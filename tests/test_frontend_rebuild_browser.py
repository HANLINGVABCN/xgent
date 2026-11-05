"""User contracts for the rewritten chat/settings frontend, using isolated real services."""
import pytest

from tests.test_workbench_browser import browser_context, workspace_url, ready  # noqa: F401


PANELS = ['appearance','conversation','agent','web','data','health','tasks','files','models','usage','archive']
TARGETS = {
    'appearance':'.branding-form','conversation':'[name=global_depth]','agent':'[name=agent_max_iterations]',
    'web':'[name=web_public_url]','data':'.wb-backup-config-form','health':'.wb-diagnostics',
    'tasks':'.wb-task-stats','files':'form.wb-file-dates','models':'.wb-provider-list',
    'usage':'.wb-usage-stats','archive':'.settings-archive-panel',
}


def test_history_and_composer_survive_temporarily_empty_conversation_list(browser_context,workspace_url):
    page=browser_context.new_page();errors=[]
    snapshot=browser_context.request.get(workspace_url['url']+'/api/workbench/conversations').json()
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(workspace_url['url']+'/#/chat?conversation=global_memory')
    page.locator('#log .msg-row').first.wait_for()
    page.wait_for_function('document.querySelector("#composer-model")?.disabled===false')
    state=page.evaluate('snapshot=>{window.XGentConversations.accept({...snapshot,items:[]});return {count:window.XGentConversations.items.length,archived:window.XGentConversations.archived};}',snapshot)
    assert state=={'count':0,'archived':False}
    page.locator('#input').fill('对话列表加载期间保留的草稿')
    page.locator('#btn-composer-menu').click()
    page.locator('#composer-commands .composer-command').first.wait_for()
    page.keyboard.press('Escape')
    page.evaluate('window.XGentConversations.refresh()')
    page.wait_for_function('window.XGentConversations.items.length>0')
    page.wait_for_function('!document.querySelector("#btn-send").disabled')
    assert page.locator('#input').input_value()=='对话列表加载期间保留的草稿'
    assert not errors
    page.close()


@pytest.mark.parametrize('width',[320,390,768,1440])
def test_settings_is_one_retained_navigation_with_no_address_changes(browser_context,workspace_url,width):
    page=browser_context.new_page();page.set_viewport_size({'width':width,'height':900})
    ready(page,workspace_url['url'],'settings')
    page.emulate_media(reduced_motion='reduce')
    nav=page.locator('.wb-settings-nav');nav.wait_for()
    assert page.locator('#workspace-primary-nav').count()==0
    assert page.locator('#conversation-archive-view,#conversation-archive-count').count()==0
    assert nav.locator('a').count()==0
    assert nav.locator('button').count()==13
    assert nav.locator('[data-panel]').evaluate_all('(rows)=>rows.map(row=>row.dataset.panel)')==PANELS
    assert '工作' not in page.locator('#header').inner_text()
    assert '工作' not in nav.inner_text()
    page.evaluate('window.keptSettingsNavigation=document.querySelector(".wb-settings-nav")')
    original=page.url
    for panel in PANELS:
        nav.locator('[data-panel='+panel+']').click()
        page.locator(TARGETS[panel]).first.wait_for()
        assert page.url==original
        assert page.evaluate('document.body.dataset.page')=='settings'
        assert page.evaluate('window.keptSettingsNavigation===document.querySelector(".wb-settings-nav")')
        assert nav.locator('.active').get_attribute('data-panel')==panel
        assert page.locator('#wb-page-title').inner_text()=='设置'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    styles=nav.locator('button').evaluate_all('rows=>rows.map(n=>{const s=getComputedStyle(n);return [s.fontSize,s.fontWeight,s.minHeight,s.padding]})')
    assert len({tuple(style) for style in styles})==1
    page.close()


