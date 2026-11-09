"""A centered HTML graphic must fit as a whole, including its last control."""
from pathlib import Path

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.web_display import build_web_display


SOURCE = '''<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>完整卡片</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{display:flex;justify-content:center;align-items:center;min-height:100vh;padding:16px;font-family:system-ui}
.card{position:relative;width:100%;max-width:400px;padding:24px 20px;border:2px solid #89a;border-radius:24px;background:#192341;overflow:hidden;color:white;text-align:center}
h1{font-size:19px;margin-bottom:6px}p{font-size:13px;margin-bottom:20px}
.stage{position:relative;width:220px;height:220px;margin:0 auto 16px;display:flex;justify-content:center;align-items:center}
.decoration{position:absolute;top:14px;right:18px;width:28px;height:28px}
.picture{width:170px;height:170px;animation:pulse 2s infinite}
@keyframes pulse{50%{opacity:.6}}
button{padding:10px 14px;font-size:14px;border:1px solid #bce;border-radius:14px;background:#213356;color:white;width:100%}
</style></head><body><div class="card" id="card">
<svg class="decoration" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="gold"/></svg>
<h1>完整交互卡片</h1><p id="subtitle">上面的说明也要完整显示</p>
<div class="stage"><svg class="picture" viewBox="0 0 200 200"><rect id="picture" width="200" height="200" rx="30" fill="#89c"/></svg></div>
<button id="last" onclick="this.textContent='交互成功';document.getElementById('subtitle').textContent='状态已保留';window.interactions=(window.interactions||0)+1">下面的按钮必须完整显示</button>
</div><script>window.executions=(window.executions||0)+1;</script></body></html>'''


@pytest.mark.parametrize('width', [320, 390, 1440])
@pytest.mark.parametrize('old_size', [False, True])
@pytest.mark.parametrize('tall', [False, True])
def test_centered_html_card_fits_in_preview_drag_expand_and_reload(full_output_server, tmp_path, width, old_size, tall):
    server = full_output_server[0]
    source = SOURCE.replace('height:220px', 'height:620px') if tall else SOURCE
    raw = '```xgent-html 完整卡片\n' + source + '\n```'
    message = {'id': 610, 'role': 'assistant', 'msg_type': 'ai_reply', 'content': raw,
               'timestamp': 1, 'conversation_id': 'global_memory', 'web_display': build_web_display(raw)}

    async def history(limit):
        return [message]
    server.config.read_history = history
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        if old_size:
            context.add_init_script('if(location.protocol==="http:")localStorage.setItem("xgent-visual-sizes",JSON.stringify({"global_memory:610:0":{width:580,logicalWidth:432,logicalHeight:160}}))')
        page = context.new_page()
        page.set_viewport_size({'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(base + '/#/chat?conversation=global_memory')
        card = page.locator('.visual-page')
        frame = card.locator('.visual-page-frame').content_frame
        frame.locator('#last').wait_for()
        page.wait_for_function('document.querySelector(".visual-page").getAttribute("aria-busy")==="false"')

        def fits():
            assert frame.locator('html').evaluate('root=>root.scrollHeight<=innerHeight+1&&root.scrollWidth<=innerWidth+1')
            assert frame.locator('body').evaluate('()=>[document.querySelector("h1"),document.querySelector("#last")].every(node=>{const r=node.getBoundingClientRect();return r.left>=-1&&r.top>=-1&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1;})')
            assert card.evaluate('node=>{const a=node.querySelector(".visual-page-viewport").getBoundingClientRect(),b=node.querySelector(".visual-page-frame").getBoundingClientRect();return b.left>=a.left-1&&b.top>=a.top-1&&b.right<=a.right+1&&b.bottom<=a.bottom+1;}')

        page.wait_for_function('()=>{const frame=document.querySelector(".visual-page-frame"),view=document.querySelector(".visual-page-viewport");return frame&&view&&Math.abs(frame.getBoundingClientRect().height-view.getBoundingClientRect().height)<1;}')
        fits()
        frame.locator('#last').click()
        assert frame.locator('body').evaluate('()=>window.interactions===1&&window.executions===1')
        frame.locator('#last').evaluate('node=>window.originalControl=node')
        handle = card.get_by_role('button', name='拖拽等比例调整页面大小', exact=True)
        before = card.locator('.visual-page-viewport').bounding_box()
        handle.focus()
        page.keyboard.press('ArrowLeft')
        page.wait_for_function('width=>document.querySelector(".visual-page-viewport").getBoundingClientRect().width<width', arg=before['width'])
        after = card.locator('.visual-page-viewport').bounding_box()
        assert abs(before['width']/before['height'] - after['width']/after['height']) < .02
        fits()
        card.get_by_role('button', name='展开页面', exact=True).click()
        page.wait_for_function('document.querySelector(".visual-page-expanded")!==null')
        fits()
        assert frame.locator('#last').evaluate('node=>node===window.originalControl')
        assert frame.locator('body').evaluate('()=>window.executions===1')
        card.get_by_role('button', name='关闭页面', exact=True).click()
        page.wait_for_function('document.querySelector(".visual-page-expanded")===null')
        fits()
        card.get_by_role('button', name='源码', exact=True).click()
        assert page.locator('.visual-page-source').text_content().strip() == source
        card.get_by_role('button', name='预览', exact=True).click()
        fits()
        assert frame.locator('body').evaluate('()=>window.interactions===1&&window.executions===1')
        page.screenshot(path=str(tmp_path / f'html-fit-{width}-{old_size}.png'))
        page.reload()
        page.locator('.visual-page-ready').wait_for()
        fits()
        assert not errors
        browser.close()


@pytest.mark.parametrize('width', [320, 1440])
def test_html_card_keeps_streaming_nodes_and_fits_new_content_before_fence_closes(full_output_server, width):
    server = full_output_server[0]
    async def history(limit):
        return []
    server.config.read_history = history
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        page = context.new_page()
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(base + '/#/chat?conversation=global_memory')
        page.wait_for_function('!document.getElementById("btn-send").disabled')
        def emit(source):
            raw = '```xgent-html 实时卡片\n' + source
            server.outbox.put({'type': 'edit', 'message_id': 999, 'msg_type': 'ai_reply', 'text': raw,
                'web_display': build_web_display(raw, hide_unclosed=True, reply_message_id=999)})
        prefix = SOURCE.split('<button id="last"', 1)[0]
        emit(prefix)
        card = page.locator('.visual-page')
        frame = card.locator('.visual-page-frame').content_frame
        frame.locator('#picture').wait_for()
        frame.locator('#picture').evaluate('node=>window.streamingPicture=node')
        emit(SOURCE)
        frame.locator('#last').wait_for()
        assert frame.locator('#picture').evaluate('node=>node===window.streamingPicture')
        assert '生成中' in card.inner_text()
        assert frame.locator('html').evaluate('root=>root.scrollHeight<=innerHeight+1&&root.scrollWidth<=innerWidth+1')
        assert frame.locator('#last').evaluate('node=>node.getBoundingClientRect().bottom<=innerHeight+1')
        emit(SOURCE + '\n```')
        page.wait_for_function('document.querySelector(".visual-page").getAttribute("aria-busy")==="false"')
        assert frame.locator('html').evaluate('root=>root.scrollHeight<=innerHeight+1&&root.scrollWidth<=innerWidth+1')
        assert frame.locator('body').evaluate('()=>window.executions===1')
        browser.close()
