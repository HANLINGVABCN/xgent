"""Real first-send admission with mocked upstream transport and original attachments."""
import asyncio
from concurrent.futures import Future
from pathlib import Path

from tests.attachment_request_probe import Harness,unpack_request
from tests.file_ingress_probe import batch
from tests.queue_request_probe import settled
from xgent_app.conversations import bind_conversation


async def first_admission(bot,root):
    async with Harness(bot,root) as h:
        db=h.db;original=(await db.get_conversation_state())['current_chat_id']
        with bind_conversation(await bot.get_conversations().resolve(original)):
            await bot.GlobalRecorder.record_user_message('旧对话秘密背景不能自动复制')
        before=len(await db.get_all_sessions())
        text=await bot._web_accept_text('新对话的第一个问题',new_conversation='probe-text',request_id='probe-first')
        assert text['new_conversation'] and text['queued']
        await settled(bot)
        assert len(await db.get_all_sessions())==before+1
        assert '旧对话秘密背景' not in str(h.requests[0])
        repeated=await bot._web_accept_text('新对话的第一个问题',new_conversation='probe-text',request_id='probe-first')
        assert repeated['id']==text['id']
        await settled(bot)
        assert len(h.requests)==1
        data=batch(root,[('first.txt',b'FIRST COMPLETE FILE\nALL ORIGINAL BYTES')],idempotency_key='first-file',queue=True)
        receipt=Future()
        await bot._web_accept_new_file_batch(data,'attachment',h.outbox,receipt,'probe-file','ungrouped')
        files=receipt.result();assert files['ok'] and files['queued'] and files['new_conversation']
        await settled(bot)
        assert len(h.requests)==2 and len(await db.get_all_sessions())==before+2
        assert 'FIRST COMPLETE FILE\nALL ORIGINAL BYTES' in '\n'.join(unpack_request(h.requests[-1])[0])
        assert '新对话的第一个问题' not in str(h.requests[-1]) and '旧对话秘密背景' not in str(h.requests[-1])
        again=batch(root,[('first.txt',b'FIRST COMPLETE FILE\nALL ORIGINAL BYTES')],idempotency_key='first-file',queue=True)
        receipt=Future();await bot._web_accept_new_file_batch(again,'attachment',h.outbox,receipt,'probe-file','ungrouped')
        assert receipt.result()['id']==files['id'] and receipt.result()['duplicate']
        await settled(bot);assert len(h.requests)==2
        return {'atomic_creation':True,'original_context':True,'attachment_originals':True,'idempotent_retry':True}
