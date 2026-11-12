"""A neutral portrait canvas with separate controls fits as one composition."""
from pathlib import Path

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.web_display import build_web_display


SOURCE = '''<!doctype html><html><head><style>
*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:14px 10px 20px;background:#f8efe6}
.art{position:relative;width:100%;max-width:460px;aspect-ratio:4/5;border-radius:24px;overflow:hidden;background:#fffbf3}
svg{display:block;width:100%;height:100%}
canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.label{position:absolute;top:14px;left:6%;width:88%;padding:10px;background:#fff;border-radius:16px;text-align:center}
.controls{width:100%;max-width:460px;margin-top:12px;display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
button{padding:9px 4px;border:1px solid #cfc2b1;border-radius:14px;background:white}
</style></head><body><div class="art" id="art"><div class="label" id="label">四比五画布</div>
<canvas id="effects"></canvas><svg viewBox="0 0 800 1000"><rect width="800" height="1000" fill="#e9d8bd"/>
<circle cx="400" cy="400" r="130" fill="#80aac2"/><rect id="bottom" x="50" y="930" width="700" height="45" rx="20" fill="#417981"/></svg></div>
<div class="controls" id="controls"><button id="one">第一项</button><button>第二项</button><button>第三项</button><button>第四项</button></div>
<script>window.runs=(window.runs||0)+1;document.getElementById('one').onclick=()=>document.getElementById('label').textContent='已操作';</script></body></html>'''


@pytest.mark.parametrize('width', [320, 390, 1440])
def test_separate_art_and_controls_fit_stream_drag_expand_and_reload(full_output_server, width, tmp_path):
    server = full_output_server[0]
    raw = '```xgent-html 独立画布与底部控件\n' + SOURCE + '\n```'
    record = {'id': 861, 'role': 'assistant', 'msg_type': 'ai_reply', 'content': raw,
              'timestamp': 1, 'conversation_id': 'global_memory', 'web_display': build_web_display(raw)}
    async def history(limit):
        return [record]
    server.config.read_history = history
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        page = context.new_page()
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(base + '/#/chat?conversation=global_memory')
        card = page.locator('.visual-page')
        frame = card.locator('.visual-page-frame').content_frame
        frame.locator('#controls').wait_for()
        page.locator('.visual-page-ready').wait_for()

        def fits():
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve))))')
            bounds = frame.locator('body').evaluate('''() => {
                const art = document.querySelector('#art').getBoundingClientRect(), controls = document.querySelector('#controls').getBoundingClientRect();
                return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,
                    scrollHeight:document.documentElement.scrollHeight,top:art.top,bottom:controls.bottom,
                    left:Math.min(art.left,controls.left),right:Math.max(art.right,controls.right),
                    ratio:art.width/art.height,compact:document.documentElement.hasAttribute('data-xgent-card')};
            }''')
            assert bounds['compact'], bounds
            assert bounds['top'] >= -1 and bounds['bottom'] <= bounds['height'] + 1, bounds
            assert bounds['left'] >= -1 and bounds['right'] <= bounds['width'] + 1, bounds
            assert bounds['scrollHeight'] <= bounds['height'] + 1 and bounds['scrollWidth'] <= bounds['width'] + 1, bounds
            assert abs(bounds['ratio'] - .8) < .005, bounds

        fits()
        frame.locator('#one').click()
        frame.locator('#art').evaluate('node => window.artNode=node')
        card.get_by_role('button', name='展开页面', exact=True).click()
        fits()
        card.get_by_role('button', name='关闭页面', exact=True).click()
        fits()
        before = card.locator('.visual-page-viewport').bounding_box()
        card.get_by_role('button', name='拖拽等比例调整页面大小', exact=True).focus()
        page.keyboard.press('ArrowLeft')
        fits()
        after = card.locator('.visual-page-viewport').bounding_box()
        assert after['width'] < before['width']
        assert abs(before['width']/before['height']-after['width']/after['height']) < .02
        card.get_by_role('button', name='恢复自动大小', exact=True).click()
        fits()
        card.get_by_role('button', name='源码', exact=True).click()
        card.get_by_role('button', name='预览', exact=True).click()
        fits()
        assert frame.locator('#label').inner_text() == '已操作'
        assert frame.locator('#art').evaluate('node => node===window.artNode&&window.runs===1')
        page.screenshot(path=str(tmp_path / f'multiroot-complete-{width}.png'))
        page.reload()
        frame.locator('#controls').wait_for()
        page.locator('.visual-page-ready').wait_for()
        fits()
        browser.close()


@pytest.mark.parametrize('width', [390, 1440])
def test_controls_arriving_after_streamed_canvas_are_fitted_before_the_page_completes(full_output_server, width):
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
        page.wait_for_function('!document.querySelector("#btn-send").disabled')
        def emit(source, complete=False):
            raw = '```xgent-html 逐步生成的画布与控件\n' + source + ('\n```' if complete else '')
            server.outbox.put({'type': 'edit', 'msg_type': 'ai_reply', 'message_id': 862,
                'text': raw, 'web_display': build_web_display(raw, hide_unclosed=not complete, reply_message_id=862)})
        emit(SOURCE.split('</svg>')[0])
        card = page.locator('.visual-page')
        frame = card.locator('.visual-page-frame').content_frame
        frame.locator('#bottom').wait_for()
        frame.locator('#art').evaluate('node=>window.keptArt=node')
        emit(SOURCE.split('<script>')[0])
        frame.locator('#controls').wait_for()
        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))')
        value = frame.locator('#controls').evaluate('node=>({bottom:node.getBoundingClientRect().bottom,height:innerHeight,compact:document.documentElement.hasAttribute("data-xgent-card")})')
        assert value['compact'] and value['bottom'] <= value['height']+1, value
        assert frame.locator('#art').evaluate('node=>node===window.keptArt&&window.runs===undefined')
        emit(SOURCE, complete=True)
        page.wait_for_function('document.querySelector(".visual-page")?.getAttribute("aria-busy")==="false"')
        frame.locator('#one').click()
        assert frame.locator('#label').inner_text() == '已操作'
        assert frame.locator('#art').evaluate('()=>window.runs===1')
        browser.close()
