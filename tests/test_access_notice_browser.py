from pathlib import Path

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session


def test_alert_toast_on_other_conversation_does_not_add_context_message(full_output_server):
    server=full_output_server[0]
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        try:
            page=context.new_page();page.goto(base+'/#/chat?conversation=global_memory')
            page.wait_for_function('!document.getElementById("btn-send").disabled')
            before=page.locator('#log>.msg-row').count()
            text='🚨 访问控制通知：来自电报端的未授权请求 🚨'
            server.outbox.put({'type':'access_notice','conversation_id':'other-conversation','notice_id':'fixture-notice','text':text})
            page.locator('#toast').filter(has_text=text).wait_for()
            assert page.locator('#log>.msg-row').count()==before
        finally:
            browser.close()
