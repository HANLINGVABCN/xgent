"""Intrinsic image proportions fit the chat; HTML retains usable page scrolling."""
import pytest
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.web_display import build_web_display


@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('canvas',[(400,400),(960,240),(180,900),(120,120)])
def test_svg_fits_its_canvas_without_internal_scroll_and_keeps_live_nodes(full_output_server,tmp_path,width,canvas):
    server=full_output_server[0]
    async def history(limit):return []
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p);page=context.new_page()
        page.set_viewport_size({'width':width,'height':900});page.goto(base+'/#/chat?conversation=global_memory')
        page.wait_for_function('!document.getElementById("btn-send").disabled')
        w,h=canvas;source=f'<svg width="100%" height="100%" viewBox="0 0 {w} {h}"><rect id="canvas" width="{w}" height="{h}" fill="purple"/>'
        def emit(value):server.outbox.put({'type':'edit','message_id':999,'msg_type':'ai_reply','text':value,
            'web_display':build_web_display('```xgent-svg 尺寸适配\n'+value,hide_unclosed=True,reply_message_id=999)})
        emit(source)
        card=page.locator('.visual-page');frame=card.locator('.visual-page-frame').content_frame
        frame.locator('#canvas').wait_for()
        page.wait_for_function('document.querySelector(".visual-page").classList.contains("visual-graphic")')
        def bounds():return card.evaluate('card=>{const box=card.getBoundingClientRect(),view=card.querySelector(".visual-page-viewport").getBoundingClientRect(),frame=card.querySelector("iframe").getBoundingClientRect();return {width:box.width,height:box.height,viewWidth:view.width,viewHeight:view.height,frameWidth:frame.width,frameHeight:frame.height,overflow:frame.left<view.left-1||frame.top<view.top-1||frame.right>view.right+1||frame.bottom>view.bottom+1};}')
        box=bounds();assert abs(box['viewWidth']/box['viewHeight']-w/h)<.02
        assert abs(box['viewWidth']-box['frameWidth'])<1 and abs(box['viewHeight']-box['frameHeight'])<1 and not box['overflow']
        assert box['viewWidth']<=w*.8+1 and box['viewHeight']<=h*.8+1
        assert box['viewHeight']<=440 and box['width']<=page.locator('.body').first.bounding_box()['width']+1
        assert frame.locator('html').evaluate('node=>node.scrollHeight<=innerHeight+1&&node.scrollWidth<=innerWidth+1')
        frame.locator('#canvas').evaluate('node=>window.originalSvgNode=node')
        source+=f'<circle id="live" cx="{w/2}" cy="{h/2}" r="20"/>'
        emit(source);frame.locator('#live').wait_for()
        assert frame.locator('#canvas').evaluate('node=>node===window.originalSvgNode')
        assert bounds()==box
        source+='</svg>\n```';emit(source)
        page.wait_for_function('document.querySelector(".visual-page").getAttribute("aria-busy")==="false"')
        assert bounds()==box
        page.screenshot(path=str(tmp_path/f'fit-svg-{w}-{h}-{width}.png'))
        # Expanded view recomputes one scale and returning retains the page state.
        frame.locator('body').evaluate('()=>window.savedPageState=123')
        card.get_by_role('button',name='展开页面',exact=True).click()
        page.wait_for_function('document.querySelector(".visual-page-expanded")!==null')
        assert not bounds()['overflow']
        card.get_by_role('button',name='关闭页面',exact=True).click()
        assert frame.locator('body').evaluate('()=>window.savedPageState===123')
        browser.close()


@pytest.mark.parametrize('width',[390,1440])
def test_full_window_canvas_game_keeps_centered_menu_inside_viewport(full_output_server,width):
    server=full_output_server[0]
    source='''<html><head><style>*{box-sizing:border-box;margin:0;padding:0}html,body{width:100%;height:100%;overflow:hidden;background:#05060d}canvas{display:block;width:100%;height:100%}.overlay{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px}h1{font-size:54px;margin-bottom:8px}.subtitle{font-size:14px;margin-bottom:28px}.description{font-size:13px;line-height:24px;margin-bottom:30px}button{padding:14px 38px;font-size:16px}</style></head><body><canvas></canvas><div class="overlay"><h1>NEON SURVIVOR</h1><div class="subtitle">赛博空间无尽求生</div><div class="description">第一行说明<br>第二行说明</div><button id="start" onclick="this.textContent='已启动'">启动协议 [START]</button></div><script>window.runs=(window.runs||0)+1;</script></body></html>'''
    async def history(limit):return [{'id':502,'role':'assistant','msg_type':'ai_reply','content':source,'timestamp':1,'conversation_id':'global_memory',
        'web_display':build_web_display('```xgent-html 游戏\n'+source+'\n```')}]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p);page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        # Compatibility: the previous sizing code could persist a clipped viewport.
        context.add_init_script('localStorage.setItem("xgent-visual-sizes",JSON.stringify({"global_memory:502:0":{width:250,logicalWidth:800,logicalHeight:160}}))')
        page.goto(base+'/#/chat?conversation=global_memory')
        card=page.locator('.visual-page');frame=card.locator('.visual-page-frame').content_frame
        page.wait_for_function('document.querySelector(".visual-page")?.classList.contains("visual-viewport-page")')
        frame.get_by_role('button',name='启动协议 [START]',exact=True).wait_for()
        page.wait_for_function('()=>JSON.parse(localStorage.getItem("xgent-visual-sizes"))["global_memory:502:0"].logicalHeight>=600')
        assert frame.locator('body').evaluate('()=>[document.querySelector("h1"),document.querySelector("#start")].every(node=>{const r=node.getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1;})')
        assert card.locator('.visual-page-viewport').bounding_box()['height']<=440
        frame.get_by_role('button',name='启动协议 [START]',exact=True).click()
        handle=card.get_by_role('button',name='拖拽等比例调整页面大小',exact=True);handle.focus();page.keyboard.press('ArrowLeft')
        assert frame.locator('body').evaluate('()=>window.runs===1')
        assert frame.get_by_role('button',name='已启动',exact=True).is_visible()
        browser.close()


