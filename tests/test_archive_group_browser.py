"""Hidden archived trees remain writable, with one entry and automatic restoration navigation."""
import pytest
from tests.test_workbench_browser import browser_context,workspace_url,ready  # noqa: F401


def create(context,base,name,parent=None):
    action='create_child' if parent else 'create'
    response=context.request.post(base+'/api/workbench/conversations/'+action,data={'name':name,**({'id':parent} if parent else {})})
    assert response.ok,response.text()
    return response.json()['conversation_id']


@pytest.mark.parametrize('width',[390,1440])
def test_archived_tree_enter_create_child_and_restore_original_group(browser_context,workspace_url,width,tmp_path):
    base=workspace_url['url']
    def organize(resource,**data):
        state=browser_context.request.get(base+'/api/workbench/conversations').json()
        response=browser_context.request.post(base+'/api/workbench/'+resource,data={'revision':state['revision'],**data})
        assert response.ok,response.text()
        return response.json()
    gid=organize('conversation-groups/create',name='归档恢复原分组')['group_id']
    parent=create(browser_context,base,'归档树形父对话')
    organize('conversations/move',id=parent,group_id=gid)
    organize('conversations/pin',id=parent,group_id=gid)
    child=create(browser_context,base,'归档树形子对话',parent)
    nested=create(browser_context,base,'归档树形孙对话',child)
    response=browser_context.request.post(base+'/api/workbench/conversations/archive',data={'id':parent})
    assert response.ok
    page=browser_context.new_page();page.set_viewport_size({'width':width,'height':1000})
    page.emulate_media(reduced_motion='reduce');ready(page,base,'archive')
    assert page.locator('#conversation-group-select option[value="__archived__"]').count()==0
    assert page.locator('#conversation-list [data-conversation-id="'+parent+'"]').count()==0
    root=page.locator('.archive-row[data-conversation-id="'+parent+'"]')
    kid=page.locator('.archive-row[data-conversation-id="'+child+'"]')
    root.wait_for()
    assert root.is_visible() and kid.is_hidden()
    root.locator('.archive-tree-toggle').click();assert kid.is_visible()
    kid.locator('.archive-tree-toggle').click();assert page.locator('.archive-row[data-conversation-id="'+nested+'"]').is_visible()
    assert '原分组：归档恢复原分组' in root.inner_text() and '原分组置顶' in root.inner_text()
    root.get_by_role('button',name='更多归档操作：归档树形父对话',exact=True).click()
    assert page.get_by_role('menuitem',name='重命名',exact=True).is_disabled()
    assert page.get_by_role('menuitem',name='新建子对话',exact=True).is_enabled()
    page.keyboard.press('Escape')
    root.get_by_role('button',name='进入对话',exact=True).click()
    page.wait_for_function('(id)=>window.XGentConversations.current===id&&document.body.dataset.page==="chat"',arg=parent)
    page.wait_for_function('document.querySelector("#btn-send").disabled===false')
    assert page.locator('#input').is_visible()
    requests=[];page.route('**/api/chat',lambda route:(requests.append(route.request.post_data_json),route.fulfill(json={'ok':True})))
    page.locator('#input').fill('归档里可以正常聊天');page.locator('#btn-send').click()
    page.wait_for_function('document.querySelector("#input").value===""')
    assert requests[0]['conversation_id']==parent
    state=browser_context.request.get(base+'/api/workbench/conversations').json()
    assert next(item for item in state['items'] if item['id']==parent)['archived']
    assert not browser_context.request.post(base+'/api/workbench/conversations/rename',data={'id':parent,'name':'禁止改名'}).ok
    if page.locator('#workspace-settings').is_hidden():page.locator('#conversation-mobile-toggle').click()
    page.locator('#workspace-settings').click();root.wait_for()
    root.get_by_role('button',name='更多归档操作：归档树形父对话',exact=True).click()
    page.get_by_role('menuitem',name='新建子对话',exact=True).click()
    page.wait_for_function('document.querySelectorAll(".archive-row").length>=4')
    state=browser_context.request.get(base+'/api/workbench/conversations').json()
    fresh=next(item['id'] for item in state['items'] if item.get('owner_conversation_id')==parent and item['id']!=child)
    added=next(item for item in state['items'] if item['id']==fresh)
    assert added['archived'] and added['owner_conversation_id']==parent
    assert page.locator('#conversation-list [data-conversation-id="'+fresh+'"]').count()==0
    assert page.evaluate('document.body.dataset.page')=='settings'
    page.locator('.archive-row[data-conversation-id="'+fresh+'"]').wait_for()
    root.locator('.archive-tree-toggle').click() if root.locator('.archive-tree-toggle').get_attribute('aria-expanded')=='false' else None
    page.screenshot(path=str(tmp_path/f'archive-tree-{width}.png'))
    root.get_by_role('button',name='恢复',exact=True).click()
    page.wait_for_function('(id)=>window.XGentConversations.current===id&&document.body.dataset.page==="chat"',arg=parent)
    assert page.locator('#conversation-group-select').input_value()==gid
    page.locator('#conversation-list [data-conversation-id="'+parent+'"]').wait_for(state='attached')
    state=browser_context.request.get(base+'/api/workbench/conversations').json()
    for cid in (parent,child,nested,fresh):
        item=next(item for item in state['items'] if item['id']==cid)
        assert not item['archived'] and item['group_id']==gid
    assert next(item for item in state['items'] if item['id']==parent)['pinned']
    page.close()