def test_settings_selection_preserves_dirty_form_and_keyboard_focus(browser_context,workspace_url):
    page=browser_context.new_page();ready(page,workspace_url['url'],'settings')
    page.locator('.wb-settings-nav [data-panel=conversation]').click()
    value=page.locator('[name=global_depth]');value.wait_for();value.fill('79')
    page.once('dialog',lambda dialog:dialog.dismiss())
    page.locator('.wb-settings-nav [data-panel=tasks]').click()
    assert value.input_value()=='79'
    assert page.locator('.wb-settings-nav .active').get_attribute('data-panel')=='conversation'
    page.once('dialog',lambda dialog:dialog.accept())
    page.locator('.wb-settings-nav [data-panel=agent]').focus();page.keyboard.press('Enter')
    page.locator('[name=agent_max_iterations]').wait_for()
    assert page.locator('.wb-settings-nav [data-panel=agent]').evaluate('(node)=>node===document.activeElement')
    page.keyboard.press('ArrowDown')
    assert page.locator('.wb-settings-nav [data-panel=web]').evaluate('(node)=>node===document.activeElement')
    page.close()


@pytest.mark.parametrize('theme',['light','dark'])
def test_file_preview_has_legible_theme_text_and_keeps_full_content(browser_context,workspace_url,theme):
    page=browser_context.new_page();ready(page,workspace_url['url'],'files')
    page.evaluate('(theme)=>document.body.classList.toggle("dark",theme==="dark")',theme)
    page.get_by_role('button',name='预览',exact=True).first.click()
    pre=page.locator('#wb-detail .wb-document-preview');pre.wait_for()
    assert pre.text_content()
    colors=pre.evaluate('(node)=>{const s=getComputedStyle(node);return [s.color,s.backgroundColor]}')
    assert colors[0]!=colors[1]
    channels=lambda color:[int(value.strip()) for value in color.removeprefix('rgb(').removesuffix(')').split(',')]
    assert abs(sum(channels(colors[0]))-sum(channels(colors[1])))>300
    text=pre.text_content()
    page.get_by_role('button',name='切换换行',exact=True).click()
    assert pre.text_content()==text
    assert pre.evaluate('(node)=>getComputedStyle(node).whiteSpace')=='pre'
    page.close()


def test_initial_chat_defers_management_modules_and_keeps_draft(browser_context,workspace_url):
    page=browser_context.new_page();requests=[]
    page.on('request',lambda request:requests.append(request.url))
    ready(page,workspace_url['url'])
    assert not any('/workbench-tasks.js' in url or '/workbench-files.js' in url or '/workbench-models.js' in url for url in requests)
    page.locator('#input').fill('保留构造对话之前的草稿')
    page.locator('#workspace-settings').click()
    page.locator('.wb-settings-nav [data-panel=tasks]').click();page.locator('.wb-task-stats').wait_for()
    assert any('/workbench-tasks.js' in url for url in requests)
    page.locator('.wb-brand').click();page.wait_for_function('document.body.dataset.page==="chat"')
    assert page.locator('#input').input_value()=='保留构造对话之前的草稿'
    page.close()


def test_conversation_fold_control_is_on_the_list_and_remains_reachable(browser_context,workspace_url):
    page=browser_context.new_page();page.set_viewport_size({'width':1440,'height':900});ready(page,workspace_url['url'])
    assert page.locator('#header #conversation-drawer-toggle').count()==0
    toggle=page.locator('#wb-nav #conversation-drawer-toggle');assert toggle.is_visible()
    toggle.click();assert page.locator('#conversation-scroll').is_hidden()
    assert toggle.is_visible() and toggle.get_attribute('aria-expanded')=='false'
    assert page.locator('#wb-nav').bounding_box()['width']<=60
    assert toggle.locator('use').get_attribute('href')=='#i-sidebar-show'
    toggle.click();page.locator('#conversation-list .conv-row').first.wait_for()
    assert toggle.get_attribute('aria-expanded')=='true'
    heights=page.locator('#conversation-list .conv-row:not(.is-child)').evaluate_all('rows=>rows.map(row=>row.getBoundingClientRect().height)')
    assert max(heights)<=34
    page.close()


