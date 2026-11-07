"""Direct SVG/HTML rendering: interaction, isolation, reuse and Web App deep links."""
from pathlib import Path
from urllib.parse import quote

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.message_policy import stamp_record_metadata
from xgent_app.web_history import build_history_message

SOURCE='''<html><head><style>body{margin:0;padding:24px;background:linear-gradient(130deg,#eeebff,#def6fa);font-family:system-ui}article{background:#fff;border-radius:20px;padding:24px;box-shadow:0 8px 25px #66557722}h1{color:#6355bb;margin:0 0 16px}button{background:#6355bb;color:white;border:0;border-radius:10px;padding:12px}svg{width:100px}#result{margin-left:12px}</style></head><body><article><h1>渲染页面</h1><svg viewBox="0 0 120 120"><rect width="120" height="120" rx="28" fill="#E5A85A"/><path d="M22 34L46 51L22 68 M94 40L80 51L94 62 M44 86H76" fill="none" stroke="#18181B" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/></svg><p>这是直接渲染的 HTML，不是图片。</p><button id="action">点击切换</button><span id="result">未点击</span><input id="slider" type="range" min="0" max="100" value="30"></article><script>document.querySelector('#action').onclick=()=>document.querySelector('#result').textContent='已点击';try{parent.document.body.dataset.leaked='yes';}catch(e){window.hostBlocked=true;}fetch('/api/config').catch(()=>window.networkBlocked=true);</script></body></html>'''


@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('deep_link',[False,True])
def test_direct_html_interaction_isolated_frame_expand_and_reload(full_output_server,width,deep_link,tmp_path):
    server=full_output_server[0]
    visual={'version':2,'title':'完整页面演示','width':800,'height':450,'format':'html','source_path':'test.html','sha256':'a'*64}
    record={'id':55,'msg_type':'agent_result','role':'system','content':'[render结果] 已创建','timestamp':1,'session_id':'global_memory',
            'metadata':stamp_record_metadata('agent_result','system',{'visual_render':visual})}
    message=build_history_message(record,str(tmp_path),str(tmp_path));assert message['visual_page']['version']==2
    async def history(limit):return [message]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        context.route('**/api/workbench/visual?*',lambda route:route.fulfill(json={'version':2,'source':SOURCE,'format':'html','title':'完整页面演示','width':800,'height':450}))
        page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        page.goto(base+'/#/chat?conversation=global_memory'+('&visual=55' if deep_link else ''))
        iframe=page.locator('.visual-page-frame');iframe.wait_for()
        frame=page.frame_locator('.visual-page-frame');frame.get_by_role('button',name='点击切换').wait_for()
        assert page.locator('#log img').count()==0
        assert iframe.get_attribute('sandbox')=='allow-scripts'
        try:frame.get_by_role('button',name='点击切换').click(timeout=5000)
        except Exception:
            print(page.locator('#log').inner_html()[:2500]);print(iframe.bounding_box());raise
        assert frame.locator('#result').inner_text()=='已点击'
        assert iframe.content_frame.locator('body').evaluate('()=>window.hostBlocked')
        assert iframe.content_frame.locator('body').evaluate('()=>window.networkBlocked')
        assert page.locator('body').get_attribute('data-leaked') is None
        if not deep_link:page.get_by_role('button',name='展开页面',exact=True).click()
        assert page.locator('.visual-page-expanded').count()==1
        assert frame.locator('#result').inner_text()=='已点击'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(tmp_path/f'rendered-page-{width}-{deep_link}.png'))
        page.get_by_role('button',name='关闭页面',exact=True).click()
        assert page.locator('.visual-page-expanded').count()==0
        assert frame.locator('#result').inner_text()=='已点击'
        page.reload();frame.get_by_role('button',name='点击切换').wait_for()
        assert page.locator('.visual-page-frame').count()==1
        browser.close()
