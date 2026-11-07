"""Editor height is explicitly resizable without changing drafts or send behavior."""
import pytest
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session


@pytest.mark.parametrize('width',[390,1440])
def test_input_height_survives_typing_clearing_reload_and_small_viewport(full_output_server,width):
    server=full_output_server[0]
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p);page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        page.goto(base+'/#/chat?conversation=global_memory');page.wait_for_function('!document.getElementById("btn-send").disabled')
        input=page.get_by_role('textbox',name='消息',exact=True);handle=page.get_by_role('button',name='调整输入框高度',exact=True)
        original=input.bounding_box()['height'];box=handle.bounding_box();x=box['x']+box['width']/2;y=box['y']+box['height']/2
        composer=page.locator('.composer-card').bounding_box()
        assert box['x']<composer['x']<box['x']+box['width']
        assert abs(box['y']-composer['y']-13)<1
        assert box['width']==8 and handle.locator('svg').count()==0
        assert handle.locator('.composer-resize-grip').is_visible()
        if width==390:
            client=context.new_cdp_session(page);client.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
            client.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x,'y':y-100}]})
            client.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]});client.detach()
        else:page.mouse.move(x,y);page.mouse.down();page.mouse.move(x,y-100,steps=8);page.mouse.up()
        height=input.bounding_box()['height'];assert abs(height-original-100)<2
        assert abs(handle.bounding_box()['y']-page.locator('.composer-card').bounding_box()['y']-13)<1
        assert page.evaluate('Number(localStorage.getItem("xgent-composer-height"))')==height
        input.fill('\n'.join('长输入内容 '+str(i) for i in range(80)));assert input.bounding_box()['height']==height
        input.fill('保留我的草稿');assert input.bounding_box()['height']==height
        page.reload();page.wait_for_function('!document.getElementById("btn-send").disabled')
        assert input.bounding_box()['height']==height and input.input_value()=='保留我的草稿'
        input.fill('');assert input.bounding_box()['height']==height
        handle.focus();page.keyboard.press('ArrowUp');assert input.bounding_box()['height']>height
        stored=page.evaluate('Number(localStorage.getItem("xgent-composer-height"))')
        page.set_viewport_size({'width':width,'height':340})
        page.wait_for_function('document.querySelector("#input").getBoundingClientRect().height<=innerHeight*.45+1')
        assert page.locator('#log').bounding_box()['height']>50
        page.set_viewport_size({'width':width,'height':900})
        page.wait_for_function('height=>Math.abs(document.querySelector("#input").getBoundingClientRect().height-height)<2',arg=stored)
        handle.focus();page.keyboard.press('Home')
        assert abs(input.bounding_box()['height']-original)<2
        assert page.evaluate('localStorage.getItem("xgent-composer-height")') is None
        assert page.get_by_role('button',name='发送',exact=True).is_visible()
        handle.focus();page.keyboard.press('ArrowDown');page.keyboard.press('ArrowDown');page.keyboard.press('ArrowDown')
        assert input.bounding_box()['height']==28
        input.fill('压扁后仍能输入');assert input.bounding_box()['height']==28
        page.reload();page.wait_for_function('!document.getElementById("btn-send").disabled')
        assert input.bounding_box()['height']==28 and input.input_value()=='压扁后仍能输入'
        card=page.locator('.composer-card').bounding_box()
        for id in ('btn-composer-menu','btn-attach','btn-server-upload'):
            button=page.locator('#'+id);box=button.bounding_box()
            assert card['y']+card['height']-box['y']-box['height']<=5
            assert button.locator('svg').bounding_box()['width']<=15
        assert page.locator('.composer-footnote').count()==0
        assert abs(handle.bounding_box()['y']-card['y']-13)<1
        assert page.locator('#composer-model').evaluate('node=>{const css=getComputedStyle(node);return css.backgroundColor==="rgba(0, 0, 0, 0)"&&css.borderTopWidth==="0px";}')
        tool=page.locator('#btn-attach svg').bounding_box()
        thinking=page.locator('#composer-thinking .composer-choice-label').bounding_box()
        assert abs(tool['y']+tool['height']/2-thinking['y']-thinking['height']/2)<1.5
        browser.close()
