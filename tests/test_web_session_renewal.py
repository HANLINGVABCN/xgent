"""Real HTTP renewal retains one device and never revives expired authorization."""
import asyncio
import http.client
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.test_web_two_factor import Database
from xgent_app import web_auth
from xgent_app.web_access import DEFAULT_POLICY, WebAccess
from xgent_app.web_server import WebChatConfig, WebChatServer
from xgent_app.web_two_factor import PASSWORD_KEY, WebTwoFactor, totp


DAY = 86400


@pytest.fixture
def renewal_instance():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    run = lambda coro: asyncio.run_coroutine_threadsafe(coro, loop).result(10)
    db = run(Database().open())
    async def database():
        return db
    async def empty(*args):
        return []
    access = WebAccess(database)
    run(access.initialize())
    secret = run(web_auth.load_session_secret(db))
    clock = SimpleNamespace(now=1700000000)

    class Instance:
        def start(self):
            self.factor = WebTwoFactor(database)
            self.server = WebChatServer(WebChatConfig(host='127.0.0.1', port=0,
                password_hash=run(db.get_config_fresh(PASSWORD_KEY)), bot_token='', authorized_user_id=1,
                loop=loop, submit_message=empty, read_history=empty, read_settings=empty,
                write_setting=empty, request_stop=lambda: None, is_busy=lambda: False,
                session_secret=secret, security_api=self.factor.handle, access_api=access.handle))
            self.server.start()

        def restart(self):
            self.server.stop()
            self.start()

        def request(self, path, data=None, jar=None):
            jar = self.cookies if jar is None else jar
            connection = http.client.HTTPConnection('127.0.0.1', self.server._httpd.server_address[1], timeout=5)
            connection.request('POST' if data is not None else 'GET', path,
                json.dumps(data) if data is not None else None,
                {'Cookie': '; '.join(k+'='+v for k, v in jar.items()), 'Content-Type': 'application/json'})
            response = connection.getresponse()
            payload = response.read()
            body = json.loads(payload) if 'json' in response.getheader('Content-Type', '') else payload
            headers = [v for k, v in response.getheaders() if k.lower() == 'set-cookie']
            for value in headers:
                jar.update(web_auth.parse_cookie_header(value.split(';')[0]))
            result = response.status, body, headers
            connection.close()
            return result

        def login(self, jar=None):
            result = self.request('/api/login', {'password': 'test-password'}, jar)
            assert result[0] == 200, result
            return result

        def session(self, sid=None):
            async def get():
                session_id = sid or self.cookies[web_auth.SESSION_COOKIE_NAME].split('.')[1]
                row = await (await db.connection.execute('SELECT * FROM web_login_sessions WHERE id=?', (session_id,))).fetchone()
                return dict(row)
            return run(get())

    instance = Instance()
    instance.cookies = {}
    instance.db, instance.run, instance.access, instance.clock = db, run, access, clock
    with patch('xgent_app.web_access.time.time', lambda: clock.now):
        instance.start()
        try:
            yield instance
        finally:
            instance.server.stop()
            run(db.close())
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)
    loop.close()


def test_active_use_continues_beyond_seven_days_and_retains_device_on_restart(renewal_instance):
    instance = renewal_instance
    login = instance.login()
    assert any('Max-Age=2678400' in header and 'HttpOnly' in header and 'SameSite=Lax' in header for header in login[2])
    sid = instance.session()['id']
    created = instance.session()['created_at']
    for _ in range(8):
        old = instance.cookies[web_auth.SESSION_COOKIE_NAME]
        instance.clock.now += 6*DAY
        assert instance.request('/api/session')[1]['authenticated']
        assert instance.cookies[web_auth.SESSION_COOKIE_NAME] != old
        assert instance.session()['id'] == sid
        assert instance.session()['created_at'] == created
        assert instance.session()['expires_at'] == instance.clock.now+30*DAY
    instance.restart()
    assert instance.request('/api/session')[1]['authenticated']
    assert instance.request('/api/security/access')[1]['sessions'][0]['id'] == sid
    instance.clock.now += 60
    assert instance.request('/api/session')[2] == []
    assert instance.session()['expires_at'] == instance.clock.now+30*DAY


