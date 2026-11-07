"""Keyboard viewport resize/pan never leaves blank space below the composer."""
import pytest
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session

VIEWPORT_SCRIPT='''(() => {
  const viewport=new EventTarget();Object.assign(viewport,{height:844,width:390,offsetTop:0,offsetLeft:0,scale:1});
  Object.defineProperty(window,'visualViewport',{value:viewport,configurable:true});
  window.keyboardViewport=(height,top=0,scale=1,type='resize')=>{
    Object.assign(viewport,{height,offsetTop:top,scale});viewport.dispatchEvent(new Event(type));
  };
})();'''


def test_mobile_keyboard_animation_pan_close_and_pinch_keep_editor_attached(full_output_server,tmp_path):
    server=full_output_server[0];playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p);context.add_init_script(VIEWPORT_SCRIPT)
        page=context.new_page();page.set_viewport_size({'width':390,'height':844})
        page.goto(base+'/#/chat?conversation=global_memory');page.wait_for_function('!document.getElementById("btn-send").disabled')
        editor=page.get_by_role('textbox',name='消息',exact=True);editor.fill('键盘弹出前的草稿')
        handle=page.get_by_role('button',name='调整输入框高度',exact=True)
        handle.focus();page.keyboard.press('ArrowUp');page.keyboard.press('ArrowUp')
        stored=editor.bounding_box()['height'];editor.focus()
        page.evaluate('window.originalEditor=document.getElementById("input")')
        # Chrome overlay keyboard, Safari visual-viewport pan, early animation.
        for height,top,event in ((740,0,'resize'),(440,96,'resize'),(440,130,'scroll'),(550,40,'resize')):
            page.evaluate('([h,top,event])=>keyboardViewport(h,top,1,event)',[height,top,event])
            page.wait_for_function('([h,top])=>{const shell=document.getElementById("wb-shell").getBoundingClientRect();return Math.abs(shell.bottom-h-top)<1&&Math.abs(shell.top-top)<1;}',arg=[height,top])
            footer=page.locator('#wb-shell>footer').bounding_box();card=page.locator('.composer-card').bounding_box()
            assert abs(footer['y']+footer['height']-height-top)<1
            assert height+top-card['y']-card['height']<=5
            assert page.evaluate('([x,y])=>!!document.elementFromPoint(x,y)?.closest(".composer-card")',
                [card['x']+card['width']/2,card['y']+card['height']-8]), '父容器不能裁掉键盘上方的输入按钮栏'
            assert page.get_by_role('button',name='发送',exact=True).is_visible()
            assert editor.input_value()=='键盘弹出前的草稿'
            assert page.evaluate('originalEditor===document.getElementById("input")')
        page.screenshot(path=str(tmp_path/'keyboard-pan-mobile.png'))
        # Some browsers scroll the document as well as panning the viewport.
        # A fixed app frame must retain the same keyboard boundary.
        page.evaluate('document.documentElement.style.height="1400px";document.documentElement.style.overflow="auto";window.scrollTo(0,90)')
        assert abs(page.locator('#wb-shell').bounding_box()['y']-40)<1
        assert abs(page.locator('#wb-shell').bounding_box()['height']-550)<1
        page.evaluate('document.documentElement.style.height="";document.documentElement.style.overflow="";window.scrollTo(0,0)')
        editor.blur();page.evaluate('keyboardViewport(844)')
        page.wait_for_function('document.getElementById("wb-shell").getBoundingClientRect().bottom===844')
        assert abs(editor.bounding_box()['height']-stored)<1
        assert not page.locator('body').evaluate('node=>node.classList.contains("wb-keyboard")')
        # Pinch zoom must not be interpreted as a software keyboard.
        page.evaluate('keyboardViewport(422,50,2)')
        page.wait_for_function('!document.body.classList.contains("viewport-fit")')
        assert page.locator('#wb-shell').bounding_box()['height']==844
        page.evaluate('keyboardViewport(844,0,1)')
        page.wait_for_function('document.body.classList.contains("viewport-fit")')
        assert page.locator('#log').bounding_box()['height']>400
        browser.close()


def test_keyboard_on_a_browser_that_resizes_layout_does_not_apply_height_twice(full_output_server):
    server=full_output_server[0];playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p);page=context.new_page()
        page.set_viewport_size({'width':390,'height':844})
        page.goto(base+'/#/chat?conversation=global_memory');page.wait_for_function('!document.getElementById("btn-send").disabled')
        editor=page.get_by_role('textbox',name='消息',exact=True);editor.fill('布局缩小后保留')
        for height in (740,480,360,844):
            page.set_viewport_size({'width':390,'height':height})
            page.wait_for_function('h=>Math.abs(document.getElementById("wb-shell").getBoundingClientRect().bottom-h)<1',arg=height)
            assert editor.input_value()=='布局缩小后保留'
            assert page.locator('#log').bounding_box()['height']>100
        browser.close()
