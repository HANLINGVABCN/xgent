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
    visual={'version':2,'index':0,'title':'完整页面演示','width':800,'height':450,'format':'html','source_path':'test.html','sha256':'a'*64}
    record={'id':55,'msg_type':'ai_reply','role':'assistant','content':'正常回复前文。\n```xgent-html 完整页面演示\n'+SOURCE+'\n```\n正常回复后文。','timestamp':1,'session_id':'global_memory',
            'metadata':stamp_record_metadata('ai_reply','assistant',{'rendered_pages':[visual]})}
    message=build_history_message(record,str(tmp_path),str(tmp_path));assert message['visual_pages'][0]['version']==2
    async def history(limit):return [message]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        context.route('**/api/workbench/visual?*',lambda route:route.fulfill(json={'version':2,'source':SOURCE,'format':'html','title':'完整页面演示','width':800,'height':450}))
        page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        page.goto(base+'/#/chat?conversation=global_memory'+('&visual=55&visual_full=1' if deep_link else '&visual=55'))
        iframe=page.locator('.visual-page-frame');iframe.wait_for()
        if not deep_link:
            assert page.locator('.visual-page-expanded').count()==0
            assert page.locator('[data-record-id="55"] .bubble-author-icon').is_visible()
            assert page.locator('.wb-brand').is_visible() or width==390
        frame=page.frame_locator('.visual-page-frame');frame.get_by_role('button',name='点击切换').wait_for()
        assert page.locator('#log img').count()==0
        assert page.locator('[data-record-id="55"] [data-brand-logo]').count()==1
        assert '正常回复前文' in page.locator('#log').inner_text() and '正常回复后文' in page.locator('#log').inner_text()
        assert iframe.get_attribute('sandbox')=='allow-scripts'
        frame.get_by_role('button',name='点击切换').click(timeout=5000)
        assert frame.locator('#result').inner_text()=='已点击'
        assert iframe.content_frame.locator('body').evaluate('()=>window.hostBlocked')
        assert iframe.content_frame.locator('body').evaluate('()=>window.networkBlocked')
        assert page.locator('body').get_attribute('data-leaked') is None
        assert iframe.content_frame.locator('html').evaluate('node=>getComputedStyle(node).zoom')=='0.8'
        page.get_by_role('button',name='源码',exact=True).click()
        assert page.locator('.visual-page-source').is_visible()
        assert page.locator('.visual-page-source code').text_content()==SOURCE+'\n'
        assert not iframe.is_visible()
        assert page.get_by_role('link',name='下载',exact=True).is_visible()
        page.get_by_role('button',name='预览',exact=True).click()
        assert frame.locator('#result').inner_text()=='已点击'
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


def test_actual_live_reply_preview_placeholder_and_refresh_match(full_output_server,tmp_path):
    from tests.test_thinking_params import run_in_app
    from xgent_app.web_display import build_web_display
    case=run_in_app('import asyncio\nfrom tests.visual_pages_probe import exercise\n'+
        f'print(json.dumps(asyncio.run(exercise(bot,{str(tmp_path)!r},"openai","foreground",long_source=True,capture=True))))')
    server=full_output_server[0];records=[]
    async def history(limit):return records
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p)
        context.route('**/api/workbench/visual?*',lambda route:route.fulfill(json={'version':2,'source':case['source'],'format':'html'}))
        page=context.new_page();page.set_viewport_size({'width':390,'height':950});page.goto(base+'/#/chat?conversation=global_memory')
        page.wait_for_function('!document.getElementById("btn-send").disabled')
        boundary=next(i for i,frame in enumerate(case['frames']) if any('visual_index' in segment for segment in (frame.get('web_display') or {}).get('segments',[])))
        for frame in case['frames'][:boundary]:server.outbox.put(frame)
        incoming=case['frames'][boundary]
        pending='这里是页面。\n```xgent-html 演示标题\n<html><button'
        server.outbox.put({**incoming,'text':pending,'web_display':build_web_display(pending,hide_unclosed=True)})
        placeholder=page.locator('.visual-page-loading');placeholder.wait_for()
        assert placeholder.locator('strong').inner_text()=='演示标题'
        assert '生成中' in placeholder.inner_text() and placeholder.locator('.visual-page-skeleton').is_visible()
        assert page.locator('.visual-page-frame').count()==1
        page.evaluate('document.querySelector(".visual-page").dataset.sameCard="yes"')
        for frame in case['frames'][boundary:]:server.outbox.put(frame)
        selector='[data-record-id="'+str(case['history']['id'])+'"]'
        card=page.locator(selector+' .visual-page');card.wait_for()
        page.locator(selector+' .visual-page-ready').wait_for()
        assert card.get_attribute('data-same-card')=='yes'
        assert page.locator('#log .file-card').count()==0
        assert page.locator('#log').get_by_text('打开渲染页面',exact=True).count()==0
        assert page.locator(selector+' [data-brand-logo]').count()==1
        before=page.locator(selector+' .body').inner_text()
        records.append(case['history']);page.reload();page.locator(selector+' .visual-page-ready').wait_for()
        assert page.locator(selector+' .body').inner_text()==before
        assert page.locator(selector+' [data-brand-logo]').count()==1
        browser.close()


