import json
import sqlite3
import time

from tests.test_workbench_browser import workspace_url, browser_context, ready  # noqa: F401
from xgent_app.web_two_factor import totp


def test_manual_enrollment_recovery_and_two_step_password_login(browser_context, workspace_url, tmp_path):
    base = workspace_url['url']
    db = workspace_url['database_path']
    with sqlite3.connect(db) as conn:
        before = conn.execute('SELECT COUNT(*) FROM global_messages').fetchone()[0]
    page = browser_context.new_page()
    ready(page, base, 'settings')
    page.get_by_role('button', name='Web 与安全', exact=True).click()
    page.get_by_role('button', name='添加验证器', exact=True).wait_for()
    assert browser_context.request.get(base + '/api/security/2fa').json()['enabled'] is False
    page.get_by_role('button', name='添加验证器', exact=True).click()
    page.get_by_label('当前访问密码', exact=True).fill(workspace_url['password'])
    with page.expect_response('**/api/security/2fa/setup') as setup:
        page.get_by_role('button', name='生成绑定信息', exact=True).click()
    binding = setup.value.json()
    page.get_by_label('六位动态验证码', exact=True).wait_for()
    page.screenshot(path=str(tmp_path / 'two-factor-enrollment.png'))
    assert browser_context.request.get(base + '/api/security/2fa').json()['enabled'] is False
    page.get_by_label('六位动态验证码', exact=True).fill(totp(binding['secret'], int(time.time()) // 30))
    with page.expect_response('**/api/security/2fa/confirm') as confirmed:
        page.get_by_role('button', name='验证并启用', exact=True).click()
    result = confirmed.value.json()
    assert result['enabled'] is True and len(result['recovery_codes']) == 10
    page.get_by_role('button', name='已保存', exact=True).wait_for()
    page.get_by_role('button', name='已保存', exact=True).click()
    page.get_by_role('button', name='关闭两步验证', exact=True).wait_for()
    public = browser_context.request.get(base + '/api/security/2fa').json()
    assert binding['secret'] not in json.dumps(public)
    assert binding['secret'] not in json.dumps(browser_context.request.get(base + '/api/workbench/bootstrap').json())
    page.get_by_role('button', name='退出登录', exact=True).click()
    page.locator('#login').wait_for(state='visible')
    page.locator('#password').fill(workspace_url['password'])
    page.locator('#btn-login').click()
    page.locator('#login-code').wait_for(state='visible')
    assert page.locator('#password').is_hidden()
    assert browser_context.request.get(base + '/api/session').json()['authenticated'] is False
    page.locator('#login-code').fill('INVALID')
    page.locator('#btn-login').click()
    page.get_by_text('动态验证码或恢复码不正确', exact=True).wait_for()
    assert page.locator('#login-code').is_visible()
    page.locator('#login-code').fill(result['recovery_codes'][0])
    page.locator('#btn-login').click()
    page.locator('#login').wait_for(state='hidden')
    assert browser_context.request.get(base + '/api/security/2fa').json()['recovery_remaining'] == 9
    page.get_by_role('button', name='关闭两步验证', exact=True).wait_for()
    page.screenshot(path=str(tmp_path / 'two-factor-enabled.png'))
    page.get_by_role('button', name='关闭两步验证', exact=True).click()
    page.get_by_label('当前访问密码', exact=True).fill(workspace_url['password'])
    page.locator('#wb-dialog').get_by_label('动态验证码或恢复码', exact=True).fill(result['recovery_codes'][1])
    page.get_by_role('button', name='确认关闭', exact=True).click()
    page.get_by_role('button', name='添加验证器', exact=True).wait_for()
    assert browser_context.request.get(base + '/api/security/2fa').json()['enabled'] is False
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM global_messages').fetchone()[0] == before
    page.close()


def test_mobile_manual_key_layout_and_terminal_password_challenge(browser_context, workspace_url, tmp_path):
    base = workspace_url['url']
    page = browser_context.new_page()
    page.set_viewport_size({'width': 390, 'height': 844})
    ready(page, base, 'settings')
    page.get_by_role('button', name='Web 与安全', exact=True).click()
    page.get_by_role('button', name='添加验证器', exact=True).click()
    page.get_by_label('当前访问密码', exact=True).fill(workspace_url['password'])
    with page.expect_response('**/api/security/2fa/setup') as setup:
        page.get_by_role('button', name='生成绑定信息', exact=True).click()
    binding = setup.value.json()
    page.get_by_text('手动添加密钥', exact=True).click()
    assert page.get_by_text(binding['secret'], exact=True).is_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    page.screenshot(path=str(tmp_path / 'two-factor-mobile.png'))
    page.get_by_label('六位动态验证码', exact=True).fill(totp(binding['secret'], int(time.time()) // 30))
    with page.expect_response('**/api/security/2fa/confirm') as confirmed:
        page.get_by_role('button', name='验证并启用', exact=True).click()
    codes = confirmed.value.json()['recovery_codes']
    page.get_by_role('button', name='已保存', exact=True).click()
    assert browser_context.request.post(base + '/api/logout').ok
    page.goto(base + '/terminal')
    page.locator('#pw').wait_for(state='visible')
    page.locator('#pw').fill(workspace_url['password'])
    page.locator('#loginBtn').click()
    page.locator('#otp').wait_for(state='visible')
    assert page.locator('#pw').is_hidden()
    assert not browser_context.request.get(base + '/api/session').json()['authenticated']
    # Finish using a recovery code, then turn off the temporary fixture setting.
    with page.expect_response('**/api/login') as verified:
        page.locator('#otp').fill(codes[0])
        page.locator('#loginBtn').click()
    assert verified.value.json()['ok']
    assert browser_context.request.post(base + '/api/security/2fa/disable', data={
        'password': workspace_url['password'], 'code': codes[1]}).ok
    page.close()
