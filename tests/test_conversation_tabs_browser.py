"""Native links and independent browser tabs against the real loopback server."""
import pytest
from tests.test_workbench_browser import browser_context, workspace_url  # noqa: F401


def create(context, base, name):
    response = context.request.post(base + '/api/workbench/conversations/create', data={'name': name})
    assert response.ok
    return response.json()['current_chat_id']


def open_chat(context, base, cid):
    page = context.new_page()
    page.goto(base + '/#/chat?conversation=' + cid)
    page.wait_for_function('(id)=>window.XGentConversations?.current===id', arg=cid)
    page.wait_for_function('!document.getElementById("btn-send").disabled')
    return page


def link(page, cid):
    return page.locator(f'.conv-row[data-conversation-id="{cid}"] a.conv-open')


@pytest.mark.parametrize('method', ['control', 'middle'])
def test_native_link_opens_new_tab_without_switching_source(browser_context, workspace_url, method):
    base = workspace_url['url']
    a, b = create(browser_context, base, '标签 A'), create(browser_context, base, '标签 B')
    page = open_chat(browser_context, base, a)
    page.locator('#input').fill('A 的草稿')
    target = link(page, b)
    assert target.get_attribute('href') == '#/chat?conversation=' + b
    assert target.get_attribute('draggable') == 'true'
    with browser_context.expect_page() as capture:
        target.click(**({'modifiers': ['Control']} if method == 'control' else {'button': 'middle'}))
    other = capture.value
    other.wait_for_function('(id)=>window.XGentConversations?.current===id', arg=b)
    assert page.evaluate('window.XGentConversations.current') == a
    assert page.locator('#input').input_value() == 'A 的草稿'
    assert page.url.endswith('conversation=' + a)
    assert other.url.endswith('conversation=' + b)
    page.close()
    other.close()


def test_copied_url_opens_archived_conversation_read_only(browser_context, workspace_url):
    base = workspace_url['url']
    cid = create(browser_context, base, '复制地址和归档只读')
    page = open_chat(browser_context, base, cid)
    copied = page.url
    response = browser_context.request.post(base + '/api/workbench/conversations/archive', data={'id': cid})
    assert response.ok
    other = browser_context.new_page()
    other.goto(copied)
    other.wait_for_function('(id)=>window.XGentConversations?.current===id && window.XGentConversations.readOnly', arg=cid)
    assert other.locator('#btn-send').is_disabled()
    assert page.url == copied
    page.close()
    other.close()


def test_tabs_keep_selection_drafts_urls_and_back_forward(browser_context, workspace_url):
    base = workspace_url['url']
    a, b, c = (create(browser_context, base, '独立标签 ' + name) for name in ('A', 'B', 'C'))
    first, second = open_chat(browser_context, base, a), open_chat(browser_context, base, b)
    first.locator('#input').fill('A 独立草稿')
    second.locator('#input').fill('B 独立草稿')
    link(second, c).click()
    second.wait_for_function('(id)=>window.XGentConversations.current===id', arg=c)
    browser_context.request.post(base + '/api/workbench/conversations/switch', data={'id': 'global_memory'})
    first.evaluate('window.XGentConversations.refresh()')
    second.evaluate('window.XGentConversations.refresh()')
    assert first.evaluate('window.XGentConversations.current') == a
    assert second.evaluate('window.XGentConversations.current') == c
    assert first.locator('#input').input_value() == 'A 独立草稿'
    second.go_back()
    second.wait_for_function('(id)=>window.XGentConversations.current===id', arg=b)
    assert second.locator('#input').input_value() == 'B 独立草稿'
    second.go_forward()
    second.wait_for_function('(id)=>window.XGentConversations.current===id', arg=c)
    second.evaluate("location.hash='#/settings'")
    second.wait_for_function('document.body.dataset.page==="settings"')
    second.evaluate('(id)=>location.hash="#/chat?conversation="+id', b)
    second.wait_for_function('(id)=>window.XGentConversations.current===id && document.body.dataset.page==="chat"', arg=b)
    assert second.url.endswith('conversation=' + b)
    assert first.evaluate('window.XGentConversations.current') == a
    first.reload()
    first.wait_for_function('(id)=>window.XGentConversations.current===id', arg=a)
    assert first.locator('#input').input_value() == 'A 独立草稿'
    for cid in (a, b):
        response = browser_context.request.post(base + '/api/chat', data={'text': '标签定向请求', 'conversation_id': cid})
        assert response.ok, response.text()
    rejected = browser_context.request.get(base + '/api/workbench/history?conversation_id=missing-conversation')
    assert rejected.status in (404, 409)
    first.close()
    second.close()


def test_link_drag_is_native_and_file_drop_still_works(browser_context, workspace_url):
    base = workspace_url['url']
    cid = create(browser_context, base, '原生拖动链接')
    page = open_chat(browser_context, base, cid)
    result = link(page, cid).evaluate('''element=>{
      const data=new DataTransfer();data.setData('text/uri-list',element.href);
      const enter=new DragEvent('dragenter',{bubbles:true,cancelable:true,dataTransfer:data});
      element.dispatchEvent(enter);
      return {prevented:enter.defaultPrevented,overlay:document.getElementById('drop-overlay').classList.contains('active')};
    }''')
    assert result == {'prevented': False, 'overlay': False}
    page.evaluate('''()=>{
      const data=new DataTransfer();data.items.add(new File(['file content'],'tab-drop.txt',{type:'text/plain'}));
      window.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data}));
    }''')
    page.get_by_text('tab-drop.txt', exact=False).first.wait_for()
    page.close()
