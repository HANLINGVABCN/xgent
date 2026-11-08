"""Use actual Telegram entry handlers while a different turn owns execution."""
import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from tests.attachment_request_probe import Harness,upload_update,unpack_request
from tests.test_attachments import image_bytes
from tests.queue_request_probe import settled
from xgent_app.conversations import bind_conversation,current_scope
from xgent_app.interaction import interaction


class Prompt:
    def __init__(self,text,events):self.text=text;self.events=events;self.deleted=False;self.message_id=9000+len(events)
    async def edit_text(self,text,**kwargs):self.text=text;self.events.append(('edit',text))
    async def delete(self):self.deleted=True;self.events.append(('delete',self.text))
    async def edit_reply_markup(self,**kwargs):pass


async def manual_files(bot,root,fallback=False):
    async with Harness(bot,root) as h:
        manager=bot.get_conversations();events=[];prompts=[];queue=bot.get_text_queue();await queue.start()
        async def prompt(text,**kwargs):
            value=Prompt(text,events);prompts.append(value);events.append(('prompt',text));return value
        async def download(media,destination=None):
            await asyncio.sleep(media.delay if hasattr(media,'delay') else 0)
            if destination:Path(destination).write_bytes(media.data);return destination
            return media.data
        async def dispatch(batch):
            assert all(p.deleted for p in prompts),'拼接提示必须在 AI 回答前清理'
            events.append(('model',None))
            await bot.publish_queued_users(h.context,batch)
            await bot.process_conversation(h.update,h.context,batch[-1]['text'],queued_messages=batch)
        queue.dispatch=dispatch
        files=[('document','slow-image.png',image_bytes('PNG',color='blue')),
               ('document','fast-image.webp',image_bytes('WEBP',color='green')),
               ('photo','telegram_photo.jpg',image_bytes('JPEG',color='yellow')),
               ('document','notes.txt',b'FULL TEXT ORIGINAL\nTAIL'),
               ('document','unknown.bin',b'\x00keep every byte'),
               ('voice','voice_105.oga',b'OggS\x00original-voice')]
        pairs=[]
        for index,(kind,name,data) in enumerate(files):
            if kind=='voice':
                pair=upload_update(h,'document',100+index,data,caption='',name=name)
                pair[0].message.document=None;pair[0].message.voice=SimpleNamespace(data=data,mime_type='audio/ogg')
            else:pair=upload_update(h,kind,100+index,data,group='mixed-docs' if index<2 else None,caption='附言 '+str(index),name=name)
            pair[0].message.reply_text=prompt
            media=pair[0].message.photo[-1] if kind=='photo' else pair[0].message.voice if kind=='voice' else pair[0].message.document
            media.delay=.04 if index==0 else .005
            pairs.append(pair)
        with interaction('telegram','chat'),bind_conversation(replace(await manager.resolve(),origin='telegram')),patch.object(bot,'download_telegram_file',download),patch.object(bot,'_web_chat_server',SimpleNamespace(outbox=h.outbox)):
            async with manager.operation(execution=True):
                incoming=replace(current_scope(),origin='telegram',run_id=None)
                with bind_conversation(incoming):
                    handlers=[bot.handle_media_message if kind=='voice' else bot.handle_photo_message if kind=='photo' else bot.handle_document_message for kind,_,_ in files]
                    await asyncio.gather(*(handler(*pair) for handler,pair in zip(handlers,pairs)),handlers[0](*pairs[0]))
                    assert len(prompts)==1 and not h.requests
                    key=bot.get_text_conversation_buffer_key(pairs[0][0]);pending=bot._pending_text_conversations[key]
                    assert [p['attachment']['source_message_id'] for p in pending.attachments]==list(range(100,106))
                    assert not await h.db.get_attachment_records()
                    assert not (await queue.snapshot(incoming.conversation_id))['items']
                    textpair=upload_update(h,'document',106,b'',caption='');textpair[0].message.reply_text=prompt
                    if fallback:
                        async def broken_edit(*args,**kwargs):raise OSError('模拟旧提示编辑失败')
                        prompts[0].edit_text=broken_edit
                    await bot.handle_normal_text_conversation(*textpair,'一起看看这六个附件')
                    assert len(prompts)==(2 if fallback else 1)
                    callback=SimpleNamespace(message=None,callback_query=SimpleNamespace(answer=AsyncMock()),effective_chat=h.update.effective_chat,effective_user=h.update.effective_user)
                    with interaction('telegram','management'),bind_conversation(replace(incoming,purpose='management')):
                        await bot.finish_text_conversation(callback,h.context)
                        await bot.finish_text_conversation(callback,h.context)
                    items=(await queue.snapshot(incoming.conversation_id))['items'];assert len(items)==1
                    assert not h.requests and all(p.deleted for p in prompts)
                    assert not bot.has_pending_text_conversation(pairs[0][0])
            await settled(bot)
        assert len(h.requests)==1
        texts,images,_=unpack_request(h.requests[0]);assert images==[entry[2] for entry in files[:3]]
        assert 'FULL TEXT ORIGINAL\nTAIL' in '\n'.join(texts) and '一起看看这六个附件' in '\n'.join(texts)
        rows=await h.db.get_attachment_records();assert len(rows)==1
        import json
        refs=json.loads(rows[0]['metadata'])['attachments'];assert len(refs)==6
        for reference,entry in zip(refs,files):assert (Path(bot.ArtifactManager.UPLOAD_DIR)/reference['path']).read_bytes()==entry[2]
        assert not any('拼接' in row['content'] for row in await h.db.get_display_history(0) if row['msg_type']!='user_file')
        return {'all_files_stitched':True,'not_auto_sent':True,'busy_not_rejected':True,'one_prompt':True,'prompts_removed':True,'one_model_request':True,'original_bytes':True}


