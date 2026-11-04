"""Resend and withdraw originals against the actual queue/delivery boundaries."""
import asyncio
import hashlib
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests.attachment_request_probe import Harness
from tests.file_ingress_probe import batch
from tests.notification_sync_probe import PendingChannel
from tests.telegram_chat_probe import TelegramCapture
from tests.test_attachments import image_bytes
from tests.test_channel_isolation import _FakeStore
from xgent_app.conversation_branching import ConversationBranchService
from xgent_app.conversations import bind_conversation
from xgent_app.fanout import ChannelWorker, OP_DOCUMENT, Op
from xgent_app.interaction import interaction
from xgent_app.presentation import metadata_dict
from xgent_app.web_bridge import deliver_op_to_bot
from xgent_app.file_ingress import FileTransportCapabilities


async def verify(bot, root, phase='delivered', new_file=False, long_caption=False):
    async with Harness(bot, root) as h:
        entered, release=asyncio.Event(),asyncio.Event()
        connected=phase!='reconnect'
        class Native(TelegramCapture):
            id=8201
            def __init__(self):
                super().__init__();self.files=[]
            async def send_document(self,chat_id,document,filename,**kwargs):
                if not connected:
                    from telegram.error import TimedOut
                    raise TimedOut('fixture offline')
                if phase=='inflight':
                    entered.set();await release.wait()
                content=document.read()
                message=self.message('',chat_id)
                self.files.append((filename,content,message.message_id))
                self.save(message.message_id,kwargs.get('caption',''),chat_id=chat_id)
                return message
        native,pending,store=Native(),PendingChannel(),_FakeStore()
        pending.is_open=lambda:False
        worker=ChannelWorker('resend-originals',lambda op,mid:deliver_op_to_bot(native,op,mid),store=store)
        original={'原件图.png':image_bytes(),'原件档.txt':b'EXACT_SERVER_UPLOAD\r\n  spaces\n','原件视频.mp4':b'EXACT_VIDEO_BYTES'}
        upload_root=Path(bot.ArtifactManager.UPLOAD_DIR);upload_root.mkdir(parents=True,exist_ok=True)
        refs=[]
        for index,(name,content) in enumerate(original.items()):
            (upload_root/name).write_bytes(content)
            refs.append({'version':1,'path':name,'name':name,'storage':'uploads','order':index,'size':len(content),
                         'id':hashlib.sha256(name.encode()).hexdigest(),'kind':['image','text','binary'][index],
                         'sha256':hashlib.sha256(content).hexdigest(),
                         'mime_type':['image/png','text/plain','video/mp4'][index]})
        other=(await bot.get_conversations().manage('create',name='B keep'))['conversation_id']
        with bind_conversation(await bot.get_conversations().resolve(other)):
            await bot.GlobalRecorder.record_user_message('B remains')
        native.messages[99999]={'text':'B native remains','chat_id':1}
        scope=replace(await bot.get_conversations().resolve('global_memory'),origin='web',purpose='chat',telegram_delivery=True)
        with interaction('web','chat'),bind_conversation(scope),patch.object(bot,'_web_real_bot',native),patch.object(bot,'telegram_channel',return_value=pending):
            metadata={'attachments':[refs[0],refs[2]],'server_uploads':[refs[1]],
                      'web_file_message':{'version':1,'text':'原始说明\n  保留缩进'},
                      'telegram_delivery':{'bot_id':native.id,'chat_id':1,'ids':[66],'conversation_id':scope.conversation_id}}
            native.messages[66]={'text':'old source','chat_id':1}
            source_id=await bot.GlobalRecorder.record_user_message('原始说明\nFILE_INDEX',bot.MessageType.USER_FILE,metadata=metadata)
            service=ConversationBranchService(h.db,code_root=root,storage_root=bot.ArtifactManager.ROOT_DIR)
            async def withdraw(row_id,key):
                preview=await service.withdraw_preview(scope.conversation_id,row_id)
                result=await service.withdraw(scope.conversation_id,row_id,{'confirm':True,'turn_id':preview['turn_id'],
                    'current_digest':preview['current_digest'],'request_id':key})
                await bot._delete_withdrawn_telegram(result['telegram_native_message_ids'],[],key)
                return result
            try:
                restored=await withdraw(source_id,'restore-source')
                assert [item['filename'] for item in restored['draft']['media']]==list(original)
                for op in pending.operations:await worker._handle(op)
                pending.operations.clear()
                assert list(native.messages)==[99999]
                active=replace(await bot.get_conversations().resolve(scope.conversation_id),origin='web',purpose='chat',telegram_delivery=True)
                with bind_conversation(active):
                    if new_file:
                        draft=restored['draft']
                        await service.update_draft(active.conversation_id,{'source_record_id':source_id,'revision':draft['revision'],
                            'keep':['attachments:0','server_uploads:0']})
                        process=AsyncMock()
                        with patch.object(bot,'process_conversation',process),patch.object(bot,'build_web_mirror_objects',return_value=(h.update,h.context,None)):
                            receipt=Future()
                            await bot._web_run_file_batch(batch(Path(root),[('新增.txt',b'NEW_BYTES')],text='重新说明',
                                idempotency_key='mixed-resend'), 'attachment',h.outbox,receipt)
                            assert receipt.result()['ok'] and process.await_count==1,(receipt.result(),h.drain_frames())
                            row_id=receipt.result()['record_id']
                            again=Future()
                            await bot._web_run_file_batch(batch(Path(root),[('新增.txt',b'NEW_BYTES')],text='重新说明',
                                idempotency_key='mixed-resend'), 'attachment',h.outbox,again)
                            assert again.result()['duplicate'] and process.await_count==1
                        expected=[('原件图.png',original['原件图.png']),('原件档.txt',original['原件档.txt']),('新增.txt',b'NEW_BYTES')]
                        row=await h.db.get_display_message(row_id)
                        all_refs=[*metadata_dict(row['metadata'])['attachments'],*metadata_dict(row['metadata'])['server_uploads']]
                        assert next(ref['order'] for ref in all_refs if ref['name']=='新增.txt')==2
                        operations=[]
                    else:
                        await h.db.queue_register('resend-instance')
                        text=('完整说明 🙂\n'*800+'LONG_TEXT_TAIL') if long_caption else '重新说明'
                        await h.db.queue_enqueue(scope=active,instance='resend-instance',request_key='resend-originals',text=text,chat_id=1)
                        async with bot.get_conversations().operation(active.conversation_id,execution=True,fresh=True) as running:
                            claimed=await h.db.queue_claim(running)
                            row_id=claimed[0]['record_id']
                            await bot.publish_queued_users(h.context,claimed)
                        operations=list(pending.operations);pending.operations.clear()
                        assert not native.files and len([op for op in operations if op.kind==OP_DOCUMENT])==3
                        assert all(op.payload['_record_id']==row_id for op in operations)
                        assert 'telegram_delivery' not in metadata_dict((await h.db.get_display_message(row_id))['metadata'])
                        expected=list(original.items())
                        if phase in {'delivered','reconnect'}:
                            for op in operations:await worker._handle(op)
                            if phase=='reconnect':
                                assert len(store.rows)==3 and not native.files
                                assert all(Op.from_row(row).payload['path'] for row in store.rows)
                                connected=True;worker._breaker.record_success();await worker._drain_store(0)
                                assert not store.rows
                    task=None
                    if phase=='inflight':
                        task=asyncio.create_task(worker._handle(operations[0]))
                        await asyncio.wait_for(entered.wait(),3)
                    if phase in {'delivered','reconnect'}:
                        assert [(name,content) for name,content,_ in native.files]==expected
                        row=await h.db.get_display_message(row_id)
                        assert set(metadata_dict(row['metadata'])['telegram_delivery']['ids'])==set(native.messages)-{99999}
                        if long_caption:assert any('LONG_TEXT_TAIL' in message['text'] for message in native.messages.values())
                        else:assert '重新说明' in native.messages[native.files[0][2]]['text']
                    result=await withdraw(row_id,'withdraw-resend')
                    for op in pending.operations:await worker._handle(op)
                    pending.operations.clear()
                    if phase=='pending':
                        for op in operations:await worker._handle(op)
                        assert not native.files
                    if task:
                        release.set();await task
                        for op in operations[1:]:await worker._handle(op)
                        assert len(native.files)==1
                    assert list(native.messages)==[99999]
                    assert not await h.db.get_display_history(100)
                    assert 'telegram_delivery' not in result['draft']['metadata']
                with bind_conversation(await bot.get_conversations().resolve(other)):
                    assert 'B remains' in str(await h.db.get_display_history(100))
                assert all((upload_root/name).read_bytes()==content for name,content in original.items())
                assert not h.requests
                return {'originals':True,'ordered':True,'fresh_delivery_ids':True,'second_withdraw':True,'other_conversation_kept':True}
            finally:
                release.set();await worker.aclose()


