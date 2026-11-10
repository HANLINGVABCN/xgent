"""Wrapped Canvas pages retain their complete scene without viewport filler clipping it."""
from pathlib import Path

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.web_display import build_web_display


SOURCE='''<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#281927;min-height:620px;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:18px;color:white;font-family:system-ui}
.wrapper{position:relative;padding:10px;border-radius:26px;background:#654}
.stage{position:relative;width:520px;max-width:92vw;aspect-ratio:1/1;overflow:hidden;border-radius:20px;cursor:grab}
canvas{width:100%;height:100%;display:block}
.caption{position:absolute;left:16px;right:16px;top:14px;font-size:12px}
.controls{position:absolute;left:16px;right:16px;bottom:14px;padding:10px;font-size:14px;background:#123}
button{color:white;background:#835;border:0;padding:5px}
</style></head><body><div class="wrapper"><div class="stage">
<canvas id="canvas" width="800" height="800"></canvas><div class="caption">上方说明</div>
<div class="controls"><span id="status">底部内容必须完整显示</span><button id="interact">触摸互动</button></div>
</div></div><script>
window.executions=(window.executions||0)+1;window.paintFrames=0;
const canvas=document.getElementById('canvas'),context=canvas.getContext('2d');
context.fillStyle='#ad8';context.fillRect(0,0,800,800);context.fillStyle='#e38';context.fillRect(0,760,800,40);
document.getElementById('interact').onclick=()=>document.getElementById('status').textContent='已互动';
function paint(){window.paintFrames++;requestAnimationFrame(paint);}requestAnimationFrame(paint);
</script></body></html>'''


@pytest.mark.parametrize('width',[320,390,1440])
@pytest.mark.parametrize('body_height',['min-height:620px','height:620px','min-height:100vh'])
def test_wrapped_canvas_and_bottom_controls_fit_after_drag_expand_and_reload(full_output_server,tmp_path,width,body_height):
    server=full_output_server[0]
    source=SOURCE.replace('min-height:620px',body_height)
    raw='```xgent-html 完整画布\n'+source+'\n```'
    record={'id':830,'role':'assistant','msg_type':'ai_reply','content':raw,'timestamp':1,
            'conversation_id':'global_memory','web_display':build_web_display(raw)}
    async def history(limit):return [record]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(base+'/#/chat?conversation=global_memory')
        card=page.locator('.visual-page');frame=card.locator('.visual-page-frame').content_frame
        frame.locator('#canvas').wait_for();page.locator('.visual-page-ready').wait_for()
        def settle():page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))')
        def fits():
            settle()
            value=frame.locator('body').evaluate('node=>{const a=document.querySelector(".wrapper").getBoundingClientRect(),b=document.querySelector(".stage").getBoundingClientRect(),c=document.querySelector(".controls").getBoundingClientRect();return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,wrapper:{left:a.left,right:a.right,top:a.top,bottom:a.bottom},canvas:{width:b.width,height:b.height},controlsBottom:c.bottom};}')
            assert value['wrapper']['top']>=-1 and value['wrapper']['bottom']<=value['height']+1,value
            assert value['wrapper']['left']>=-1 and value['wrapper']['right']<=value['width']+1,value
            assert value['scrollHeight']<=value['height']+1 and value['scrollWidth']<=value['width']+1,value
            assert value['controlsBottom']<=value['height']+1,value
            assert abs(value['canvas']['width']/value['canvas']['height']-1)<.01,value
        fits();frame.locator('#canvas').evaluate('node=>window.keptCanvas=node')
        frame.locator('#interact').click();assert frame.locator('#status').inner_text()=='已互动'
        count=frame.locator('body').evaluate('()=>window.paintFrames')
        card.get_by_role('button',name='展开页面',exact=True).click();fits()
        assert frame.locator('#canvas').evaluate('node=>node===window.keptCanvas')
        card.get_by_role('button',name='关闭页面',exact=True).click();fits()
        before=card.locator('.visual-page-viewport').bounding_box()
        card.get_by_role('button',name='拖拽等比例调整页面大小',exact=True).focus();page.keyboard.press('ArrowLeft');fits()
        after=card.locator('.visual-page-viewport').bounding_box()
        assert after['width']<before['width'] and abs(before['width']/before['height']-after['width']/after['height'])<.02
        card.get_by_role('button',name='恢复自动大小',exact=True).click();fits()
        card.get_by_role('button',name='源码',exact=True).click()
        assert page.locator('.visual-page-source').text_content().strip()==source
        card.get_by_role('button',name='预览',exact=True).click();fits()
        assert frame.locator('#canvas').evaluate('node=>node===window.keptCanvas')
        assert frame.locator('body').evaluate('()=>window.executions===1&&window.paintFrames>'+str(count))
        assert frame.locator('#status').inner_text()=='已互动'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(tmp_path/f'canvas-wrapper-{width}-{body_height.split(":")[0]}.png'))
        page.reload();page.locator('.visual-page-ready').wait_for();fits()
        assert not errors
        browser.close()


