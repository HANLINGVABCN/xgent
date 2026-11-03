"""Real compression handler, transient previews and Telegram routing, with fake models."""
import tempfile
import unittest
from pathlib import Path

import pytest

from tests.test_thinking_params import run_in_app
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session


async def display_probe(bot, root, web_mode='foreground', telegram_mode='foreground',
                        outcome='success', callback=False, routed=True, pure_web=False, return_case=False):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch
    from tests.compression_request_probe import CompressionHarness
    from tests.lossless_context_probe import assert_preserved, latest_job
    from tests.test_compression_token_usage import TelegramProbe
    from xgent_app.compression_display import current_compression_output
    from xgent_app.web_history import build_history_message

    partial = 'COMPRESS_PARTIAL_OUTPUT: 真实收到的第一段。'
    final = partial + '\nCOMPRESS_COMPLETE_OUTPUT'
    async with CompressionHarness(bot, root) as h:
        await bot.GlobalRecorder.record_user_message('KEEP_ORIGINAL_CONTEXT')
        await h.db.set_config('telegram_conversation_id', 'global_memory' if routed else None)
        for key, value in [('web_response_mode', web_mode), ('stream_mode', telegram_mode != 'nonstream'),
                           ('stream_style', 'background' if telegram_mode == 'background' else 'foreground')]:
            await bot.UserDataManager.save_config(key, value)
        before = await h.db.get_compression_snapshot()
        telegram = TelegramProbe(h.db)
        entered, release = asyncio.Event(), asyncio.Event()
        views, requests = [], []

        def received(args, kwargs, stream):
            entered.set()
            assert args[4] == '', 'Compression must have no persona, skill or Agent addon'
            assert args[5][-1]['content'] == bot.PromptFileManager.get_required('compression_prompt'), 'Compression instruction changed'
            assert 'KEEP_ORIGINAL_CONTEXT' in str(args[5]), 'Original context omitted'
            requests.append(stream)
            views.append(current_compression_output())

        def fail():
            if outcome == 'stopped':
                views[0].stop_event.set()
                raise bot.CompressionError('用户已停止压缩')
            if outcome != 'success':
                raise RuntimeError(outcome + ': ORIGINAL_FAILURE_DETAIL')

        async def stream(*args, **kwargs):
            received(args, kwargs, True)
            try:
                yield partial
                await release.wait()
                fail()
                yield '\nCOMPRESS_COMPLETE_OUTPUT'
            finally:
                entered.set()

        async def nonstream(*args, **kwargs):
            received(args, kwargs, False)
            await release.wait()
            fail()
            return final, None

        bot._ensure_web_command_map()
        with patch.object(bot, '_web_real_bot', None if pure_web else telegram), \
             patch.object(bot, 'get_web_real_bot', return_value=None if pure_web else telegram), \
             patch.object(bot, 'telegram_channel', return_value=None), \
             patch.object(bot.ModelClient, 'think_and_reply_stream', stream), \
             patch.object(bot.ModelClient, 'think_and_reply', nonstream):
            coro = (bot._web_handle_callback('cmd_compress', 1, h.outbox) if callback else
                    bot._web_handle_command('/compress', h.outbox))
            task = asyncio.create_task(bot._web_scoped_call(coro, 'global_memory', h.outbox,
                execution=True, purpose='management'))
            await asyncio.wait_for(entered.wait(), 15)
            if not views:
                await task
                raise AssertionError('Model request validation failed: '+str(h.drain_frames())[-1500:])
            view = views[0]
            await asyncio.sleep(.45)  # Shared renderer's flush interval.
            bridge = view.context.bot.original
            assert await bridge.flush_telegram(timeout=5)
            live = h.drain_frames()
            preview = str(live)
            assert ('前台流式输出中...' if web_mode == 'foreground' else '非流式输出中...') in preview
            assert (partial in preview) == (web_mode == 'foreground')
            assert not any(r['msg_type'] == 'ai_reply' for r in await h.db.get_global_messages(1000))
            sent_before = str(telegram.sent)
            if routed and not pure_web:
                assert ('后台流式输出中...' if telegram_mode == 'background' else
                        '非流式输出中...' if telegram_mode == 'nonstream' else '前台流式输出中...') in sent_before
                assert (partial in sent_before) == (web_mode == telegram_mode == 'foreground')
            else:
                assert not telegram.sent
            release.set()
            await asyncio.wait_for(task, 15)
            assert await bridge.flush_telegram(timeout=5)
            frames = live + h.drain_frames()
            entry = await latest_job(h.db)
            assert len(requests) == 1 and requests[0] == (web_mode == 'foreground')
            if outcome == 'success':
                assert entry['status'] == 'completed' and entry['summary'] == final
                if routed and not pure_web:
                    assert any('COMPRESS_COMPLETE_OUTPUT' in item['text'] and partial in item['text']
                               for item in telegram.sent)
                history = await h.db.get_display_history(1000)
                row = next(r for r in history if r['id'] == entry['response_row_id'])
                message = build_history_message(row, bot.ArtifactManager.ROOT_DIR, root)
                snapshots = [f for f in frames if f.get('record_id') == row['id'] and f['type'] == 'record_snapshot']
                assert snapshots and snapshots[-1]['text'] == message['content']
            else:
                assert entry['status'] == ('stopped' if outcome == 'stopped' else 'failed')
                assert not entry['summary']
                assert_preserved(before, await h.db.get_compression_snapshot())
                assert outcome == 'stopped' or 'ORIGINAL_FAILURE_DETAIL' in str(frames)
                assert not any(f['type'] == 'context_reset' for f in frames)
            assert not bot.get_conversations().busy()
            assert not frames[-1].get('busy', False)
            if bridge._local_channel is not None:
                await bridge._local_channel.aclose()
            result = {'preview': True, 'routing': True, 'request_isolated': True, 'context_valid': True,
                      'completed': outcome == 'success'}
            if return_case:
                result['browser_case'] = {'frames': frames, 'partial': partial, 'response': message,
                    'history': [build_history_message(r, bot.ArtifactManager.ROOT_DIR, root)
                                for r in await h.db.get_display_history(1000)]}
            return result


