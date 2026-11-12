"""One shared stream switch, immediate Web/CLI and paced Bot body previews."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_thinking_params import run_in_app
from tests.test_telegram_native import operation
from tests.telegram_rich_probe import RichCapture
from xgent_app.response_modes import response_policy
from xgent_app.stop_targets import begin_phase, end_phase
from xgent_app.telegram_native import OP_NATIVE_CONTROL, OP_NATIVE_DRAFT, OP_NATIVE_RENDER
from xgent_app.web_bridge import deliver_op_to_bot


@pytest.mark.parametrize('enabled', [False, True, 'off', 'true'])
@pytest.mark.parametrize('origin', ['web', 'telegram', 'cli'])
def test_shared_policy_ignores_retired_per_client_modes(enabled, origin):
    config = {'stream_mode': enabled, 'stream_style': 'foreground', 'web_response_mode': 'nonstream'}
    policy = response_policy(config, origin)
    streaming = enabled in (True, 'true')
    assert policy.generation_mode == ('foreground' if streaming else 'nonstream')
    assert policy.telegram_mode == ('background' if streaming else 'nonstream')


def test_settings_aliases_share_persistence_and_peer_changes_are_read_fresh(tmp_path):
    result = run_in_app('''import asyncio
from tests.attachment_request_probe import Harness
from tests.test_database_write_lock import _load_db_class
async def test(root):
    async with Harness(bot,root) as h:
        assert await h.db.ensure_web_response_mode()=='nonstream'
        for key,value,enabled in [('response_mode','foreground',True),('telegram_response_mode','nonstream',False),
                                  ('web_response_mode','background',True),('stream_mode',False,False)]:
            await bot._web_write_setting(key,value)
            data=(await bot._web_read_settings())['values']
            assert data['stream_mode'] is enabled
            assert data['response_mode']==data['web_response_mode']==('foreground' if enabled else 'nonstream')
            assert data['telegram_response_mode']==('background' if enabled else 'nonstream')
            assert data['stream_style']=='background'
        peer=_load_db_class()(h.db.db_path)
        try:
            await peer.set_response_mode('background')
            values=await bot.UserDataManager.refresh_response_modes()
            assert values['stream_mode'] is True and values['web_response_mode']=='foreground'
        finally:await peer.close()
        data=await bot._web_read_settings()
        assert [option['value'] for option in data['options']['telegram_response_mode']]==['background','nonstream']
        return {'shared':True,'peer_fresh':True,'two_bot_choices':True}
''' + f'print(json.dumps(asyncio.run(test({str(tmp_path)!r}))))')
    assert all(result.values())


def test_mode_change_during_tools_affects_next_turn_only(tmp_path):
    result = run_in_app('''import asyncio
from unittest.mock import patch
from tests.native_tool_probe import NativeHarness,call
async def test(root):
    async with NativeHarness(bot,root,'openai_compatible','foreground') as h:
        async def execute(command,stop_event=None):
            await bot._web_write_setting('telegram_response_mode','nonstream')
            return {'success':True,'return_code':0,'output':'ACTUAL_RESULT'}
        h.responses=[([call(command='mocked-only')],''),([], 'FIRST_FINAL')]
        with patch.object(bot.AgentExecutor,'run_command',execute):await h.turn('keep mode during tools')
        assert [request['stream'] for request in h.requests]==[True,True]
        h.responses=[([], 'SECOND_FINAL')]
        await h.turn('new turn uses shared new mode')
        assert h.requests[-1]['stream'] is False
        return {'fixed_turn':True,'next_request':True}
''' + f'print(json.dumps(asyncio.run(test({str(tmp_path)!r}))))')
    assert all(result.values())


def test_background_previews_send_body_in_paced_batches_and_finalize_without_wait():
    async def test():
        bot = RichCapture()
        ref = begin_phase('run', 'model')
        waiting = operation(OP_NATIVE_CONTROL, ref, durable=False)
        waiting.payload['telegram_native'].update(mode='background', raw='')
        await deliver_op_to_bot(bot, waiting, None)
        control_id = next(iter(bot.messages))
        clock = [100.0]
        async def sleep(delay):
            clock[0] += delay
        def preview(text):
            value = operation(OP_NATIVE_DRAFT, ref, durable=False)
            value.payload['telegram_native'].update(mode='background', raw=text, fallback=[text])
            return value
        with patch('xgent_app.telegram_native.time.monotonic', side_effect=lambda: clock[0]), \
                patch('xgent_app.telegram_native.asyncio.sleep', new=AsyncMock(side_effect=sleep)) as pauses:
            await deliver_op_to_bot(bot, preview('FIRST_BATCH'), None)
            assert 'FIRST_BATCH' in bot.messages[control_id]['text']
            clock[0] += .5
            await deliver_op_to_bot(bot, preview('FIRST_BATCH SECOND_BATCH'), None)
            pauses.assert_awaited_once()
            assert pauses.await_args.args[0] == pytest.approx(2.5)
            assert 'FIRST_BATCH SECOND_BATCH' in bot.messages[control_id]['text']
            count = len(bot.api_calls)
            await deliver_op_to_bot(bot, preview('FIRST_BATCH SECOND_BATCH'), None)
            assert len(bot.api_calls) == count
            assert not bot.drafts
            end_phase('run', ref)
            final = operation(OP_NATIVE_RENDER, ref, html=['<p>FIRST_BATCH SECOND_BATCH FINAL</p>'])
            final.payload['telegram_native'].update(mode='background', raw='FIRST_BATCH SECOND_BATCH FINAL')
            mid = await deliver_op_to_bot(bot, final, None)
            assert list(bot.messages) == [mid]
            assert bot.messages[mid]['text']=='<p>FIRST_BATCH SECOND_BATCH FINAL</p>'
            assert pauses.await_count == 1
    asyncio.run(test())


def test_long_background_preview_keeps_all_parts_and_finalization_reuses_them():
    async def test():
        bot = RichCapture()
        ref = begin_phase('run', 'model')
        waiting = operation(OP_NATIVE_CONTROL, ref, durable=False)
        waiting.payload['telegram_native'].update(mode='background', raw='')
        await deliver_op_to_bot(bot, waiting, None)
        preview = operation(OP_NATIVE_DRAFT, ref, durable=False)
        preview.payload['telegram_native'].update(mode='background', raw='FIRST_PART SECOND_PART',
            fallback=['FIRST_PART', 'SECOND_PART'])
        await deliver_op_to_bot(bot, preview, None)
        ids = list(bot.messages)
        assert len(ids) == 2
        assert bot.messages[ids[0]]['text'] == 'FIRST_PART'
        assert 'SECOND_PART' in bot.messages[ids[1]]['text']
        assert bot.messages[ids[0]]['reply_markup'] is None
        assert bot.messages[ids[1]]['reply_markup'] is not None
        end_phase('run', ref)
        final = operation(OP_NATIVE_RENDER, ref, html=['<p>FIRST_PART</p>', '<p>SECOND_PART FINAL</p>'])
        final.payload['telegram_native'].update(mode='background', raw='FIRST_PART SECOND_PART FINAL')
        await deliver_op_to_bot(bot, final, None)
        assert list(bot.messages) == ids
        assert [bot.messages[mid]['text'] for mid in ids] == ['<p>FIRST_PART</p>', '<p>SECOND_PART FINAL</p>']
        assert bot.messages[ids[0]]['reply_markup'] is None and bot.messages[ids[1]]['reply_markup'] is None
    asyncio.run(test())


def test_discarding_background_preview_removes_its_full_sequence():
    from xgent_app.telegram_native import OP_NATIVE_DELETE
    async def test():
        bot = RichCapture()
        ref = begin_phase('run', 'model')
        preview = operation(OP_NATIVE_DRAFT, ref, durable=False)
        preview.payload['telegram_native'].update(mode='background', raw='FIRST_PART SECOND_PART',
            fallback=['FIRST_PART', 'SECOND_PART'])
        await deliver_op_to_bot(bot, preview, None)
        assert len(bot.messages) == 2
        deletion = operation(OP_NATIVE_DELETE, ref)
        deletion.payload['telegram_native'].update(mode='background')
        await deliver_op_to_bot(bot, deletion, None)
        assert not bot.messages
        end_phase('run', ref)
    asyncio.run(test())


def test_web_receives_live_body_while_bot_batches_its_own_updates(tmp_path):
    result = run_in_app('''import asyncio
from unittest.mock import patch
from tests.native_tool_probe import NativeHarness
from tests.telegram_rich_probe import RichCapture
from tests.test_channel_isolation import _FakeStore
from xgent_app.fanout import ChannelWorker
from xgent_app.web_bridge import build_web_mirror_objects,deliver_op_to_bot
async def test(root):
    async with NativeHarness(bot,root,'openai','foreground') as h:
        native=RichCapture()
        async def deliver(op,mid):return await deliver_op_to_bot(native,op,mid)
        worker=ChannelWorker('shared-stream-preview',deliver,store=_FakeStore())
        h.update,h.context,_=build_web_mirror_objects(1,h.outbox,native,worker)
        first,second,finish=asyncio.Event(),asyncio.Event(),asyncio.Event()
        calls=0
        async def generate(*args,**kwargs):
            nonlocal calls
            calls+=1
            yield 'FIRST_VISIBLE_LINE\\n';first.set()
            await second.wait();yield 'SECOND_VISIBLE_LINE\\n'
            await finish.wait();yield 'FINAL_VISIBLE_LINE'
        task=None
        try:
            with patch.object(bot.ModelClient,'think_and_reply_stream',generate):
                task=asyncio.create_task(h.turn('one shared streamed reply'))
                await asyncio.wait_for(first.wait(),10);await asyncio.sleep(.45)
                frames=h.drain_frames()
                assert 'FIRST_VISIBLE_LINE' in json.dumps(frames)
                second.set();await asyncio.sleep(.4)
                assert 'SECOND_VISIBLE_LINE' in json.dumps(h.drain_frames())
                assert not finish.is_set()
                finish.set();await asyncio.wait_for(task,15)
            assert calls==1 and await worker.wait_idle(10)
            assert not native.drafts
            assert any('FIRST_VISIBLE_LINE' in data.get('text','') for method,data in native.api_calls if method=='editMessageText')
            assert any('FINAL_VISIBLE_LINE' in row['content'] for row in await h.db.get_display_history(100) if row['msg_type']=='ai_reply')
            return {'live_web':True,'paced_bot_body':True,'one_request':True}
        finally:
            first.set();second.set();finish.set()
            if task is not None and not task.done():await asyncio.gather(task,return_exceptions=True)
            await worker.aclose()
''' + f'print(json.dumps(asyncio.run(test({str(tmp_path)!r}))))')
    assert all(result.values())