def test_settings_reload_keeps_tab_conversation_and_reads_files_after_archive(browser_context,workspace_url):
    base=workspace_url['url'];first=browser_context.request.post(base+'/api/workbench/conversations/create',data={'name':'设置刷新保留选择'}).json()['current_chat_id']
    browser_context.request.post(base+'/api/workbench/conversations/create',data={'name':'其他标签页默认选择'})
    page=browser_context.new_page();ready(page,base);page.evaluate('window.XGentConversations.refresh()')
    page.evaluate('(id)=>window.XGentConversations.select(id)',first)
    page.locator('#workspace-settings').click();page.locator('.wb-settings-nav').wait_for();page.reload()
    page.locator('.wb-settings-nav').wait_for();page.wait_for_function('(id)=>window.XGentConversations.current===id',arg=first)
    assert page.url==base+'/#/settings'
    assert browser_context.request.post(base+'/api/workbench/conversations/archive',data={'id':first}).ok
    page.goto(base+'/#/files');page.locator('form.wb-file-dates').wait_for()
    page.locator('.wb-file-grid').wait_for();assert page.locator('#settings-content .wb-error').count()==0
    page.close()


@pytest.mark.parametrize('width',[390,1440])
def test_aligned_brand_save_close_icon_and_outside_dismiss(browser_context,workspace_url,width):
    page=browser_context.new_page();page.set_viewport_size({'width':width,'height':960});ready(page,workspace_url['url'],'settings')
    page.locator('.wb-settings-nav [data-panel=appearance]').click();page.locator('.branding-form').wait_for()
    name,save=page.locator('.brand-preview-row').evaluate('n=>[n.querySelector("input"),n.querySelector("button")].map(e=>e.getBoundingClientRect().toJSON())')
    assert abs(name['y']-save['y'])<1 and abs(name['height']-save['height'])<1
    page.locator('#workspace-search-open').click();dialog=page.locator('#global-search-dialog');dialog.wait_for()
    close=dialog.get_by_role('button',name='关闭全局搜索');box=close.bounding_box();icon=close.locator('svg').bounding_box()
    assert abs(box['x']+box['width']/2-icon['x']-icon['width']/2)<1
    assert abs(box['y']+box['height']/2-icon['y']-icon['height']/2)<1
    page.mouse.click(3,3);dialog.wait_for(state='detached')
    page.locator('.wb-settings-nav [data-panel=models]').click();page.get_by_role('button',name='添加提供商',exact=True).first.click()
    page.mouse.click(3,3);page.locator('#wb-dialog').wait_for(state='hidden')
    page.close()


def test_new_provider_fetch_uses_unsaved_connection_and_preserves_editor(browser_context,workspace_url):
    page=browser_context.new_page();ready(page,workspace_url['url'],'models')
    original=browser_context.request.get(workspace_url['url']+'/api/workbench/providers').json()
    requests=[]
    def fetch(route):requests.append(route.request.post_data_json);route.fulfill(json={'models':['draft-small','draft-large']})
    page.route('**/api/workbench/providers/fetch',fetch)
    page.get_by_role('button',name='添加提供商',exact=True).first.click();dialog=page.locator('#wb-dialog')
    fetch_button=dialog.get_by_role('button',name='拉取候选模型',exact=True);assert fetch_button.is_visible()
    dialog.locator('[name=name]').fill('临时连接');dialog.locator('[name=base_url]').fill('https://draft.invalid/v1');dialog.locator('[name=api_key]').fill('FAKE-DRAFT-KEY')
    fetch_button.click();dialog.get_by_role('heading',name='2 个候选模型',exact=True).wait_for()
    assert requests[0]['connection']['base_url']=='https://draft.invalid/v1'
    assert requests[0]['connection']['api_key']=='FAKE-DRAFT-KEY'
    assert browser_context.request.get(workspace_url['url']+'/api/workbench/providers').json()==original
    dialog.get_by_role('checkbox',name='draft-small',exact=True).check();dialog.get_by_role('button',name='应用到列表',exact=True).click()
    assert dialog.locator('[name=models]').input_value()=='draft-small'
    assert dialog.locator('[name=api_key]').input_value()=='FAKE-DRAFT-KEY'
    page.once('dialog',lambda dialog:dialog.accept());page.keyboard.press('Escape');page.close()
