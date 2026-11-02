"""Web and Telegram select independent modes for the same generated reply."""
import asyncio

import pytest

from tests.test_thinking_params import run_in_app
from xgent_app.response_modes import response_policy


@pytest.mark.parametrize('bot_mode', ['foreground', 'background', 'nonstream'])
@pytest.mark.parametrize('web_mode', ['foreground', 'nonstream'])
def test_policy_preserves_one_generation_and_independent_target_modes(bot_mode, web_mode):
    config = {'stream_mode': bot_mode != 'nonstream', 'stream_style': bot_mode,
              'web_response_mode': web_mode}
    web = response_policy(config, 'web')
    telegram = response_policy(config, 'telegram')
    assert web.generation_mode == web_mode and web.telegram_mode == bot_mode
    assert telegram.generation_mode == ('nonstream' if bot_mode == 'nonstream' else 'foreground')
    assert telegram.telegram_mode == bot_mode


def test_legacy_initialization_and_independent_settings_remain_persisted(tmp_path):
    result = run_in_app('''import asyncio
from tests.attachment_request_probe import Harness
async def test(root):
    async with Harness(bot,root) as h:
        first = await h.db.ensure_web_response_mode()
        assert first == 'nonstream'
        await bot._web_write_setting('response_mode','foreground')
        assert not bot.UserDataManager.get('stream_mode')
        await bot._web_write_setting('telegram_response_mode','background')
        assert bot.UserDataManager.get('web_response_mode') == 'foreground'
        data=(await bot._web_read_settings())['values']
        assert data['response_mode']=='foreground' and data['telegram_response_mode']=='background'
        await bot._web_write_setting('stream_mode',False)
        assert bot.UserDataManager.get('stream_mode') is True
        assert await h.db.ensure_web_response_mode()=='nonstream'
        await bot._web_write_setting('response_mode','background')
        assert bot.UserDataManager.get('web_response_mode')=='foreground'
        assert bot.UserDataManager.get('stream_style')=='background'
        return {'separate':True,'legacy':True}
''' + f'print(json.dumps(asyncio.run(test({str(tmp_path)!r}))))')
    assert all(result.values())


def test_mode_changes_during_tool_execution_apply_only_to_next_new_request(tmp_path):
    result = run_in_app('''import asyncio
from unittest.mock import patch
from tests.native_tool_probe import NativeHarness,call
async def test(root):
    async with NativeHarness(bot,root,'openai_compatible','foreground') as h:
        async def execute(command,stop_event=None):
            await bot._web_write_setting('response_mode','nonstream')
            await bot._web_write_setting('telegram_response_mode','background')
            return {'success':True,'return_code':0,'output':'ACTUAL_RESULT'}
        h.responses=[([call(command='mocked-only')],''),([], 'FIRST_FINAL')]
        with patch.object(bot.AgentExecutor,'run_command',execute):
            await h.turn('keep mode during tools')
        assert [request['stream'] for request in h.requests]==[True,True]
        h.responses=[([], 'SECOND_FINAL')]
        await h.turn('new request uses new mode')
        assert h.requests[-1]['stream'] is False
        return {'fixed_turn':True,'next_request':True}
''' + f'print(json.dumps(asyncio.run(test({str(tmp_path)!r}))))')
    assert all(result.values())


@pytest.mark.parametrize('telegram_mode', ['foreground', 'background', 'nonstream'])
def test_web_receives_live_body_before_shared_telegram_delivery_finishes(tmp_path, telegram_mode):
    result = run_in_app('''import asyncio,time
from unittest.mock import patch
from tests.native_tool_probe import NativeHarness
from tests.telegram_rich_probe import RichCapture
from tests.test_channel_isolation import _FakeStore
from xgent_app.fanout import ChannelWorker
from xgent_app.web_bridge import build_web_mirror_objects,deliver_op_to_bot
async def test(root,telegram_mode):
    async with NativeHarness(bot,root,'openai','foreground') as h:
        await bot.UserDataManager.save_config('stream_mode',telegram_mode!='nonstream')
        await bot.UserDataManager.save_config('stream_style',telegram_mode if telegram_mode!='nonstream' else 'foreground')
        native=RichCapture();original=native._post
        async def slow(method,*args,**kwargs):
            await asyncio.sleep(.15)
            return await original(method,*args,**kwargs)
        native._post=slow
        async def deliver(op,mid):return await deliver_op_to_bot(native,op,mid)
        worker=ChannelWorker('web-independent-stream',deliver,store=_FakeStore())
        h.update,h.context,_=build_web_mirror_objects(1,h.outbox,native,worker)
        calls=0;complete=False
        async def generate(*args,**kwargs):
            nonlocal calls,complete
            calls+=1
            for token in ['FIRST_VISIBLE_LINE\\n','SECOND_VISIBLE_LINE\\n','FINAL_VISIBLE_LINE']:
                yield token
                await asyncio.sleep(.2)
            complete=True
        with patch.object(bot.ModelClient,'think_and_reply_stream',generate):
            task=asyncio.create_task(h.turn('one shared response'))
            await asyncio.sleep(.18)
            frames=h.drain_frames()
            assert not complete
            assert 'FIRST_VISIBLE_LINE' in json.dumps(frames),frames
            await task
        assert calls==1
        assert await worker.wait_idle(8)
        all_frames=frames+h.drain_frames()
        assert any(row['msg_type']=='ai_reply' and 'FINAL_VISIBLE_LINE' in row['content']
                   for row in await h.db.get_display_history(100))
        if telegram_mode!='foreground':assert not native.drafts
        assert sum(method=='sendRichMessage' for method,_ in native.api_calls)==1,native.api_calls
        await worker.aclose()
        return {'live_web':True,'one_model_request':True,'telegram_mode':telegram_mode}
''' + f'print(json.dumps(asyncio.run(test({str(tmp_path)!r},{telegram_mode!r}))))')
    assert result == {'live_web': True, 'one_model_request': True, 'telegram_mode': telegram_mode}
