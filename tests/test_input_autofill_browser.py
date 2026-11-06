"""Business fields reject login inference without changing input, drafts or credentials."""
import pytest
from urllib.parse import unquote

from tests.test_workbench_browser import browser_context,workspace_url,ready  # noqa: F401


def protected(locator,purpose='off'):
    assert locator.get_attribute('autocomplete')==purpose
    for name in ('data-lpignore','data-1p-ignore','data-bwignore'):
        assert locator.get_attribute(name)=='true'


@pytest.mark.parametrize('width',[390,1440])
def test_sidebar_search_rejects_autofill_and_keeps_explicit_search_and_clear(browser_context,workspace_url,width):
    base=workspace_url['url'];page=browser_context.new_page();page.set_viewport_size({'width':width,'height':900})
    ready(page,base)
    if page.locator('#conversation-search').is_hidden():page.locator('#conversation-mobile-toggle').click()
    search=page.locator('#conversation-search');protected(search)
    assert search.evaluate('node=>node.form') is None
    assert page.locator('#password').evaluate('node=>node.form.id')=='login-credentials'
    queries=[];page.route('**/api/workbench/global-search?*',lambda route:(queries.append(route.request.url),route.fulfill(json={'items':[]})))
    search.fill('我自己输入的查询')
    page.wait_for_function('document.querySelector("#conversation-list-title").textContent==="全局搜索"')
    # Reproduce the browser's native autofill notification after it changes value.
    search.evaluate('node=>{node.value="浏览器保存的账号";node.dispatchEvent(new AnimationEvent("animationstart",{animationName:"xgent-search-autofill",bubbles:true}));}')
    assert search.input_value()=='我自己输入的查询'
    page.wait_for_timeout(450)
    assert not any('浏览器保存的账号' in unquote(url) for url in queries)
    page.locator('#conversation-search-clear').click();assert search.input_value()==''
    search.evaluate('node=>{node.value="误填推荐";node.dispatchEvent(new AnimationEvent("animationstart",{animationName:"xgent-search-autofill",bubbles:true}));}')
    assert search.input_value()==''
    search.fill('正常继续输入');assert search.input_value()=='正常继续输入'
    assert search.evaluate('node=>node.readOnly') is False
    page.close()


def test_sidebar_native_autofill_state_is_reverted_before_search_handlers(browser_context,workspace_url):
    page=browser_context.new_page();ready(page,workspace_url['url'])
    search=page.locator('#conversation-search');search.fill('用户明确的查询')
    client=browser_context.new_cdp_session(page);client.send('DOM.enable');client.send('CSS.enable')
    root=client.send('DOM.getDocument')['root']['nodeId']
    node=client.send('DOM.querySelector',{'nodeId':root,'selector':'#conversation-search'})['nodeId']
    search.evaluate('node=>node.value="自动填入的历史账号"')
    # Force Chromium's native autofill pseudo state, including its CSS notification.
    client.send('CSS.forcePseudoState',{'nodeId':node,'forcedPseudoClasses':['autofill']})
    search.evaluate('node=>node.dispatchEvent(new InputEvent("input",{bubbles:true,inputType:"insertReplacementText"}))')
    assert search.input_value()=='用户明确的查询'
    client.send('CSS.forcePseudoState',{'nodeId':node,'forcedPseudoClasses':[]});client.detach()
    search.fill('手动编辑仍可继续');assert search.input_value()=='手动编辑仍可继续'
    page.close()


def test_dynamic_search_and_provider_fields_do_not_advertise_login(browser_context,workspace_url):
    page=browser_context.new_page();ready(page,workspace_url['url'],'models')
    protected(page.get_by_role('searchbox',name='搜索提供商或模型'))
    page.get_by_role('button',name='添加提供商',exact=True).first.click();dialog=page.locator('#wb-dialog')
    protected(dialog.locator('form'))
    protected(dialog.locator('[name=name]'));protected(dialog.locator('[name=base_url]'))
    protected(dialog.locator('[name=models]'));protected(dialog.locator('[name=api_key]'),'new-password')
    dialog.locator('[name=name]').fill('手动填写提供商')
    dialog.locator('[name=api_key]').fill('TEST-MANUAL-KEY')
    assert dialog.locator('[name=name]').input_value()=='手动填写提供商'
    assert dialog.locator('[name=api_key]').input_value()=='TEST-MANUAL-KEY'
    page.once('dialog',lambda prompt:prompt.accept());page.keyboard.press('Escape')
    page.locator('#workspace-search-open').click()
    protected(page.get_by_role('searchbox',name='全局搜索关键词'))
    page.keyboard.press('Escape');page.close()


def test_chat_draft_and_real_credential_controls_remain_supported(browser_context,workspace_url):
    page=browser_context.new_page();ready(page,workspace_url['url']);protected(page.locator('#input'))
    page.locator('#input').fill('用户自己的草稿');page.reload()
    page.wait_for_function('!document.querySelector("#btn-send").disabled')
    assert page.locator('#input').input_value()=='用户自己的草稿'
    assert page.locator('#password').get_attribute('autocomplete')=='current-password'
    assert page.locator('#password').get_attribute('data-1p-ignore') is None
    assert page.locator('#login-code').get_attribute('autocomplete')=='one-time-code'
    page.evaluate('location.hash="/settings"');page.locator('.wb-settings-nav [data-panel=web]').click()
    page.get_by_role('button',name='修改访问密码',exact=True).click()
    dialog=page.locator('#wb-dialog')
    for name in ('password','repeat'):
        field=dialog.locator('[name='+name+']')
        assert field.get_attribute('autocomplete')=='new-password'
        assert field.get_attribute('data-1p-ignore') is None
    assert dialog.locator('form').get_attribute('autocomplete')=='on'
    page.keyboard.press('Escape');page.close()


def test_standalone_ask_and_terminal_fields_follow_input_policy(browser_context,workspace_url):
    base=workspace_url['url'];page=browser_context.new_page();ready(page,base)
    page.evaluate('''async()=>{
      const {syncAskForm}=await import('/assets/ask-form.js');
      const row=document.createElement('div'),bubble=document.createElement('div');row.append(bubble);document.querySelector('#log').append(row);
      syncAskForm({row,bubble},{version:1,id:'input-policy-form',conversation_id:'global_memory',revision:1,status:'pending',draft:{},
        questions:[{id:'1',type:'text',prompt:'普通答案'},{id:'2',type:'secret',prompt:'工具密钥',var:'TOKEN'}]});
    }''')
    form=page.get_by_role('form',name='Agent 提问表单');protected(form)
    protected(form.get_by_role('textbox',name='普通答案'))
    secret=form.locator('input[type=password]');protected(secret,'new-password')
    secret.fill('MANUAL-SECRET');assert secret.input_value()=='MANUAL-SECRET'
    page.goto(base+'/terminal');protected(page.locator('#pasteBox'))
    assert page.locator('#pw').evaluate('node=>node.form.id')=='terminal-login-credentials'
    assert page.locator('#pw').get_attribute('autocomplete')=='current-password'
    assert page.locator('#otp').get_attribute('autocomplete')=='one-time-code'
    page.close()
