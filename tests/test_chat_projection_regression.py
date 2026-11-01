import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_thinking_params import run_in_app
from tests.test_web_presentation import browser_session
from xgent_app.presentation_delivery import PresentationBot, PresentationMessage
from xgent_app.web_bridge import WebBot, WebOutbox
from xgent_app.web_history import build_history_message


@pytest.fixture(scope='module', params=['nonstream', 'foreground', 'background'])
def workflow_case(tmp_path_factory, request):
    root = tmp_path_factory.mktemp('chat-projection-' + request.param)
    return run_in_app('import asyncio\nfrom tests.chat_projection_probe import workflow\n' +
                      f'print(json.dumps(asyncio.run(workflow(bot, {str(root)!r}, {request.param!r}))))')


def test_tool_only_media_file_form_workflow_preserves_display_and_waiting_state(workflow_case):
    assert len([m for m in workflow_case['history'] if m.get('file_message')]) == 2


@pytest.mark.parametrize('mode', ['toolcall', 'fence'])
@pytest.mark.parametrize('style', ['nonstream', 'foreground', 'background'])
def test_text_and_binary_writes_do_not_send_files_in_either_mode(tmp_path, mode, style):
    result = run_in_app('import asyncio\nfrom tests.chat_projection_probe import write_without_upload\n' +
                        f'print(json.dumps(asyncio.run(write_without_upload(bot, {str(tmp_path)!r}, {mode!r}, {style!r}))))')
    assert result['written_exactly'] and result['no_upload']


def test_replaying_previous_reply_does_not_stop_current_generation():
    turn = SimpleNamespace()
    bot = PresentationBot(SimpleNamespace(), turn)
    old = PresentationMessage(bot, SimpleNamespace(message_id=1))
    old.telegram_owner_id = 1
    bot.messages[1] = old
    bot._telegram_generation = {'owner_id': 2, 'run_id': 'current-run', 'ref': 'current-phase'}
    with patch('xgent_app.stop_targets.end_phase') as stop:
        bot.complete_telegram_reply({'message_ids': [1]})
        stop.assert_not_called()
        current = PresentationMessage(bot, SimpleNamespace(message_id=2))
        bot.messages[2] = current
        bot.complete_telegram_reply({'message_ids': [2]})
        stop.assert_called_once_with('current-run', 'current-phase')


def test_web_message_retains_form_keyboard_after_text_and_markup_edits():
    async def exercise():
        bot = WebBot(WebOutbox(), 1)
        markup = SimpleNamespace(inline_keyboard=[])
        message = await bot.send_message(1, 'form', reply_markup=markup)
        assert message.reply_markup is markup
        await message.edit_text('updated', reply_markup=markup)
        assert message.reply_markup is markup and message.text == 'updated'
        await message.edit_reply_markup(None)
        assert message.reply_markup is None
    asyncio.run(exercise())


@pytest.mark.parametrize('protocol', ['file', 'file:base64', 'sendfile'])
def test_previous_file_results_restore_the_original_caption_and_file_representation(tmp_path, protocol):
    from copy import deepcopy
    from xgent_app.message_policy import stamp_record_metadata
    path = tmp_path / 'image.png'
    path.write_bytes(b'fixture bytes')
    notice = f'[{protocol}结果] 已' + ('发送服务器文件给用户' if protocol == 'sendfile' else '写入服务器文件')
    notice += f': {path} ({path.stat().st_size} bytes)'
    raw = {'id': 81, 'role': 'system', 'msg_type': 'agent_result', 'content': notice,
           'metadata': stamp_record_metadata('agent_result', 'system')}
    before = deepcopy(raw)
    result = build_history_message(raw, tmp_path, tmp_path)
    assert result['file_message']
    assert result['media'][0]['kind'] == 'file'
    assert '已写入服务器并发送' in result['content'] if protocol.startswith('file') else result['content'].startswith('📄 image.png (')
    assert str(path) not in result['content']
    assert raw == before