async def unfinished_restart(bot,root,restore=False):
    async with Harness(bot,root) as h:
        prompts=[];events=[]
        async def prompt(text,**kwargs):value=Prompt(text,events);prompts.append(value);events.append(('prompt',text));return value
        async def download(media,destination=None):
            if destination:Path(destination).write_bytes(media.data);return destination
            return media.data
        scope=replace(await bot.get_conversations().resolve(),origin='telegram')
        with interaction('telegram','chat'),bind_conversation(scope),patch.object(bot,'download_telegram_file',download):
            pair=upload_update(h,'document',1001,image_bytes(),name='restart.png',caption='保留到手动发送');pair[0].message.reply_text=prompt
            if not restore:
                await bot.handle_document_message(*pair)
                assert not h.requests and not await h.db.get_attachment_records()
            else:
                assert not bot._pending_text_conversations
                callback=SimpleNamespace(message=None,callback_query=SimpleNamespace(answer=AsyncMock()),effective_chat=h.update.effective_chat,effective_user=h.update.effective_user)
                with interaction('telegram','management'),bind_conversation(replace(scope,purpose='management')):
                    await bot.restore_text_stitch(callback,pair[1])
                    pending=bot._pending_text_conversations[bot.get_text_conversation_buffer_key(callback)]
                assert len(pending.attachments)==1 and Path(bot.ArtifactManager.UPLOAD_DIR,pending.attachments[0]['attachment']['path']).read_bytes()==image_bytes()
                assert not h.requests and not await h.db.get_attachment_records()
                queue=bot.get_text_queue();await queue.start()
                async def dispatch(batch):await bot.process_conversation(h.update,h.context,batch[-1]['text'],queued_messages=batch)
                queue.dispatch=dispatch
                deleted=[]
                async def delete(**kwargs):deleted.append(kwargs['message_id'])
                with patch.object(pair[1].bot,'delete_message',delete):
                    with interaction('telegram','management'),bind_conversation(replace(scope,purpose='management')):
                        await bot.finish_text_conversation(callback,pair[1])
                    await settled(bot)
                assert len(h.requests)==1 and deleted==pending.prompt_ids,(len(h.requests),deleted,pending.prompt_ids)
                assert unpack_request(h.requests[0])[1]==[image_bytes()]
            return {'saved_for_manual_send':True,'restored_without_auto_send':True,'original_preserved':True}


async def downloads_and_failure(bot,root):
    async with Harness(bot,root) as h:
        events=[];prompts=[];started=asyncio.Event();release=asyncio.Event()
        async def prompt(text,**kwargs):value=Prompt(text,events);prompts.append(value);events.append(('prompt',text));return value
        async def download(media,destination=None):
            if media.file_name=='slow.png':started.set();await release.wait()
            if media.file_name=='failed.png':raise OSError('模拟下载失败')
            Path(destination).write_bytes(media.data);return destination
        with interaction('telegram','chat'),bind_conversation(replace(await bot.get_conversations().resolve(),origin='telegram')),patch.object(bot,'download_telegram_file',download):
            slow=upload_update(h,'document',2001,image_bytes(),name='slow.png');slow[0].message.reply_text=prompt
            task=asyncio.create_task(bot.handle_document_message(*slow));await asyncio.wait_for(started.wait(),5)
            message=upload_update(h,'document',2002,b'');message[0].message.reply_text=prompt
            await bot.handle_normal_text_conversation(*message,'下载时追加的文字')
            await bot.finish_text_conversation(*message);assert not h.requests
            release.set();await task
            failed=upload_update(h,'document',2003,image_bytes(),name='failed.png');failed[0].message.reply_text=prompt
            await bot.handle_document_message(*failed)
            pending=bot._pending_text_conversations[bot.get_text_conversation_buffer_key(message[0])]
            assert len(pending.attachments)==1 and pending.parts==['下载时追加的文字']
            queue=bot.get_text_queue();await queue.start()
            with patch.object(queue,'submit',AsyncMock(side_effect=OSError('模拟数据库提交失败'))):
                try:await bot.finish_text_conversation(*message)
                except OSError:pass
                else:raise AssertionError('Expected submission error')
            assert not pending.committing and all(not p.deleted for p in pending.prompt_messages)
            assert Path(bot.ArtifactManager.UPLOAD_DIR,pending.attachments[0]['attachment']['path']).is_file()
            await bot.cancel_text_conversation(message[0]);assert not Path(bot.ArtifactManager.UPLOAD_DIR,pending.attachments[0]['attachment']['path']).exists()
            assert not h.requests
        return {'download_pending_not_sent':True,'text_joins_during_download':True,'failure_keeps_other_files':True,'failed_submit_keeps_prompt_and_files':True,'cancel_cleans_only_pending':True}