@pytest.mark.parametrize('width',[390,1440])
def test_relative_width_svg_card_stops_resizing_between_stream_updates_and_after_completion(full_output_server,width):
    source='''<!doctype html><html><head><style>
*{box-sizing:border-box;margin:0;padding:0}body{min-height:580px;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:18px}
.card{width:500px;max-width:94vw;padding:14px;transition:transform .3s}.card:hover{transform:translateY(-3px)}
.scene{width:100%;aspect-ratio:1/1;overflow:hidden}svg{display:block;width:100%;height:100%}
.picture{transform-origin:250px 250px;animation:breathe 1s infinite}@keyframes breathe{50%{transform:scale(1.015,.988)}}
.caption{display:flex;margin-top:12px;padding:8px 16px;justify-content:space-between}button{padding:4px 11px}
</style></head><body><div class="card" id="card"><div class="scene"><svg viewBox="0 0 500 500"><defs><linearGradient id="color"><stop stop-color="purple"/></linearGradient></defs>
<g class="picture"><circle id="live" cx="250" cy="250" r="150" fill="url(#color)"/></g></svg></div>
<div class="caption"><span id="state">底部的真实内容</span><button id="action">交互按钮</button></div></div>
<script>window.executions=(window.executions||0)+1;document.getElementById('action').onclick=()=>document.getElementById('state').textContent='交互正常';</script></body></html>'''
    server=full_output_server[0]
    async def history(limit):return []
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p);page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        page.goto(base+'/#/chat?conversation=global_memory');page.wait_for_function('!document.getElementById("btn-send").disabled')
        card=page.locator('.visual-page');frame=card.locator('.visual-page-frame').content_frame
        def emit(text):
            raw='```xgent-html 稳定实时图形\n'+text
            server.outbox.put({'type':'edit','message_id':999,'text':raw,'msg_type':'ai_reply',
                'web_display':build_web_display(raw,hide_unclosed=True,reply_message_id=999)})
        def stable():
            sizes=page.evaluate('''()=>new Promise(resolve=>{const values=[],start=performance.now();function read(){const r=document.querySelector('.visual-page-viewport').getBoundingClientRect();values.push([r.width,r.height]);if(performance.now()-start<900)requestAnimationFrame(read);else resolve(values);}requestAnimationFrame(read);})''')
            assert max(v[0] for v in sizes)-min(v[0] for v in sizes)<1,sizes
            assert max(v[1] for v in sizes)-min(v[1] for v in sizes)<1,sizes
            assert sizes[-1][0]>100 and sizes[-1][1]>100,sizes[-1]
        stages=[source[:source.index('<g class')],source[:source.index('<div class="caption"')],source]
        for prefix in stages:
            emit(prefix);frame.locator('#card').wait_for();page.wait_for_timeout(200);stable()
            code=card.get_by_role('button',name='源码',exact=True)
            header=card.locator('header').bounding_box();codebox=code.bounding_box()
            assert codebox and codebox['y']>=header['y'] and codebox['y']+codebox['height']<=header['y']+header['height']+1
            code.click(timeout=2000);page.locator('.visual-page-source').wait_for()
            assert page.locator('.visual-page-source').text_content()==prefix
            card.get_by_role('button',name='预览',exact=True).click();page.wait_for_timeout(200);stable()
        frame.locator('#live').evaluate('node=>window.liveNode=node')
        emit(source+'\n```');page.wait_for_function('document.querySelector(".visual-page").getAttribute("aria-busy")==="false"')
        page.wait_for_timeout(200);stable()
        frame.locator('#action').click();assert frame.locator('#state').inner_text()=='交互正常'
        frame.locator('#card').evaluate('node=>window.finishedCard=node')
        stable()
        card.get_by_role('button',name='源码',exact=True).click();card.get_by_role('button',name='预览',exact=True).click()
        assert frame.locator('#card').evaluate('node=>node===window.finishedCard')
        assert frame.locator('body').evaluate('()=>window.executions===1')
        assert frame.locator('#card').evaluate('node=>node.getBoundingClientRect().bottom<=innerHeight+1')
        browser.close()
