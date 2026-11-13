"""Native new-chat links, completion notices and late message-action recovery."""
from pathlib import Path

import pytest

from tests.test_workbench_browser import browser_context,workspace_url,ready  # noqa: F401
from tests.test_full_output_web import full_output_server  # noqa: F401


def test_new_chat_native_drag_and_modified_click_leave_source_and_database_alone(browser_context,workspace_url):
    base=workspace_url['url'];page=browser_context.new_page();ready(page,base)
    before=browser_context.request.get(base+'/api/workbench/conversations').json()
    page.locator('#input').fill('原标签页里的草稿')
    new=page.get_by_role('button',name='新对话',exact=True)
    assert new.evaluate('node=>node.tagName')=='A'
    assert new.get_attribute('href')=='#/chat' and new.get_attribute('draggable')=='true'
    page.evaluate('''()=>{const drop=document.createElement('div');drop.id='test-link-drop';drop.style='position:fixed;top:70px;right:30px;width:90px;height:90px;z-index:200;background:white';
      drop.ondragover=e=>e.preventDefault();drop.ondrop=e=>{e.preventDefault();window.droppedLink=e.dataTransfer.getData('text/uri-list');};document.body.append(drop);}''')
    new.drag_to(page.locator('#test-link-drop'))
    assert page.evaluate('window.droppedLink')==base+'/#/chat'
    page.locator('#test-link-drop').evaluate('node=>node.remove()')
    with browser_context.expect_page() as popup:new.click(modifiers=['Control'])
    other=popup.value;other.wait_for_function('window.XGentConversations&&window.XGentConversations.current===null')
    assert other.url.endswith('#/chat')
    assert page.locator('#input').input_value()=='原标签页里的草稿'
    assert page.evaluate('window.XGentConversations.current')==before['current_chat_id']
    assert len(browser_context.request.get(base+'/api/workbench/conversations').json()['items'])==len(before['items'])
    other.close();page.close()


@pytest.fixture
def followup_page(full_output_server):
    playwright=pytest.importorskip('playwright.sync_api');server=full_output_server[0];base=f'http://127.0.0.1:{server.config.port}'
    state={'done':False,'runs':{},'revision':1,'history_calls':[]}
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser=p.chromium.launch(headless=True);context=browser.new_context(reduced_motion='reduce')
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base) else route.abort())
        assert context.request.post(base+'/api/login',data={'password':'temporary-test-only'}).ok
        def conversations(route):route.fulfill(json={'revision':state['revision'],'current_chat_id':'A','runs':state['runs'],
             'items':[{'id':cid,'name':'对话 '+cid,'generation':7,'group_id':'ungrouped'} for cid in ('A','B')]})
        context.route('**/api/workbench/conversations',conversations)
        def history(route):
            state['history_calls'].append(route.request.url)
            user={'id':1,'role':'user','msg_type':'user_text','content':'我发出的消息','timestamp':1,'conversation_id':'A','turn_id':'turn-A'}
            if state['done']:user['conversation_actions']={'branch_mode':'user','withdraw':True}
            route.fulfill(json={'messages':[user,{'id':2,'role':'assistant','msg_type':'ai_reply','content':'实时回答内容','timestamp':2}],
                'conversation_id':'A','ui_generation':7,'busy':not state['done'],'next_cursor':None,'live':{**server.outbox.snapshot(),'frames':[]}})
        context.route('**/api/workbench/history?*',history)
        context.route('**/api/queue?*',lambda route:route.fulfill(json={'items':[],'conversation_id':'A','generation':7,'revision':0}))
        page=context.new_page();page.goto(base+'/#/chat?conversation=A');page.locator('[data-record-id="1"]').wait_for()
        yield page,server,state,base,context
        browser.close()