async def busy_image_rejection(bot,root):
    async with Harness(bot,root) as h:
        manager=bot.get_conversations();answers=[]
        with patch.object(bot,'download_telegram_file',AsyncMock(return_value=image_bytes())),patch.object(bot,'process_conversation',AsyncMock()) as process:
            async with manager.operation(execution=True):
                incoming=replace(current_scope(),origin='telegram',run_id=None)
                with interaction('telegram','chat'),bind_conversation(incoming):
                    for index,group in enumerate((None,'album-busy')):
                        pair=upload_update(h,'document',101+index,image_bytes(),group=group,name='busy-image.png')
                        pair[0].message.reply_text=AsyncMock(side_effect=lambda text,*a,**k:answers.append(str(text)))
                        await bot.handle_document_message(*pair)
                    pending=bot._pending_text_conversations.get(bot.get_text_conversation_buffer_key(pair[0]))
                    return {'errors':[text for text in answers if '未加入拼接' in text],'buffered':len(pending.attachments) if pending else 0,'model_started':process.await_count}


async def interleaved_native_messages(bot,root):
    from tests.telegram_rich_probe import RichCapture
    from xgent_app.web_bridge import WebMessage
    async with Harness(bot,root) as h:
        native=RichCapture();context=SimpleNamespace(bot=native);queue=bot.get_text_queue();await queue.start()
        prompt_ids=[]
        def update(mid,data=None,text=None):
            message=WebMessage(native,mid,31,text or '')
            message.document=SimpleNamespace(data=data,file_name='image-'+str(mid)+'.png',file_size=len(data),mime_type='image/png') if data else None
            message.caption='';message.photo=None;message.media_group_id=None
            native.messages[mid]={'text':text or '原始图片 '+str(mid),'reply_markup':None}
            return SimpleNamespace(message=message,effective_message=message,callback_query=None,
                effective_chat=SimpleNamespace(id=31),effective_user=SimpleNamespace(id=1))
        async def download(media,destination=None):
            Path(destination).write_bytes(media.data);return destination
        async def dispatch(batch):
            assert all(mid not in native.messages for mid in prompt_ids)
            await bot.process_conversation(h.update,h.context,batch[-1]['text'],queued_messages=batch)
        queue.dispatch=dispatch
        scope=replace(await bot.get_conversations().resolve(),origin='telegram',telegram_chat_id=31,purpose='chat')
        with interaction('telegram','chat'),bind_conversation(scope),patch.object(bot,'download_telegram_file',download):
            async with bot.get_conversations().operation(execution=True):
                first=update(1,image_bytes());await bot.telegram_entry(bot.handle_document_message)(first,context)
                pending=bot._pending_text_conversations[bot.get_text_conversation_buffer_key(first)]
                prompt_ids.append(pending.prompt_message.message_id)
                earlier=await native.send_message(31,'AI 正在输出的第一段')
                second=update(2,image_bytes('JPEG'));await bot.telegram_entry(bot.handle_document_message)(second,context)
                later=await native.send_message(31,'AI 正在输出的第二段')
                # Simulate an earlier prompt that now needs replacing below the reply.
                async def broken(*args,**kwargs):raise OSError('模拟旧提示不可编辑')
                pending.prompt_message.edit_text=broken
                text=update(3,text='两张图一起解释')
                await bot.telegram_entry(bot.handle_text_message)(text,context)
                prompt_ids.append(pending.prompt_message.message_id)
                assert pending.parts==['两张图一起解释'] and len(pending.attachments)==2
                assert not (await queue.snapshot(scope.conversation_id))['items'] and not h.requests
                query=SimpleNamespace(message=pending.prompt_message,data=bot.CallbackDataStore.store('act_finish_text_stitch'),answer=AsyncMock())
                callback=SimpleNamespace(message=None,effective_message=query.message,callback_query=query,effective_chat=first.effective_chat,effective_user=first.effective_user)
                await bot.telegram_entry(bot.handle_button_click)(callback,context)
                assert all(mid not in native.messages for mid in prompt_ids)
                assert all(mid in native.messages for mid in (1,2,3,earlier.message_id,later.message_id))
                snapshot=await queue.snapshot(scope.conversation_id)
                assert len(snapshot['items'])==1 and not h.requests
            await settled(bot)
        assert len(h.requests)==1 and unpack_request(h.requests[0])[1]==[image_bytes(),image_bytes('JPEG')]
        return {'busy_files_stitch':True,'text_joins':True,'send_enters_queue':True,'interleaved_prompts_deleted':True,'user_and_ai_messages_retained':True,'one_request':True}