@pytest.mark.parametrize('width',[390,1440])
def test_drag_scales_the_whole_page_remembers_each_card_and_can_restore_auto(full_output_server,width,tmp_path):
    server=full_output_server[0]
    raw=''.join('```xgent-html 页面 '+str(i)+'\n<article style="width:320px;height:240px;background:purple"><button onclick="this.textContent=\'已点击\'">交互按钮</button></article>\n```\n' for i in range(2))
    display=build_web_display(raw)
    async def history(limit):return [{'id':501,'role':'assistant','msg_type':'ai_reply','content':raw,'timestamp':1,'conversation_id':'global_memory','web_display':display}]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p);page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        page.goto(base+'/#/chat?conversation=global_memory')
        cards=page.locator('.visual-page');first=cards.nth(0);second=cards.nth(1)
        page.wait_for_function('document.querySelectorAll(".visual-page-ready").length===2')
        page.wait_for_function('Math.abs(document.querySelector(".visual-page-viewport").clientWidth-256)<2')
        frame=first.locator('.visual-page-frame').content_frame
        frame.get_by_role('button',name='交互按钮',exact=True).click()
        frame.locator('body').evaluate('()=>window.keepState=123')
        original=first.locator('.visual-page-viewport').bounding_box()
        logical=frame.locator('html').evaluate('()=>[innerWidth,innerHeight]')
        handle=first.get_by_role('button',name='拖拽等比例调整页面大小',exact=True)
        cardbox=first.bounding_box();handlebox=handle.bounding_box()
        assert abs(handlebox['x']-cardbox['x']-cardbox['width'])<1
        assert handlebox['height']>handlebox['width']*2 and handle.locator('svg').count()==0
        assert handle.locator('.visual-page-resize-grip').is_visible()
        assert abs(handlebox['y']+handlebox['height']/2-cardbox['y']-cardbox['height']/2)<2
        def drag(dx,dy):
            box=handle.bounding_box();x=box['x']+box['width']/2;y=box['y']+box['height']/2
            if width==390:
                client=context.new_cdp_session(page)
                client.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
                for step in range(1,9):client.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x+dx*step/8,'y':y+dy*step/8}]})
                client.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]});client.detach()
            else:
                page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+dx,y+dy,steps=8);page.mouse.up()
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        drag(-55,-42)
        resized=first.locator('.visual-page-viewport').bounding_box()
        assert resized['width']<original['width'] and abs(resized['width']/resized['height']-4/3)<.02
        assert frame.locator('html').evaluate('()=>[innerWidth,innerHeight]')==logical
        assert frame.locator('body').evaluate('()=>window.keepState===123')
        assert frame.get_by_role('button',name='已点击',exact=True).is_visible()
        assert abs(second.locator('.visual-page-viewport').bounding_box()['width']-original['width'])<2
        assert page.evaluate('Object.keys(JSON.parse(localStorage.getItem("xgent-visual-sizes"))).length')==1
        page.reload();page.wait_for_function('document.querySelectorAll(".visual-page-ready").length===2')
        page.wait_for_function('width=>Math.abs(document.querySelector(".visual-page-viewport").clientWidth-width)<2',arg=resized['width'])
        first.get_by_role('button',name='恢复自动大小',exact=True).click()
        page.wait_for_function('Math.abs(document.querySelector(".visual-page-viewport").clientWidth-256)<2')
        assert not first.get_by_role('button',name='恢复自动大小',exact=True).is_visible()
        drag(70,54)
        grown=first.locator('.visual-page-viewport').bounding_box()
        assert grown['width']>original['width'] and abs(grown['width']/grown['height']-4/3)<.02
        first.get_by_role('button',name='源码',exact=True).click()
        assert handle.is_hidden()
        first.get_by_role('button',name='预览',exact=True).click()
        page.wait_for_function('width=>Math.abs(document.querySelector(".visual-page-viewport").clientWidth-width)<2',arg=grown['width'])
        first.get_by_role('button',name='展开页面',exact=True).click();assert handle.is_hidden()
        first.get_by_role('button',name='关闭页面',exact=True).click()
        page.wait_for_function('width=>Math.abs(document.querySelector(".visual-page-viewport").clientWidth-width)<2',arg=grown['width'])
        page.screenshot(path=str(tmp_path/f'resizable-page-{width}.png'))
        handle.focus();page.keyboard.press('Home')
        page.wait_for_function('Math.abs(document.querySelector(".visual-page-viewport").clientWidth-256)<2')
        handle.focus();page.keyboard.press('ArrowRight')
        page.wait_for_function('document.querySelector(".visual-page-viewport").clientWidth>256')
        assert abs(first.locator('.visual-page-viewport').bounding_box()['width']/first.locator('.visual-page-viewport').bounding_box()['height']-4/3)<.02
        browser.close()


