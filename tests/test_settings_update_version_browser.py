"""Update completion clears stale offers and historical failures stay inspectable."""
import pytest

from tests.test_workbench_browser import browser_context,workspace_url,ready  # noqa: F401


@pytest.mark.parametrize('outcome',['failed','complete'])
def test_latest_version_cannot_repeat_update_and_old_jobs_are_historical(browser_context,workspace_url,outcome):
    page=browser_context.new_page();base=workspace_url['url'];version='a'*40
    job={'id':'b'*32,'revision':'b'*40,'state':outcome,'phase':outcome,'historical':True,
         'error':'上次重启后的版本与目标不一致' if outcome=='failed' else None,'backup_path':'/saved/custom-files'}
    page.route('**/api/workbench/system/update',lambda route:route.fulfill(json={
        'current_version':version,'has_token':False,'source':'normal','job':job}))
    page.route('**/api/workbench/system/update/check',lambda route:route.fulfill(json={
        'current_version':version,'revision':version,'up_to_date':True,'plan_id':'plan','message':'当前提交'}))
    ready(page,base,'settings');page.locator('.wb-settings-nav [data-panel=health]').click()
    card=page.locator('.wb-card').filter(has=page.get_by_role('heading',name='版本与更新',exact=True))
    history=card.locator('.wb-update-history');history.wait_for()
    assert history.get_attribute('open') is None
    assert '上次更新' in history.inner_text()
    history.locator('summary').click()
    assert '本地文件备份：/saved/custom-files' in history.inner_text()
    if outcome=='failed':assert job['error'] in history.inner_text()
    card.get_by_role('button',name='检查更新',exact=True).click()
    card.get_by_text('当前已是所选仓库的最新版本。',exact=True).wait_for()
    assert card.get_by_role('button',name='更新并重启',exact=True).is_disabled()
    card.locator('[name=overwrite]').check()
    assert card.get_by_role('button',name='更新并重启',exact=True).is_enabled()
    card.locator('[name=overwrite]').uncheck()
    assert card.get_by_role('button',name='更新并重启',exact=True).is_disabled()
    assert '当前版本：'+version in card.inner_text()
    page.close()
