"""Real file admission and queued model requests, using the existing conversation engine."""
import asyncio
import base64
import json
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.attachment_request_probe import Harness,unpack_request
from tests.file_ingress_probe import batch
from tests.queue_request_probe import settled
from tests.test_attachments import image_bytes
from xgent_app.conversations import bind_conversation
from xgent_app.interaction import interaction
from xgent_app.queue_store import item_metadata


async def queued_files(bot,root,*,recover=False,archived=False):
    async with Harness(bot,root) as h:
        manager=bot.get_conversations()
        with interaction('web','chat'):
            scope=await manager.resolve()
        if archived:
            await manager.manage('archive',scope.conversation_id)
        photo=image_bytes();text=b'QUEUED ORIGINAL TEXT\nALL BYTES';opaque=b'\x00QUEUED PATH ONLY'
        files=[('queue-image.png',photo),('queue-path.bin',opaque),('queue-notes.txt',text)]
        with patch.object(bot,'_web_chat_server',SimpleNamespace(outbox=h.outbox,config=SimpleNamespace(loop=asyncio.get_running_loop()))):
            with interaction('web','chat'),bind_conversation(scope):
                async with manager.operation(scope,execution=True):
                    data=batch(root,files,idempotency_key='queue-originals',queue=True,generation=scope.generation,
                               modes=json.dumps(['attachment','server_upload','attachment']))
                    receipt=bot._web_submit_file_batch(data,'attachment',h.outbox,conversation_id=scope.conversation_id)
                    result=await asyncio.wait_for(asyncio.wrap_future(receipt),8)
                    assert result['ok'] and result['queued'],result
                    assert not h.requests
                    assert not await h.db.get_attachment_records()
                    assert not await h.db.get_display_history(0)
                    queue=bot.get_text_queue();snapshot=await queue.snapshot(scope.conversation_id)
                    assert [file['filename'] for file in snapshot['items'][0]['files']]==[name for name,_ in files]
                    raw=await h.db.queue_item(result['id']);metadata=item_metadata(raw)
                    assert len(metadata['attachments'])==2 and len(metadata['server_uploads'])==1
                    for ref in [*metadata['attachments'],*metadata['server_uploads']]:
                        assert (Path(bot.ArtifactManager.UPLOAD_DIR)/ref['path']).is_file()
                    again=bot._web_submit_file_batch(batch(root,files,idempotency_key='queue-originals',queue=True,
                        modes=data['modes'],generation=scope.generation),'attachment',h.outbox,conversation_id=scope.conversation_id)
                    duplicate=await asyncio.wait_for(asyncio.wrap_future(again),8)
                    assert duplicate['id']==result['id'] and duplicate['duplicate']
                    if recover:
                        edited=await h.db.queue_change(scope.conversation_id,scope.generation,result['id'],raw['revision'],'edit','recover-files')
                        await h.db.queue_change(scope.conversation_id,scope.generation,result['id'],edited['revision'],'edit','recover-files')
                        from xgent_app.conversation_branching import ConversationBranchService
                        service=ConversationBranchService(h.db,code_root=root,storage_root=bot.ArtifactManager.ROOT_DIR)
                        draft=(await service.lineage(scope.conversation_id))['draft']
                        assert [item['filename'] for item in draft['media']]==[name for name,_ in files]
                        assert [item['ingress_mode'] for item in draft['media']]==['attachment','server_upload','attachment']
                        assert draft['text']=='batch caption'
                        assert not await h.db.get_attachment_records()
                        with interaction('web','chat'),bind_conversation(scope):
                            await bot.submit_ordinary_text('recovered caption',chat_id=1,request_key='web:recover-queue')
                await settled(bot)
        assert len(h.requests)==1,h.requests
        texts,images,_=unpack_request(h.requests[0]);joined='\n'.join(texts)
        assert images==[photo]
        assert 'QUEUED ORIGINAL TEXT\nALL BYTES' in joined
        assert base64.b64encode(opaque).decode() not in json.dumps(h.requests[0])
        records=await h.db.get_attachment_records()
        assert records and len(json.loads(records[0]['metadata'])['attachments'])==2
        assert all(not task.done() or task.exception() is None for task in queue._tasks.values())
        return {'originals':True,'pending_hidden':True,'modes_preserved':True,'model_received_once':True,'recovered':recover}