def test_inactive_expiration_cannot_be_renewed_or_revived_by_increasing_days(renewal_instance):
    instance = renewal_instance
    instance.login()
    original = instance.session()
    instance.clock.now += 30*DAY+1
    assert not instance.request('/api/session')[1]['authenticated']
    assert instance.request('/api/history')[0] == 401
    instance.run(instance.access.handle('policy', {'session_days': 365, 'confirm': True}))
    assert not instance.request('/api/session')[1]['authenticated']
    assert instance.session()['expires_at'] == original['expires_at']


def test_old_valid_seven_day_device_renews_without_login_but_expired_one_does_not(renewal_instance):
    instance = renewal_instance
    instance.login()
    sid = instance.session()['id']
    async def old_expiry():
        await instance.db.connection.execute('UPDATE web_login_sessions SET expires_at=created_at+?', (7*DAY,))
    instance.run(old_expiry())
    instance.clock.now += 6*DAY
    assert instance.request('/api/session')[1]['authenticated']
    assert instance.session()['id'] == sid and instance.session()['expires_at'] == instance.clock.now+30*DAY
    second = {}
    instance.login(second)
    instance.run(old_expiry())
    instance.clock.now += 8*DAY
    assert not instance.request('/api/session', jar=second)[1]['authenticated']


def test_custom_days_disabled_renewal_and_policy_patch_preserve_other_rules(renewal_instance):
    instance = renewal_instance
    instance.login()
    policy = {**DEFAULT_POLICY, 'wait_after': 4, 'ban_after': 10, 'proxy_header': 'real-ip', 'confirm': True}
    assert instance.request('/api/security/access/policy', policy)[0] == 200
    assert instance.request('/api/security/access/policy', {'session_days': 7, 'session_auto_renew': False, 'confirm': True})[0] == 200
    saved = instance.request('/api/security/access')[1]['policy']
    assert saved['wait_after'] == 4 and saved['ban_after'] == 10 and saved['proxy_header'] == 'real-ip'
    expiry = instance.session()['expires_at']
    instance.clock.now += 6*DAY
    assert instance.request('/api/session')[1]['authenticated']
    assert instance.session()['expires_at'] == expiry
    instance.clock.now += 2*DAY
    assert not instance.request('/api/session')[1]['authenticated']
    instance.login()
    assert instance.session()['expires_at'] == instance.clock.now+7*DAY
    assert instance.request('/api/security/access/policy', {'wait_after': 3, 'confirm': True})[0] == 200
    saved = instance.request('/api/security/access')[1]['policy']
    assert saved['session_days'] == 7 and saved['session_auto_renew'] is False
    for value in (0, 366, True, '30', 1.5):
        assert instance.request('/api/security/access/policy', {'session_days': value, 'confirm': True})[0] == 400


def test_revoked_tampered_device_mismatch_and_blacklist_never_get_renewed(renewal_instance):
    instance = renewal_instance
    instance.login()
    cookie = dict(instance.cookies)
    instance.clock.now += 2*DAY
    assert not instance.request('/api/session', jar={**cookie, web_auth.SESSION_COOKIE_NAME: cookie[web_auth.SESSION_COOKIE_NAME]+'bad'})[1]['authenticated']
    assert not instance.request('/api/session', jar={web_auth.SESSION_COOKIE_NAME: cookie[web_auth.SESSION_COOKIE_NAME]})[1]['authenticated']
    assert instance.request('/api/security/access/revoke', {'id': instance.session()['id'], 'confirm': True})[0] == 200
    assert not instance.request('/api/session', jar=cookie)[1]['authenticated']
    instance.login()
    instance.request('/api/security/access/rule', {'network': '127.0.0.1', 'mode': 'black', 'confirm': True})
    assert instance.request('/api/session')[0] == 403


