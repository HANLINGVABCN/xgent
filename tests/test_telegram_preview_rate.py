"""Telegram preview pacing and explicit 429 waits do not change Web frames."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from telegram.error import RetryAfter

from tests.telegram_rich_probe import RichCapture
from tests.test_channel_isolation import _FakeStore
from tests.test_telegram_native import operation
from xgent_app.fanout import ChannelWorker, Op, OpRateLimited, OP_SEND
from xgent_app.stop_targets import begin_phase, end_phase
from xgent_app.telegram_native import OP_NATIVE_CONTROL, OP_NATIVE_DRAFT, OP_NATIVE_RENDER
from xgent_app.web_bridge import classify_telegram_error, deliver_op_to_bot


def test_retry_after_duration_is_preserved_and_does_not_count_as_disconnection():
    async def test():
        attempts=[]
        async def deliver(op,mid):
            attempts.append(op.payload['text'])
            if len(attempts)==1:raise classify_telegram_error(RetryAfter(timedelta(seconds=5)))
            return 10
        store=_FakeStore();worker=ChannelWorker('rate-limited',deliver,store=store)
        first=Op(OP_SEND,logical_id=1,chat_id=1,payload={'text':'FINAL_ONE'})
        await worker._handle(first)
        assert worker.stats()['rate_limited_seconds']>4
        assert worker.stats()['circuit']=='closed'
        await worker._handle(Op(OP_SEND,logical_id=2,chat_id=1,payload={'text':'FINAL_TWO'}))
        assert attempts==['FINAL_ONE']
        assert len(store.rows)==2 and not first.attempts
        worker._rate_until=0
        await worker._drain_store(0)
        assert attempts==['FINAL_ONE','FINAL_ONE','FINAL_TWO'] and not store.rows
    asyncio.run(test())


def test_draft_429_keeps_capability_and_only_final_reply_is_durable():
    async def test():
        native=RichCapture();original=native._post;failed=False
        async def limited(method,data=None,**kwargs):
            nonlocal failed
            if method=='sendRichMessageDraft' and not failed:
                failed=True;raise RetryAfter(3)
            return await original(method,data,**kwargs)
        native._post=limited
        store=_FakeStore()
        async def deliver(op,mid):return await deliver_op_to_bot(native,op,mid)
        worker=ChannelWorker('native-draft-rate',deliver,store=store)
        ref=begin_phase('run','model')
        await worker._handle(operation(OP_NATIVE_DRAFT,ref,durable=False))
        assert worker.stats()['rate_limited_seconds']>2 and not store.rows
        for _ in range(4):await worker._handle(operation(OP_NATIVE_DRAFT,ref,durable=False))
        end_phase('run',ref)
        await worker._handle(operation(OP_NATIVE_RENDER,ref))
        assert len(store.rows)==1
        worker._rate_until=0
        await worker._drain_store(0)
        assert not store.rows
        assert sum(method=='sendRichMessage' for method,_ in native.api_calls)==1
        assert not any(method=='editMessageText' for method,_ in native.api_calls)
    asyncio.run(test())


def test_preview_is_paced_and_stale_phase_cannot_send_after_wait():
    async def test():
        native=RichCapture();ref=begin_phase('run','model')
        await deliver_op_to_bot(native,operation(OP_NATIVE_DRAFT,ref,durable=False),None)
        before=len(native.drafts)
        async def end_while_waiting(delay):
            assert delay>0
            end_phase('run',ref)
        with patch('xgent_app.telegram_native.asyncio.sleep',side_effect=end_while_waiting) as slept:
            await deliver_op_to_bot(native,operation(OP_NATIVE_DRAFT,ref,durable=False),None)
        assert slept.await_count==1 and len(native.drafts)==before
    asyncio.run(test())


def test_background_control_never_exposes_web_body_and_equal_status_is_not_edited():
    async def test():
        native=RichCapture();ref=begin_phase('run','model')
        op=operation(OP_NATIVE_CONTROL,ref,durable=False)
        op.payload['text']='WEB_VISIBLE_CONTENT'
        op.payload['telegram_native'].update(mode='background',raw='WEB_VISIBLE_CONTENT')
        await deliver_op_to_bot(native,op,None)
        before=len(native.api_calls)
        await deliver_op_to_bot(native,op,None)
        assert len(native.api_calls)==before
        text=next(iter(native.messages.values()))['text']
        assert 'WEB_VISIBLE_CONTENT' not in text and '已生成' in text
        end_phase('run',ref)
    asyncio.run(test())
