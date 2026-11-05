from pathlib import Path

import pytest

from tests.test_workbench_browser import workspace_url, browser_context, ready  # noqa: F401
from tests.test_workbench_page_cache import PROBE
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from tests.message_fixtures import typed_record


def test_setting_tabs_reuse_bootstrap_without_waiting_for_slow_optional_panels(browser_context, workspace_url):
    page=browser_context.new_page();page.add_init_script(PROBE);ready(page,workspace_url['url'],'settings')
    page.locator('input[name=web_ui_font_size]').wait_for()
    before=page.evaluate('window.__reads.filter(path=>path.split("?")[0]==="/api/workbench/bootstrap").length')
    page.evaluate("window.__delay['/api/workbench/bootstrap']=1200")
    elapsed=page.evaluate('''()=>new Promise(resolve=>{
      const start=performance.now();[...document.querySelectorAll('.wb-settings-nav [data-panel]')].find(node=>node.textContent==='Agent').click();
      const check=()=>{if(document.querySelector('#wb-page input[name=agent_max_iterations]'))resolve(performance.now()-start);else requestAnimationFrame(check);};check();
    })''')
    assert elapsed<400,elapsed
    assert page.evaluate('window.__reads.filter(path=>path.split("?")[0]==="/api/workbench/bootstrap").length')==before
    held=[]
    page.route('**/api/security/2fa',lambda route:held.append(route))
    page.get_by_role('button',name='Web 与安全',exact=True).click()
    page.locator('input[name=web_public_url]').wait_for()
    assert page.get_by_role('button',name='外观',exact=True).is_enabled()
    page.get_by_role('button',name='对话与记忆',exact=True).click()
    page.locator('input[name=global_depth]').wait_for()
    for route in held:route.fulfill(json={'enabled':False,'recovery_remaining':0})
    page.close()


def test_slow_backup_estimate_does_not_block_tabs(browser_context,workspace_url):
    page=browser_context.new_page();held=[]
    page.route('**/api/workbench/data/estimate**',lambda route:held.append(route))
    ready(page,workspace_url['url'],'settings')
    with page.expect_request('**/api/workbench/data/estimate**'):
        page.get_by_role('button',name='数据与备份',exact=True).click()
    assert page.get_by_text('正在读取…',exact=True).is_visible()
    page.get_by_role('button',name='Agent',exact=True).click()
    page.locator('input[name=agent_max_iterations]').wait_for()
    for route in held:route.abort()
    page.close()


def test_deferred_health_panel_refreshes_and_retries_with_cached_bootstrap(browser_context,workspace_url):
    page=browser_context.new_page();status={'failed':False,'version':1}
    def health(route):
        if status['failed']:route.fulfill(status=503,json={'error':'fixture health unavailable'})
        else:route.fulfill(json={'components':{'fixture':{'state':'up','error':'fixture health '+str(status['version'])}}})
    page.route('**/api/health',health)
    ready(page,workspace_url['url'],'settings')
    page.get_by_role('button',name='系统状态',exact=True).click()
    page.get_by_text('fixture health 1',exact=True).wait_for()
    status['failed']=True
    page.get_by_role('button',name='刷新状态',exact=True).click()
    page.get_by_text('fixture health unavailable',exact=True).wait_for()
    assert page.get_by_role('button',name='检查服务状态',exact=True).is_visible()
    status.update(failed=False,version=2)
    page.get_by_role('button',name='重试',exact=True).click()
    page.get_by_text('fixture health 2',exact=True).wait_for()
    page.close()


@pytest.mark.parametrize('width',[1440,390])
def test_error_and_normal_headers_keep_original_layout_and_avatar_inline(full_output_server,width,tmp_path):
    server=full_output_server[0]
    error='⚠️ {"error":{"reason":"prohibited_content","original":"ORIGINAL_ERROR"}}'
    generation={'provider':'fixture-provider','model':'fixture-model'}
    records=[typed_record(row) for row in [
        {'id':701,'role':'user','msg_type':'user_text','content':'first','timestamp':1},
        {'id':702,'role':'assistant','msg_type':'ai_reply','content':'normal answer','timestamp':2,'ai_generation':generation},
        {'id':703,'role':'user','msg_type':'user_text','content':'second','timestamp':3},
        {'id':704,'role':'assistant','msg_type':'runtime_error','content':error,'timestamp':4,'model_error':True,'ai_generation':generation},
    ]]
    async def history(limit):return records
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        try:
            page=context.new_page();page.set_viewport_size({'width':width,'height':844});page.goto(base)
            for identifier in (702,704):
                row=page.locator(f'[data-record-id="{identifier}"]');row.locator('.ai-generation-meta').wait_for()
                metrics=row.evaluate('''node=>{
                  const name=node.querySelector('[data-brand-name]').getBoundingClientRect(),icon=node.querySelector('[data-brand-logo]').getBoundingClientRect(),
                    body=node.querySelector('.body').getBoundingClientRect(),model=node.querySelector('.ai-generation-meta').getBoundingClientRect(),log=document.getElementById('log').getBoundingClientRect();
                  return {name:name.x,body:body.x,iconRight:icon.right,iconLeft:icon.left,logLeft:log.left,
                    modelX:model.x,nameRight:name.right,line:Math.abs((model.y+model.height/2)-(name.y+name.height/2))};
                }''')
                assert abs(metrics['iconLeft']-metrics['body'])<1
                assert metrics['iconRight']<metrics['name'] and metrics['iconLeft']>=metrics['logLeft']
                assert abs(metrics['modelX']-metrics['nameRight']-8)<1 and metrics['line']<1
            assert page.locator('[data-record-id="704"] .body').inner_text()==error
            page.reload();page.locator('[data-record-id="704"] .ai-generation-meta').wait_for()
            assert page.locator('[data-record-id="704"] .body').inner_text()==error
            page.screenshot(path=str(tmp_path/f'inline-headers-{width}.png'))
        finally:browser.close()