def test_stream_rechecks_do_not_count_as_activity_and_2fa_setup_survives_renewal(renewal_instance):
    instance = renewal_instance
    instance.login()
    session = instance.session()
    instance.clock.now += 2*DAY
    result = instance.run(instance.access.handle('session', {'id': session['id'], 'device': session['device'],
        'ip': session['ip'], 'key_version': session['key_version'], 'activity': False, 'renew': False}))
    assert result['valid'] and not result['renew']
    assert instance.session()['expires_at'] == session['expires_at'] and instance.session()['last_seen'] == session['last_seen']
    status, setup, _ = instance.request('/api/security/2fa/setup', {'password': 'test-password'})
    assert status == 200
    instance.clock.now += DAY
    assert instance.request('/api/session')[1]['authenticated']
    status, _, headers = instance.request('/api/security/2fa/confirm', {'setup_id': setup['setup_id'],
        'code': totp(setup['secret'], int(instance.clock.now)//30)})
    assert status == 200
    assert sum(header.startswith(web_auth.SESSION_COOKIE_NAME+'=') for header in headers) == 1
    assert instance.request('/api/session')[1]['authenticated']


def test_legacy_cookie_migration_respects_its_original_expiration(renewal_instance):
    instance = renewal_instance
    key = instance.server._httpd.session_key
    jar = {web_auth.SESSION_COOKIE_NAME: web_auth.make_session_cookie_value(key,
        issued_at=instance.clock.now-8*DAY)}
    assert not instance.request('/api/session', jar=jar)[1]['authenticated']
    jar[web_auth.SESSION_COOKIE_NAME] = web_auth.make_session_cookie_value(key, issued_at=instance.clock.now-6*DAY)
    assert instance.request('/api/session', jar=jar)[1]['authenticated']
    assert jar[web_auth.SESSION_COOKIE_NAME].count('.') == 2


def test_download_and_sse_handshake_return_renewal_cookie_but_heartbeats_do_not(renewal_instance, tmp_path):
    from xgent_app.web_bridge import MEDIA_TOKEN_REGISTRY

    instance = renewal_instance
    instance.login()
    sid = instance.session()['id']
    instance.clock.now += 2*DAY
    original = tmp_path/'renewal.txt'
    original.write_bytes(b'DOWNLOAD_CONTENT')
    token = MEDIA_TOKEN_REGISTRY.register(str(original), original.name)
    status, body, headers = instance.request('/api/media/'+token)
    assert status == 200 and body == b'DOWNLOAD_CONTENT'
    assert any(header.startswith(web_auth.SESSION_COOKIE_NAME+'=') for header in headers)
    assert instance.session()['id'] == sid
    instance.clock.now += 2*DAY
    with patch('xgent_app.web_server.SSE_HEARTBEAT_SECONDS', .01), patch('xgent_app.web_server.SSE_AUTH_RECHECK_SECONDS', .005):
        connection = http.client.HTTPConnection('127.0.0.1', instance.server._httpd.server_address[1], timeout=5)
        connection.request('GET', '/api/stream', headers={'Cookie': '; '.join(k+'='+v for k, v in instance.cookies.items())})
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader('Set-Cookie').startswith(web_auth.SESSION_COOKIE_NAME+'=')
        assert response.readline().startswith(b'event: ready')
        saved = instance.session()
        instance.clock.now += 2*DAY
        time.sleep(.08)
        assert instance.session()['last_seen'] == saved['last_seen']
        assert instance.session()['expires_at'] == saved['expires_at']
        response.close()
        connection.close()


def test_logout_and_password_change_invalidate_previously_renewed_cookies(renewal_instance):
    instance = renewal_instance
    instance.login()
    original = dict(instance.cookies)
    instance.clock.now += 3*DAY
    assert instance.request('/api/session')[1]['authenticated']
    renewed = dict(instance.cookies)
    _, _, headers = instance.request('/api/logout', {})
    assert sum(header.startswith(web_auth.SESSION_COOKIE_NAME+'=') for header in headers) == 1
    assert any('Max-Age=0' in header for header in headers)
    for jar in (original, renewed):
        assert not instance.request('/api/session', jar=jar)[1]['authenticated']
    instance.login()
    instance.clock.now += 2*DAY
    assert instance.request('/api/session')[1]['authenticated']
    instance.run(instance.db.set(PASSWORD_KEY, web_auth.hash_password('changed-password')))
    instance.restart()
    assert not instance.request('/api/session')[1]['authenticated']