def test_slow_native_finalization_and_repeated_footer_edit_keep_original_message_order():
    from tests.telegram_rich_probe import RichCapture
    from xgent_app.fanout import ChannelWorker
    from xgent_app.telegram_presentation import chat_display
    from xgent_app.web_bridge import MirrorBot, deliver_op_to_bot

    async def exercise():
        native = RichCapture()
        entered, release = asyncio.Event(), asyncio.Event()
        async def deliver(op, mid):
            if not entered.is_set():
                entered.set()
                await release.wait()
            return await deliver_op_to_bot(native, op, mid)
        worker = ChannelWorker('projection-order', deliver)
        bot = MirrorBot(WebOutbox(), 31, native, worker)
        def spec(text, owner):
            return {'phase': 'reply', 'owner_id': owner, 'html': [text], 'fallback': [text]}
        try:
            with chat_display({'telegram_native': spec('first reply', 101)}):
                await bot.send_message(31, 'first reply', relay_message_id=101)
            await asyncio.wait_for(entered.wait(), 2)
            with chat_display({'telegram_native': spec('first reply details', 101)}):
                await bot.edit_message_text('first reply details', chat_id=31, message_id=101)
            with chat_display({'telegram_native': spec('second reply', 102)}):
                await bot.send_message(31, 'second reply', relay_message_id=102)
            with chat_display({'telegram_native': spec('first reply details', 101)}):
                await bot.edit_message_text('first reply details', chat_id=31, message_id=101)
            release.set()
            assert await worker.wait_idle(5)
            assert [m['text'] for m in native.messages.values()] == ['first reply details', 'second reply']
            assert [method for method, _ in native.api_calls].count('sendRichMessage') == 2
        finally:
            await worker.aclose()
    asyncio.run(exercise())


@pytest.mark.parametrize('mobile', [False, True])
def test_media_form_and_authors_are_identical_after_refresh(full_output_server, workflow_case, mobile):
    server, _, _, _ = full_output_server
    playwright = pytest.importorskip('playwright.sync_api')
    async def empty(limit):
        return []
    server.config.read_history = empty
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        try:
            image = next(item['path'] for message in workflow_case['history']
                         for item in message.get('media', []) if item['kind'] == 'photo')
            for pattern in ('**/api/media/**', '**/api/history/media/**'):
                context.route(pattern, lambda route: route.fulfill(path=image, content_type='image/png'))
            page = context.new_page()
            if mobile:
                page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(base)
            page.wait_for_selector('#input:not([disabled])')
            for frame in workflow_case['frames']:
                server.outbox.put(frame)
            page.wait_for_selector('.web-ask-form')
            live = page.locator('#log').inner_text()
            assert 'local media fixture' in live
            assert '✅ 已写入' in live
            assert page.locator('.file-write-result').count() == 1
            assert page.locator('.fc-name', has_text='fixture.png').count() == 1
            assert page.locator('.msg-row.ai .bubble-header:visible').count() <= 1
            assert page.locator('.fc-name').first.evaluate('node=>getComputedStyle(node).fontSize') == '11px'
            # Project the durable state on the same page, then compare a full refresh.
            async def history(limit):
                return workflow_case['history']
            server.config.read_history = history
            page.evaluate('window.XGentChat.reload()')
            page.wait_for_selector('.file-card')
            page.wait_for_function('Array.from(document.querySelectorAll("#log img")).every(image=>image.complete)')
            before = page.locator('#log').inner_text()
            assert '✅ 已写入' in before
            assert page.locator('.file-write-result').count() == 1
            assert page.locator('.fc-name', has_text='fixture.png').count() == 1
            assert page.locator('.msg-row.ai .bubble-header:visible').count() <= 1
            page.reload()
            page.wait_for_selector('.web-ask-form')
            page.wait_for_function('Array.from(document.querySelectorAll("#log img")).every(image=>image.complete)')
            assert page.locator('#log').inner_text() == before
            assert page.locator('.msg-row.ai .bubble-header:visible').count() <= 1
        finally:
            browser.close()


def test_form_continuation_keeps_author_group_across_runs_and_new_user_starts_a_new_group(full_output_server):
    server, _, _, _ = full_output_server
    playwright = pytest.importorskip('playwright.sync_api')
    async def history(limit):
        return [
            {'id': 801, 'msg_type': 'ai_reply', 'role': 'assistant', 'content': '表单之前',
             'run_id': 'first-run', 'reply_group_id': 'form-group', 'timestamp': 1},
            {'id': 802, 'msg_type': 'ai_reply', 'role': 'assistant', 'content': '表单之后',
             'run_id': 'resumed-run', 'reply_group_id': 'form-group', 'timestamp': 2},
            {'id': 803, 'msg_type': 'user_text', 'role': 'user', 'content': '另一个问题', 'timestamp': 3},
            {'id': 804, 'msg_type': 'ai_reply', 'role': 'assistant', 'content': '新回复',
             'run_id': 'next-run', 'reply_group_id': 'next-group', 'timestamp': 4},
        ]
    server.config.read_history = history
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        try:
            page = context.new_page()
            page.goto(base)
            page.locator('[data-record-id="804"]').wait_for()
            assert page.locator('.msg-row.ai .bubble-header:visible').count() == 2
            assert 'turn-continuation' in page.locator('[data-record-id="802"]').get_attribute('class')
            assert 'turn-continuation' not in page.locator('[data-record-id="804"]').get_attribute('class')
            page.reload()
            page.locator('[data-record-id="804"]').wait_for()
            assert page.locator('.msg-row.ai .bubble-header:visible').count() == 2
        finally:
            browser.close()
