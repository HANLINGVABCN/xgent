"""Source hints stay dismissible and leave room for the return-to-bottom button."""
import json
import sqlite3
import time
from pathlib import Path

import pytest

from tests.test_workbench_browser import browser_context, workspace_url, ready  # noqa: F401
from tests.message_fixtures import typed_record


@pytest.fixture
def source_record(browser_context, workspace_url):
    base=workspace_url['url']
    response=browser_context.request.post(base+'/api/workbench/conversations/create',
        data={'name':'配置附件与搜索定位 · '+ '这是一段很长的对话名称' * 5})
    assert response.ok
    cid=response.json()['current_chat_id']
    uploads=Path(workspace_url['database_path']).parent/'xgent_storage'/'uploads'
    uploads.mkdir(parents=True,exist_ok=True)
    filename='source-navigation-test.txt'
    path=uploads/filename;path.write_text('配置内容',encoding='utf-8')
    with sqlite3.connect(workspace_url['database_path']) as conn:
        for index in range(82):
            file=index==41
            kind,role=('user_file','user') if file else ('ai_reply','assistant')
            text='来源跳转显示验收 · 配置文件' if file else '定位消息 '+str(index)
            meta={'attachments':[{'version':1,'path':filename,'name':filename,'storage':'uploads','mime_type':'text/plain'}],
                  'web_file_message':{'text':text}} if file else {}
            meta=typed_record({'msg_type':kind,'role':role,'metadata':meta})['metadata']
            cursor=conn.execute('INSERT INTO global_messages(chat_id,user_id,msg_type,role,content,timestamp,session_id,metadata) VALUES(1,1,?,?,?,?,?,?)',
                (kind,role,text,time.time()+index,cid,json.dumps(meta)))
            if file:anchor='history:'+str(cursor.lastrowid)
    assert browser_context.request.post(base+'/api/workbench/conversations/switch',data={'id':'global_memory'}).ok
    yield {'id':cid,'anchor':anchor,'filename':filename}
    assert browser_context.request.post(base+'/api/workbench/conversations/switch',data={'id':'global_memory'}).ok
    with sqlite3.connect(workspace_url['database_path']) as conn:
        conn.execute('DELETE FROM global_messages WHERE session_id=?',(cid,))
        conn.execute('DELETE FROM chat_sessions WHERE id=?',(cid,))
    path.unlink(missing_ok=True)


@pytest.mark.parametrize('width,dark,entry',[(360,False,'direct'),(390,True,'files'),(1440,False,'search')])
def test_source_hint_does_not_overlap_bottom_arrow_and_close_stays_visible(browser_context,workspace_url,source_record,width,dark,entry,tmp_path):
    base=workspace_url['url']
    page=browser_context.new_page();page.set_viewport_size({'width':width,'height':844})
    ready(page,base,'files' if entry=='files' else 'chat')
    page.evaluate('(dark)=>document.body.classList.toggle("dark",dark)',dark)
    if entry=='files':
        page.locator('.wb-file-table tbody tr').filter(has_text=source_record['filename']).locator('.wb-source-link').click()
    elif entry=='search':
        page.keyboard.press('Control+f')
        page.get_by_role('searchbox',name='全局搜索关键词',exact=True).fill('来源跳转显示验收')
        page.locator('#global-search-dialog .global-search-hit').first.click()
    else:
        page.goto(base+'/#/chat?conversation='+source_record['id']+'&message='+source_record['anchor'])
    banner=page.locator('#source-navigation')
    page.locator('#source-navigation .wb-source-label').filter(has_text='已定位来源消息').wait_for()
    close=page.get_by_role('button',name='关闭来源定位提示',exact=True)
    page.locator('#log').evaluate('node=>{node.scrollTop=0;node.dispatchEvent(new Event("scroll"));}')
    page.wait_for_function('document.getElementById("scroll-bottom").classList.contains("show")')
    page.mouse.move(1,1)
    styles=close.evaluate('node=>{const style=getComputedStyle(node);return {position:style.position,opacity:style.opacity,fontSize:style.fontSize};}')
    assert styles=={'position':'static','opacity':'1','fontSize':'16px'}
    box,cross,content,arrow=(locator.bounding_box() for locator in (banner,close,page.locator('.wb-source-content'),page.locator('#scroll-bottom')))
    assert cross['width']==cross['height']==28
    assert content['x']>=cross['x']+cross['width']+5
    assert box['x']+box['width']+6<=arrow['x']
    assert content['x']+content['width']<=box['x']+box['width']
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(tmp_path/'source-hint.png'))
    page.locator('#input').fill('当前位置草稿保留')
    before=page.locator('#log').evaluate('node=>({scroll:node.scrollTop,count:node.querySelectorAll(".msg-row").length})')
    close.click()
    assert banner.is_hidden() and page.evaluate('location.hash')=='#/chat?conversation='+source_record['id']
    assert page.locator('#input').input_value()=='当前位置草稿保留'
    assert page.evaluate('window.XGentConversations.current')==source_record['id']
    assert page.locator('#log').evaluate('node=>({scroll:node.scrollTop,count:node.querySelectorAll(".msg-row").length})')==before
    page.close()


@pytest.mark.parametrize('state',['loading','error'])
def test_source_hint_can_be_closed_while_loading_or_after_failure(browser_context,workspace_url,source_record,state):
    page=browser_context.new_page();page.set_viewport_size({'width':390,'height':844})
    ready(page,workspace_url['url'])
    page.locator('#input').fill('不应被跳转清除')
    if state=='loading':
        page.evaluate('()=>{window.XGentConversations.refresh=()=>new Promise(resolve=>{window.__sourceRelease=resolve;});}')
    cid=source_record['id'] if state=='loading' else 'ffffffffffffffffffffffffffffffff'
    page.evaluate('(route)=>location.hash=route','#/chat?conversation='+cid+'&message='+source_record['anchor'])
    page.get_by_text('正在定位来源消息…' if state=='loading' else '来源对话已不存在',exact=True).wait_for()
    close=page.get_by_role('button',name='关闭来源定位提示',exact=True)
    page.mouse.move(1,1);assert close.is_visible()
    close.click()
    if state=='loading':
        page.evaluate('()=>{window.__sourceRelease();}')
    assert page.locator('#source-navigation').is_hidden()
    assert page.evaluate('location.hash')=='#/chat?conversation=global_memory'
    assert page.evaluate('window.XGentConversations.current')=='global_memory'
    assert page.locator('#input').input_value()=='不应被跳转清除'
    page.close()


def test_touch_can_close_source_hint_without_hover(browser_context,workspace_url,source_record):
    base=workspace_url['url']
    phone=browser_context.browser.new_context(storage_state=browser_context.storage_state(),
        viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    phone.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base) else route.abort())
    try:
        page=phone.new_page()
        page.goto(base+'/#/chat?conversation='+source_record['id']+'&message='+source_record['anchor'])
        page.locator('#source-navigation .wb-source-label').filter(has_text='已定位来源消息').wait_for()
        assert page.evaluate('matchMedia("(hover: none) and (pointer: coarse)").matches')
        close=page.get_by_role('button',name='关闭来源定位提示',exact=True)
        assert close.is_visible()
        close.tap()
        assert page.locator('#source-navigation').is_hidden()
        assert page.evaluate('location.hash')=='#/chat?conversation='+source_record['id']
        assert page.evaluate('window.XGentConversations.current')==source_record['id']
    finally:
        phone.close()