def test_running_other_chat_only_marks_list_then_completion_closes_and_expires(followup_page,tmp_path):
    page,server,state,base,context=followup_page
    page.evaluate('''()=>{window.savedInput=document.querySelector('#input');window.XGentConversations.accept({revision:2,current_chat_id:'A',runs:{B:{run_id:'B-1',conversation_id:'B'}},
      items:[{id:'A',name:'对话 A',generation:7},{id:'B',name:'对话 B',generation:7}]});}''')
    assert page.locator('#conversation-running').count()==0
    assert page.locator('.conv-row[data-conversation-id=B] .conv-running-dot').is_visible()
    assert page.locator('.conv-completion').count()==0
    server.outbox.put({'type':'generation_end','run_id':'B-1','conversation_id':'B','generation':7})
    notice=page.locator('.conv-completion');notice.wait_for();assert notice.inner_text().startswith('回复已完成')
    assert page.locator('.conv-row[data-conversation-id=B] .conv-running-dot').is_hidden()
    for width,height in ((1440,900),(390,844)):
        page.set_viewport_size({'width':width,'height':height})
        box=notice.bounding_box();assert box['x']>=0 and box['x']+box['width']<=width
        page.screenshot(path=str(tmp_path/f'completion-{width}.png'))
    page.set_viewport_size({'width':1440,'height':900})
    assert page.url.endswith('conversation=A')
    server.outbox.put({'type':'turn_end','run_id':'B-1','conversation_id':'B','generation':7})
    page.wait_for_timeout(150);assert notice.count()==1
    notice.get_by_role('button',name='关闭对话完成通知').click();assert notice.count()==0
    server.outbox.put({'type':'chat_action','action':'typing','run_id':'B-2','conversation_id':'B'})
    server.outbox.put({'type':'turn_end','run_id':'B-2','conversation_id':'B','generation':7})
    notice.wait_for();notice.wait_for(state='detached',timeout=10000)
    assert page.evaluate('window.savedInput===document.querySelector("#input")')


def test_user_actions_are_restored_when_loaded_during_generation_without_reload(followup_page):
    page,server,state,base,context=followup_page
    row=page.locator('[data-record-id="1"]')
    assert row.get_by_role('button',name='复制用户消息').count()==1
    assert row.locator('.conversation-action').count()==0
    page.locator('#input').fill('完成后仍保留的输入草稿')
    row.evaluate('node=>window.previousRow=node')
    state['done']=True
    server.outbox.put({'type':'turn_end','run_id':'A-1','conversation_id':'A','generation':7})
    row.get_by_role('button',name='分支到新聊天',exact=True).wait_for()
    assert row.get_by_role('button',name='撤回此消息及之后',exact=True).count()==1
    assert page.locator('#input').input_value()=='完成后仍保留的输入草稿'
    assert row.evaluate('node=>node===window.previousRow')
    assert any('presentation_ids=1' in path for path in state['history_calls'])
    assert page.locator('.conv-completion').count()==0


@pytest.mark.parametrize('width',[390,1440])
def test_update_settings_uses_checked_version_and_in_place_progress(browser_context,workspace_url,width,tmp_path):
    page=browser_context.new_page();ready(page,workspace_url['url'],'settings')
    page.set_viewport_size({'width':width,'height':950})
    job={'id':'a'*32,'state':'running','phase':'downloading','revision':'b'*40,'pid':1}
    requests=[]
    page.route('**/api/workbench/system/update*',lambda route:route.fulfill(json={'current_version':'old','has_token':True,'source':'test','job':job if requests else None}))
    page.route('**/api/workbench/system/update/check',lambda route:route.fulfill(json={'plan_id':'plan-test','revision':'b'*40,'current_version':'old','up_to_date':False,'message':'新版本更新内容','source':'test'}))
    def start(route):requests.append(route.request.post_data_json);route.fulfill(json={'ok':True,'id':job['id'],'job':job})
    page.route('**/api/workbench/system/update/start',start)
    page.locator('.wb-settings-nav [data-panel=health]').click()
    page.get_by_role('button',name='检查更新',exact=True).wait_for()
    card=page.locator('.wb-card').filter(has=page.get_by_role('heading',name='版本与更新',exact=True))
    assert card.locator('[name=overwrite]').is_checked() is False
    card.get_by_role('button',name='检查更新',exact=True).click()
    card.get_by_text('发现可更新版本。',exact=True).wait_for()
    card.get_by_role('button',name='更新并重启',exact=True).click()
    dialog=page.locator('#wb-dialog');assert '保留本地提示词与公共技能' in dialog.inner_text()
    dialog.get_by_role('button',name='确认操作',exact=True).click()
    card.get_by_text('正在下载并保存代码…',exact=True).wait_for()
    assert len(requests)==1 and requests[0]['plan_id']=='plan-test' and requests[0]['overwrite_local_custom_files'] is False
    assert page.url.endswith('#/settings')
    job.update(state='complete',phase='complete')
    card.get_by_text('更新完成，服务已重新启动。',exact=True).wait_for(timeout=7000)
    assert card.get_by_text('发现可更新版本。',exact=True).count()==0
    assert card.get_by_text('已更新至 '+'b'*10+'。',exact=True).is_visible()
    assert card.get_by_role('button',name='检查更新',exact=True).is_enabled()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(tmp_path/f'update-settings-{width}.png'))
    page.close()