@pytest.mark.parametrize('width',[390,1440])
def test_svg_and_html_render_during_writing_and_finish_independently(full_output_server,width):
    from xgent_app.web_display import build_web_display
    server=full_output_server[0]
    async def history(limit):return []
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p)
        page=context.new_page();page.set_viewport_size({'width':width,'height':950});page.goto(base+'/#/chat?conversation=global_memory')
        page.wait_for_function('!document.getElementById("btn-send").disabled')
        def emit(raw):server.outbox.put({'type':'edit','message_id':999,'text':raw,'msg_type':'ai_reply',
            'web_display':build_web_display(raw,hide_unclosed=True,reply_message_id=999)})
        first='```xgent-svg 实时图形\n<svg viewBox="0 0 200 120"><rect id="bg" width="200" height="120" fill="#7165cf"/>'
        emit(first)
        card=page.locator('[data-visual-index="0"] .visual-page');frame=card.locator('.visual-page-frame').content_frame
        frame.locator('#bg').wait_for();assert frame.locator('#bg').get_attribute('fill')=='#7165cf'
        assert frame.locator('html').evaluate('node=>getComputedStyle(node).zoom')=='0.8'
        frame.locator('#bg').evaluate('node=>window.keptNode=node')
        second=first+'<circle id="dot" cx="60" cy="60" r="20" fill="#ffffff"/>'
        emit(second);frame.locator('#dot').wait_for()
        assert frame.locator('#bg').evaluate('node=>node===window.keptNode')
        assert '生成中' in card.inner_text()
        closed=second+'<script>window.closedRuns=(window.closedRuns||0)+1;</script></svg>\n```\n'
        html='```xgent-html 实时网页\n<style>h1{color:rgb(110,80,210)}</style><h1 id="heading">第一行</h1>'
        emit(closed+html)
        page.wait_for_function("document.querySelector('[data-visual-index=\"0\"] .visual-page')?.getAttribute('aria-busy')==='false'")
        assert '生成中' not in card.inner_text()
        other=page.locator('[data-visual-index="1"] .visual-page');htmlframe=other.locator('.visual-page-frame').content_frame
        htmlframe.locator('#heading').wait_for()
        assert htmlframe.locator('#heading').evaluate('node=>getComputedStyle(node).color')=='rgb(110, 80, 210)'
        htmlframe.locator('body').evaluate('()=>window.unchanged=123')
        html+='\n<p id="tail">第二行</p><script>window.scriptRuns=(window.scriptRuns||0)+1;</script><button id="click" onclick="this.textContent=\'已点击\'">试一下</button>'
        emit(closed+html);htmlframe.locator('#tail').wait_for()
        assert htmlframe.locator('body').evaluate('()=>window.scriptRuns===undefined&&window.unchanged===123')
        assert frame.locator('body').evaluate('()=>window.closedRuns===1')
        emit(closed+html+'\n```\n后续解释还在生成')
        page.wait_for_function("document.querySelector('[data-visual-index=\"1\"] .visual-page')?.getAttribute('aria-busy')==='false'")
        htmlframe.locator('#click').click();assert htmlframe.locator('#click').inner_text()=='已点击'
        assert htmlframe.locator('body').evaluate('()=>window.scriptRuns===1')
        emit(closed+html+'\n```\n后续解释还在生成更多文字')
        page.wait_for_function("document.querySelector('#log').innerText.includes('更多文字')")
        assert htmlframe.locator('#click').inner_text()=='已点击'
        assert frame.locator('body').evaluate('()=>window.closedRuns===1')
        browser.close()