async def transport_limits(bot,root):
    async with Harness(bot,root):
        pending=PendingChannel()
        scope=replace(await bot.get_conversations().resolve('global_memory'),origin='web',purpose='chat',telegram_delivery=True)
        with interaction('web','chat'),bind_conversation(scope),patch.object(bot,'_web_real_bot',object()),patch.object(bot,'telegram_channel',return_value=pending),patch.object(bot.os.path,'getsize',return_value=200*1024*1024):
            await bot.sync_web_attachment_to_telegram('original.bin','original.bin','说明',queued=True,record_id=77,
                transport_capabilities=FileTransportCapabilities())
            assert pending.operations and not any(op.kind==OP_DOCUMENT for op in pending.operations)
            assert all(op.payload['_record_id']==77 for op in pending.operations)
            pending.operations.clear()
            await bot.sync_web_attachment_to_telegram('original.bin','original.bin','说明',queued=True,record_id=77,
                transport_capabilities=FileTransportCapabilities('local_bot_api',None,2000*1024*1024,2000*1024*1024))
            assert len(pending.operations)==1
            op=pending.operations[0]
            assert op.kind==OP_DOCUMENT and op.payload['path']=='original.bin'
            assert op.payload['local_api'] and op.payload['kwargs']['read_timeout']==op.payload['kwargs']['write_timeout']==240
            assert op.payload['_record_id']==77 and not op.transient
            return {'cloud_limit_preserved':True,'local_limit_and_timeout_preserved':True,'stable_path':True}
