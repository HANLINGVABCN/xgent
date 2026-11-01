from pathlib import Path

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session


@pytest.mark.parametrize('dark', [False, True])
@pytest.mark.parametrize('mobile', [False, True])
def test_thinking_text_is_readable_in_each_theme(full_output_server, dark, mobile):
    server, _, _, _ = full_output_server
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        try:
            page = context.new_page()
            if mobile:
                page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(base)
            page.wait_for_function('!document.getElementById("btn-send").disabled')
            page.evaluate('(dark)=>document.body.classList.toggle("dark",dark)', dark)
            server.outbox.put({'type': 'record_snapshot', 'record_id': 999, 'id': 999, 'msg_type': 'ai_reply',
                'role': 'assistant', 'text': '最终回答', 'timestamp': 1,
                'thinking': {'version': 1, 'capture_id': 'theme-fixture', 'revision': 1,
                             'text': '思考原文\n保留所有文字和空格  ', 'status': 'completed', 'elapsed_seconds': None}})
            head = page.locator('.thinking-head')
            head.wait_for()
            assert head.inner_text().strip() == '思考 · 0 秒'
            head.click()
            body = page.locator('.thinking-body')
            body.wait_for(state='visible')
            assert body.text_content() == '思考原文\n保留所有文字和空格  '
            values = page.evaluate('''() => {
                function color(node){const s=getComputedStyle(node);return [s.color,s.backgroundColor];}
                const body=document.querySelector('.thinking-body');
                return {head:color(document.querySelector('.thinking-head'))[0],body:color(body)[0],
                        background:getComputedStyle(document.body).backgroundColor};
            }''')
            def luminance(css):
                rgb = [float(value) / 255 for value in css.removeprefix('rgb(').removesuffix(')').split(',')]
                linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in rgb]
                return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
            background = luminance(values['background'])
            for name in ('head', 'body'):
                foreground = luminance(values[name])
                contrast = (max(foreground, background) + .05) / (min(foreground, background) + .05)
                assert contrast >= 4.5, (dark, name, contrast, values)
        finally:
            browser.close()


@pytest.mark.parametrize('dark', [False, True])
def test_missing_file_has_compact_red_text_without_code_block(full_output_server, dark):
    server, _, _, _ = full_output_server
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        try:
            page = context.new_page()
            page.goto(base)
            page.wait_for_function('!document.getElementById("btn-send").disabled')
            page.evaluate('(dark)=>document.body.classList.toggle("dark",dark)', dark)
            server.outbox.put({'type': 'record_snapshot', 'record_id': 998, 'id': 998,
                'msg_type': 'agent_result', 'role': 'assistant', 'text': '', 'file_message': True,
                'media': [{'kind': 'file', 'filename': 'update_public.py', 'error': '原件不存在或无法读取'}]})
            error = page.locator('[data-record-id="998"] .media-error')
            error.wait_for()
            assert error.inner_text() == 'update_public.py\n原件不存在或无法读取'
            assert error.evaluate('node=>getComputedStyle(node).fontSize') == '12px'
            color = error.evaluate('node=>getComputedStyle(node).color')
            channels = [int(n) for n in color.removeprefix('rgb(').removesuffix(')').split(',')]
            assert channels[0] > channels[1] and channels[0] > channels[2], color
            assert page.locator('[data-record-id="998"] pre').count() == 0
        finally:
            browser.close()
