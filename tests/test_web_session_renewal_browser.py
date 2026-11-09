"""Login lifetime controls update their wording and persist alongside access rules."""
import pytest

from tests.test_workbench_browser import browser_context, ready, workspace_url  # noqa: F401


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('workspace_url', [True], indirect=True)
def test_login_lifetime_settings_live_description_save_reload_and_device_details(browser_context, workspace_url, tmp_path, width):
    base = workspace_url['url']
    page = browser_context.new_page()
    page.set_viewport_size({'width': width, 'height': 900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    ready(page, base, 'settings')
    page.get_by_role('button', name='Web 与安全', exact=True).click()
    field = page.get_by_label('登录有效期（天）', exact=True)
    field.wait_for()
    assert field.input_value() == '30'
    renew = page.get_by_label('使用中自动延长登录', exact=True)
    assert renew.is_checked()
    summary = page.locator('.wb-session-policy-summary')
    assert '连续 30 天未使用' in summary.inner_text()
    field.fill('90')
    assert '连续 90 天未使用' in summary.inner_text()
    renew.uncheck()
    assert '自动续期已关闭' in summary.inner_text() and '90 天' in summary.inner_text()
    with page.expect_response('**/api/security/access/policy') as saved:
        page.get_by_role('button', name='保存登录设置', exact=True).click()
    assert saved.value.ok
    field.wait_for()
    assert field.input_value() == '90' and not renew.is_checked()
    page.reload()
    page.get_by_role('button', name='Web 与安全', exact=True).click()
    field.wait_for()
    assert field.input_value() == '90' and not renew.is_checked()
    field.fill('30')
    renew.check()
    with page.expect_response('**/api/security/access/policy'):
        page.get_by_role('button', name='保存登录设置', exact=True).click()
    field.wait_for()
    data = browser_context.request.get(base + '/api/security/access').json()
    assert data['policy']['wait_after'] == 5 and data['policy']['ban_after'] == 8
    assert data['policy']['session_days'] == 30 and data['policy']['session_auto_renew']
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    panel = page.locator('.wb-access-panel').filter(has=page.get_by_role('heading', name='已登录设备', exact=True))
    assert '当前到期' in panel.inner_text()
    panel.get_by_role('button', name='详情', exact=True).first.click()
    page.get_by_role('heading', name='已登录设备详情', exact=True).wait_for()
    assert '当前到期时间' in page.locator('#wb-dialog').inner_text()
    assert '使用中自动延长' in page.locator('#wb-dialog').inner_text()
    page.screenshot(path=str(tmp_path / f'login-renewal-{width}.png'))
    assert not errors
    page.close()