class CompressionDisplayTests(unittest.TestCase):
    def probe(self, **options):
        with tempfile.TemporaryDirectory() as root:
            return run_in_app('import asyncio\nfrom tests.test_compression_display import display_probe\n'
                f'print(json.dumps(asyncio.run(display_probe(bot, {root!r}, **{options!r}))))')

    def test_web_and_telegram_reply_modes_are_independent(self):
        for web in ('foreground', 'nonstream'):
            for telegram in ('foreground', 'background', 'nonstream'):
                with self.subTest(web=web, telegram=telegram):
                    assert all(self.probe(web_mode=web, telegram_mode=telegram).values())

    def test_web_button_mirrors_compression_without_mirroring_other_menus(self):
        assert all(self.probe(callback=True).values())

    def test_other_bot_conversation_and_no_bot_are_independent(self):
        for options in ({'routed': False}, {'pure_web': True}):
            assert all(self.probe(**options).values())

    def test_failures_after_partial_output_always_preserve_original_context(self):
        for error in ('ConnectError', 'ReadTimeout', '429 rate limit', 'invalid JSON', 'stopped'):
            with self.subTest(error=error):
                result = self.probe(outcome=error)
                assert result['context_valid'] and not result['completed']


def test_compression_browser_shows_preview_and_keeps_final_reply_after_refresh(full_output_server):
    case = CompressionDisplayTests().probe(telegram_mode='background', return_case=True)['browser_case']
    server, _, _, _ = full_output_server
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        try:
            records = []

            async def history(limit):
                return records

            server.config.read_history = history
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base)
            page.wait_for_function('!document.getElementById("btn-send").disabled')
            for frame in case['frames']:
                if frame['type'] == 'context_reset':
                    page.get_by_text(case['partial'], exact=False).first.wait_for()
                    records[:] = case['history']
                server.outbox.put(frame)
            row = page.locator(f'.msg-row[data-record-id="{case["response"]["id"]}"]')
            row.wait_for()
            page.wait_for_function('document.body.textContent.includes("COMPRESS_COMPLETE_OUTPUT")')
            before = row.locator('.body').inner_html()
            page.reload()
            row.wait_for()
            assert row.locator('.body').inner_html() == before
            assert row.count() == 1
            assert errors == []
        finally:
            browser.close()