@pytest.mark.parametrize('width',[390,1440])
def test_html_card_shrinks_to_content_but_long_page_keeps_readable_scroll(full_output_server,width):
    server=full_output_server[0]
    async def history(limit):return []
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p);page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        page.goto(base+'/#/chat?conversation=global_memory');page.wait_for_function('!document.getElementById("btn-send").disabled')
        def emit(source,mid):server.outbox.put({'type':'edit','message_id':mid,'msg_type':'ai_reply','text':source,
            'web_display':build_web_display('```xgent-html 卡片\n'+source+'\n```',reply_message_id=mid)})
        emit('<article style="width:240px;height:200px;background:purple"><button>点击</button></article>',998)
        compact=page.locator('.visual-page').first
        compact.locator('.visual-page-frame').content_frame.get_by_role('button',name='点击',exact=True).wait_for()
        page.wait_for_function('Math.abs(document.querySelector(".visual-page").getBoundingClientRect().width-194)<2')
        assert abs(compact.locator('.visual-page-viewport').bounding_box()['height']-160)<2
        emit('<main style="font-size:18px;line-height:30px">'+''.join('<p>长网页内容 '+str(i)+'</p>' for i in range(100))+'</main>',999)
        long=page.locator('.visual-page').nth(1);frame=long.locator('.visual-page-frame').content_frame
        frame.get_by_text('长网页内容 99',exact=True).wait_for(state='attached')
        assert long.locator('.visual-page-viewport').bounding_box()['height']<=440
        assert frame.locator('main').evaluate('node=>getComputedStyle(node).fontSize')=='18px'
        assert frame.locator('html').evaluate('node=>node.scrollHeight>innerHeight')
        browser.close()


@pytest.mark.parametrize('width',[390,1440])
def test_pure_svg_inside_html_wrapper_fits_without_becoming_a_long_webpage(full_output_server,width):
    server=full_output_server[0]
    async def history(limit):return []
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p);page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        page.goto(base+'/#/chat?conversation=global_memory');page.wait_for_function('!document.getElementById("btn-send").disabled')
        source='<html><head><style>body{display:flex;justify-content:center}.drawing{max-width:300px;width:100%}</style></head><body><div class="drawing"><svg viewBox="0 0 300 600" width="100%" height="100%"><rect id="draw" width="300" height="600" fill="purple"/>'
        def emit(value):server.outbox.put({'type':'edit','message_id':999,'text':value,'msg_type':'ai_reply',
            'web_display':build_web_display('```xgent-html 图形\n'+value,hide_unclosed=True,reply_message_id=999)})
        emit(source)
        card=page.locator('.visual-page');frame=card.locator('.visual-page-frame').content_frame
        frame.locator('#draw').wait_for()
        page.wait_for_function('document.querySelector(".visual-page").classList.contains("visual-graphic")')
        page.wait_for_function('(()=>{const box=document.querySelector(".visual-page-viewport").getBoundingClientRect();return Math.abs(box.width/box.height-.5)<.02;})()')
        assert frame.locator('html').evaluate('node=>node.scrollHeight<=innerHeight+1&&node.scrollWidth<=innerWidth+1')
        frame.locator('#draw').evaluate('node=>window.originalDrawing=node')
        source+='<circle id="more" cx="100" cy="100" r="10"/>'
        emit(source);frame.locator('#more').wait_for()
        assert frame.locator('#draw').evaluate('node=>node===window.originalDrawing')
        emit(source+'</svg></div></body></html>\n```')
        page.wait_for_function('document.querySelector(".visual-page").getAttribute("aria-busy")==="false"')
        assert frame.locator('html').evaluate('node=>node.scrollHeight<=innerHeight+1&&node.scrollWidth<=innerWidth+1')
        browser.close()
