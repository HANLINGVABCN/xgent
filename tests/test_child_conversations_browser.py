"""Child navigation in the actual browser, over isolated fixture data."""
import pytest
from tests.test_workbench_browser import workspace_url, browser_context, ready


def row(page, cid):
    return page.locator('.conv-row[data-conversation-id="' + cid + '"]')


def create(context, base, name, parent=None):
    action = 'create_child' if parent else 'create'
    body = {'name': name, **({'id': parent} if parent else {})}
    response = context.request.post(base + '/api/workbench/conversations/' + action, data=body)
    assert response.ok, response.text()
    return response.json()['current_chat_id']


@pytest.mark.parametrize('width', [1440, 390])
def test_child_arrow_position_expansion_refresh_and_current_child(browser_context, workspace_url, tmp_path, width):
    base = workspace_url['url']
    parent = create(browser_context, base, '父对话 · 列表展开')
    child = create(browser_context, base, '子对话 · 后台核对', parent)
    nested = create(browser_context, base, '更下面的子对话', child)
    assert browser_context.request.post(base + '/api/workbench/conversations/switch', data={'id': parent}).ok
    page = browser_context.new_page()
    page.set_viewport_size({'width': width, 'height': 900 if width > 400 else 844})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    ready(page, base)
    page.wait_for_function('(cid)=>window.XGentConversations.current===cid', arg=parent)
    if width == 390:
        page.locator('#conversation-mobile-toggle').click()
    arrow = row(page, parent).locator('.conv-children-toggle')
    arrow.wait_for(state='visible')
    assert arrow.get_attribute('aria-expanded') == 'false'
    assert row(page, child).is_hidden()
    row(page, parent).hover()
    left, more = arrow.bounding_box(), row(page, parent).locator('.conv-more').bounding_box()
    assert left['x'] + left['width'] <= more['x'] + 1
    assert left['y'] + left['height'] <= row(page, parent).bounding_box()['y'] + row(page, parent).bounding_box()['height']
    arrow.click()
    assert row(page, child).is_visible()
    assert row(page, child).bounding_box()['y'] > row(page, parent).bounding_box()['y']
    assert row(page, child).bounding_box()['x'] > row(page, parent).bounding_box()['x']
    assert row(page, nested).is_hidden()
    row(page, child).locator('.conv-children-toggle').click()
    assert row(page, nested).is_visible()
    page.reload()
    ready(page, base)
    if width == 390:
        page.locator('#conversation-mobile-toggle').click()
    row(page, nested).wait_for(state='visible')
    page.screenshot(path=str(tmp_path / f'children-expanded-{width}.png'))
    row(page, parent).locator('.conv-children-toggle').click()
    assert row(page, child).is_hidden()
    assert page.evaluate('window.XGentConversations.current') == parent
    assert browser_context.request.post(base + '/api/workbench/conversations/switch', data={'id': nested}).ok
    page.evaluate('window.XGentConversations.refresh()')
    assert page.evaluate('window.XGentConversations.current') == parent
    page.evaluate('(id)=>window.XGentConversations.select(id)', nested)
    if width == 390:
        page.locator('#conversation-mobile-toggle').click()
    row(page, nested).wait_for(state='visible')
    assert row(page, nested).locator('.conv-open').get_attribute('aria-current') == 'true'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert not errors
    page.close()


def test_more_menu_creates_child_and_parent_delete_removes_entire_tree(browser_context, workspace_url):
    base = workspace_url['url']
    parent = create(browser_context, base, '要删除的父对话')
    other = create(browser_context, base, '另一个父对话')
    page = browser_context.new_page()
    ready(page, base)
    row(page, parent).locator('.conv-more').click()
    page.get_by_role('menuitem', name='新建子对话', exact=True).click()
    page.wait_for_function('(id)=>window.XGentConversations.current!==id', arg=other)
    child = page.evaluate('window.XGentConversations.current')
    assert row(page, child).is_visible()
    state = browser_context.request.get(base + '/api/workbench/conversations').json()
    assert next(item for item in state['items'] if item['id'] == child)['owner_conversation_id'] == parent
    row(page, parent).locator('.conv-more').click()
    page.get_by_role('menuitem', name='删除对话').click()
    dialog = page.get_by_role('dialog', name='删除对话')
    assert '包括 1 个子对话' in dialog.inner_text()
    dialog.get_by_role('button', name='永久删除', exact=True).click()
    row(page, parent).wait_for(state='detached')
    row(page, child).wait_for(state='detached')
    assert row(page, other).is_visible()
    page.close()
