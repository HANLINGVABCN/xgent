import asyncio
import base64
import contextlib
import hashlib
import hmac
import http.client
import json
import threading
import time
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

import aiosqlite

from xgent_app import web_auth
from xgent_app.web_server import WebChatConfig, WebChatServer
from xgent_app.web_two_factor import CONFIG_KEY, PASSWORD_KEY, WebTwoFactor, TwoFactorError, matching_counter, totp


class Database:
    async def open(self):
        self.connection = await aiosqlite.connect(':memory:', isolation_level=None)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute('CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        self.lock = asyncio.Lock()
        await self.set(PASSWORD_KEY, web_auth.hash_password('test-password'))
        return self

    async def set(self, key, value):
        await self.connection.execute('INSERT OR REPLACE INTO config VALUES(?,?)', (key, json.dumps(value)))

    async def get_config_fresh(self, key, default=None):
        row = await (await self.connection.execute('SELECT value FROM config WHERE key=?', (key,))).fetchone()
        return json.loads(row['value']) if row else default

    @contextlib.asynccontextmanager
    async def _transaction(self):
        async with self.lock:
            await self.connection.execute('BEGIN IMMEDIATE')
            try:
                yield self.connection
                await self.connection.commit()
            except BaseException:
                await self.connection.rollback()
                raise

    async def close(self):
        await self.connection.close()


class FactorUnitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await Database().open()
        async def database():
            return self.db
        self.service = WebTwoFactor(database)
        self.now = 1700000010
        self.clock = patch('xgent_app.web_two_factor.time.time', side_effect=lambda: self.now)
        self.clock.start()

    async def asyncTearDown(self):
        self.clock.stop()
        await self.db.close()

    async def enable(self):
        binding = await self.service.handle('POST', 'setup', {'password': 'test-password'}, 'owner')
        result = await self.service.handle('POST', 'confirm', {'setup_id': binding['setup_id'],
            'code': totp(binding['secret'], self.now // 30)}, 'owner')
        return binding, result

    async def test_enrollment_requires_password_and_code_and_does_not_leak_private_fields(self):
        with self.assertRaises(TwoFactorError):
            await self.service.handle('POST', 'setup', {'password': 'wrong'}, 'owner')
        binding = await self.service.handle('POST', 'setup', {'password': 'test-password'}, 'owner')
        self.assertTrue(binding['qr'].startswith('data:image/png;base64,'))
        self.assertFalse((await self.service.handle('GET', 'status', {}))['enabled'])
        with self.assertRaises(TwoFactorError):
            await self.service.handle('POST', 'confirm', {'setup_id': binding['setup_id'], 'code': 'bad'}, 'owner')
        result = await self.service.handle('POST', 'confirm', {'setup_id': binding['setup_id'],
            'code': totp(binding['secret'], self.now // 30)}, 'owner')
        self.assertEqual(10, len(result['recovery_codes']))
        status = await self.service.handle('GET', 'status', {})
        self.assertEqual({'enabled': True, 'recovery_remaining': 10}, status)
        stored = await self.db.get_config_fresh(CONFIG_KEY)
        self.assertNotIn(result['recovery_codes'][0], json.dumps(stored))
        self.assertNotIn(binding['secret'], json.dumps(status))

    async def test_login_challenge_is_bound_and_totp_cannot_be_replayed(self):
        binding, _ = await self.enable()
        start = await self.service.handle('POST', 'login_start', {'password_hash': await self.db.get_config_fresh(PASSWORD_KEY)}, 'ip')
        self.now += 30
        code = totp(binding['secret'], self.now // 30)
        with self.assertRaises(TwoFactorError):
            await self.service.handle('POST', 'login_finish', {'challenge_id': start['challenge_id'], 'code': code}, 'different-ip')
        await self.service.handle('POST', 'login_finish', {'challenge_id': start['challenge_id'], 'code': code}, 'ip')
        with self.assertRaises(TwoFactorError):
            await self.service.handle('POST', 'login_finish', {'challenge_id': start['challenge_id'], 'code': code}, 'ip')
        next_start = await self.service.handle('POST', 'login_start', {'password_hash': await self.db.get_config_fresh(PASSWORD_KEY)}, 'ip')
        with self.assertRaisesRegex(TwoFactorError, '已使用'):
            await self.service.handle('POST', 'login_finish', {'challenge_id': next_start['challenge_id'], 'code': code}, 'ip')

    async def test_recovery_code_is_one_use_and_disable_requires_current_credentials(self):
        _, enabled = await self.enable()
        begin = {'password_hash': await self.db.get_config_fresh(PASSWORD_KEY)}
        start = await self.service.handle('POST', 'login_start', begin, 'ip')
        code = enabled['recovery_codes'][0]
        await self.service.handle('POST', 'login_finish', {'challenge_id': start['challenge_id'], 'code': code}, 'ip')
        self.assertEqual(9, (await self.service.handle('GET', 'status', {}))['recovery_remaining'])
        next_start = await self.service.handle('POST', 'login_start', begin, 'ip')
        with self.assertRaises(TwoFactorError):
            await self.service.handle('POST', 'login_finish', {'challenge_id': next_start['challenge_id'], 'code': code}, 'ip')
        with self.assertRaises(TwoFactorError):
            await self.service.handle('POST', 'disable', {'password': 'wrong', 'code': enabled['recovery_codes'][1]}, 'owner')
        await self.service.handle('POST', 'disable', {'password': 'test-password', 'code': enabled['recovery_codes'][1]}, 'owner')
        stored = await self.db.get_config_fresh(CONFIG_KEY)
        self.assertFalse(stored['enabled'])
        self.assertNotIn('secret', stored)

    async def test_changed_password_expiration_and_restart_invalidate_pending_challenges(self):
        await self.enable()
        start = await self.service.handle('POST', 'login_start', {'password_hash': await self.db.get_config_fresh(PASSWORD_KEY)}, 'ip')
        await self.db.set(PASSWORD_KEY, web_auth.hash_password('changed-password'))
        with self.assertRaisesRegex(TwoFactorError, '密码已更新'):
            await self.service.handle('POST', 'login_finish', {'challenge_id': start['challenge_id'], 'code': '123456'}, 'ip')
        start = await self.service.handle('POST', 'login_start', {'password_hash': await self.db.get_config_fresh(PASSWORD_KEY)}, 'ip')
        self.service.challenges[start['challenge_id']]['expires'] = time.monotonic() - 1
        with self.assertRaisesRegex(TwoFactorError, '过期'):
            await self.service.handle('POST', 'login_finish', {'challenge_id': start['challenge_id'], 'code': '123456'}, 'ip')
        restarted = WebTwoFactor(self.service.database)
        self.assertTrue((await restarted.handle('GET', 'status', {}))['enabled'])

    async def test_malformed_configuration_fails_closed_and_local_reset_recovers(self):
        await self.db.set(CONFIG_KEY, {'enabled': True})
        with self.assertRaises(TwoFactorError):
            await self.service.handle('GET', 'policy', {})
        await self.service.reset_local()
        self.assertFalse((await self.service.handle('GET', 'status', {}))['enabled'])

    async def test_empty_active_auth_version_cannot_accept_old_password_only_cookie(self):
        await self.enable()
        stored = await self.db.get_config_fresh(CONFIG_KEY)
        stored['auth_version'] = ''
        await self.db.set(CONFIG_KEY, stored)
        with self.assertRaises(TwoFactorError):
            await self.service.handle('GET', 'policy', {})

    async def test_persisted_null_is_not_treated_as_missing_disabled_configuration(self):
        await self.db.set(CONFIG_KEY, None)
        with self.assertRaises(TwoFactorError) as rejected:
            await self.service.handle('GET', 'policy', {})
        self.assertEqual(503, rejected.exception.status)
        await self.service.reset_local()
        self.assertFalse((await self.service.handle('GET', 'status', {}))['enabled'])

    async def test_regenerated_codes_invalidate_old_codes_and_remain_hashed(self):
        binding, enabled = await self.enable()
        self.now += 30
        updated = await self.service.handle('POST', 'recovery', {'password': 'test-password',
            'code': totp(binding['secret'], self.now // 30)}, 'owner')
        stored = await self.db.get_config_fresh(CONFIG_KEY)
        self.assertNotEqual(enabled['recovery_codes'], updated['recovery_codes'])
        self.assertNotIn(updated['recovery_codes'][0], json.dumps(stored))
        start = await self.service.handle('POST', 'login_start', {'password_hash': await self.db.get_config_fresh(PASSWORD_KEY)}, 'ip')
        with self.assertRaises(TwoFactorError):
            await self.service.handle('POST', 'login_finish', {'challenge_id': start['challenge_id'], 'code': enabled['recovery_codes'][0]}, 'ip')
        await self.service.handle('POST', 'login_finish', {'challenge_id': start['challenge_id'], 'code': updated['recovery_codes'][0]}, 'ip')

    async def test_parallel_recovery_submissions_cannot_reuse_a_challenge(self):
        _, enabled = await self.enable()
        start = await self.service.handle('POST', 'login_start', {'password_hash': await self.db.get_config_fresh(PASSWORD_KEY)}, 'ip')
        results = await asyncio.gather(*(self.service.handle('POST', 'login_finish',
            {'challenge_id': start['challenge_id'], 'code': code}, 'ip') for code in enabled['recovery_codes'][:2]), return_exceptions=True)
        self.assertEqual(1, sum(isinstance(result, dict) for result in results))
        self.assertEqual(9, (await self.service.handle('GET', 'status', {}))['recovery_remaining'])

    async def test_changing_ip_or_restarting_first_step_does_not_reset_factor_limit(self):
        await self.enable()
        password_hash = await self.db.get_config_fresh(PASSWORD_KEY)
        for index in range(5):
            owner = 'different-ip-' + str(index)
            start = await self.service.handle('POST', 'login_start', {'password_hash': password_hash}, owner)
            with self.assertRaises(TwoFactorError):
                await self.service.handle('POST', 'login_finish', {'challenge_id': start['challenge_id'], 'code': 'INVALID'}, owner)
        with self.assertRaises(TwoFactorError) as rejected:
            await self.service.handle('POST', 'login_start', {'password_hash': password_hash}, 'new-ip')
        self.assertEqual(429, rejected.exception.status)
        self.now += 61
        self.assertTrue((await self.service.handle('POST', 'login_start', {'password_hash': password_hash}, 'new-ip'))['requires_2fa'])


class TotpVectors(unittest.TestCase):
    def test_rfc6238_sha1_vectors(self):
        secret = base64.b32encode(b'12345678901234567890').decode().rstrip('=')
        for stamp, expected in [(59, '94287082'), (1111111109, '07081804'), (1111111111, '14050471'),
                                (1234567890, '89005924'), (2000000000, '69279037'), (20000000000, '65353130')]:
            self.assertEqual(expected, totp(secret, stamp // 30, digits=8))
        self.assertIsNone(matching_counter(secret, '12345', now=59))


class FactorHttpTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.db = self.run_async(self.initialize())
        async def database():
            return self.db
        self.service = WebTwoFactor(database)
        self.password_hash = self.run_async(self.db.get_config_fresh(PASSWORD_KEY))
        async def empty(*args):
            return []
        self.server = WebChatServer(WebChatConfig(host='127.0.0.1', port=0, password_hash=self.password_hash,
            bot_token='fixture-bot-token', authorized_user_id=1, loop=self.loop, submit_message=empty,
            read_history=empty, read_settings=empty, write_setting=empty, request_stop=lambda: None, is_busy=lambda: False,
            security_api=self.service.handle))
        self.server.start()

    async def initialize(self):
        return await Database().open()

    def run_async(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(10)

    def tearDown(self):
        self.server.stop()
        self.run_async(self.db.close())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()

    def request(self, path, data=None, cookie=None, origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server._httpd.server_address[1], timeout=10)
        headers = {'Content-Type': 'application/json'}
        if cookie: headers['Cookie'] = cookie
        if origin: headers['Origin'] = origin
        connection.request('POST' if data is not None else 'GET', path, None if data is None else json.dumps(data), headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), response.getheader('Set-Cookie')
        connection.close()
        return result

    def enable(self):
        _, _, old_cookie = self.request('/api/login', {'password': 'test-password'})
        status, setup, _ = self.request('/api/security/2fa/setup', {'password': 'test-password'}, old_cookie)
        self.assertEqual(200, status)
        status, enabled, cookie = self.request('/api/security/2fa/confirm', {'setup_id': setup['setup_id'],
            'code': totp(setup['secret'], int(time.time()) // 30)}, old_cookie)
        self.assertEqual(200, status)
        return old_cookie, cookie, enabled

    def test_password_first_step_has_no_cookie_and_old_sessions_are_revoked(self):
        old, current, enabled = self.enable()
        self.assertFalse(self.request('/api/session', cookie=old)[1]['authenticated'])
        self.assertTrue(self.request('/api/session', cookie=current)[1]['authenticated'])
        status, first, cookie = self.request('/api/login', {'password': 'test-password', 'telegram': True})
        self.assertEqual(200, status)
        self.assertTrue(first['requires_2fa'])
        self.assertIsNone(cookie)
        self.assertEqual(401, self.request('/api/security/2fa')[0])
        self.assertEqual(400, self.request('/api/login', {'challenge_id': first['challenge_id'], 'code': 'INVALID'})[0])
        status, _, cookie = self.request('/api/login', {'challenge_id': first['challenge_id'], 'code': enabled['recovery_codes'][0]})
        self.assertEqual(200, status)
        self.assertTrue(self.request('/api/session', cookie=cookie)[1]['authenticated'])

    def test_telegram_signed_identity_remains_exempt_and_cross_site_changes_are_denied(self):
        _, cookie, _ = self.enable()
        values = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': 1})}
        secret = hmac.new(b'WebAppData', b'fixture-bot-token', hashlib.sha256).digest()
        values['hash'] = hmac.new(secret, '\n'.join(f'{key}={values[key]}' for key in sorted(values)).encode(), hashlib.sha256).hexdigest()
        status, result, signed_cookie = self.request('/api/login', {'init_data': urlencode(values)})
        self.assertEqual(200, status)
        self.assertNotIn('requires_2fa', result)
        self.assertTrue(self.request('/api/session', cookie=signed_cookie)[1]['authenticated'])
        self.assertEqual(403, self.request('/api/security/2fa/disable', {'password': 'test-password'}, cookie, 'https://evil.example')[0])
        status, public, _ = self.request('/api/security/2fa', cookie=cookie)
        self.assertEqual({'enabled': True, 'recovery_remaining': 10}, public)

    def test_second_step_cannot_access_management_or_terminal_with_password_alone(self):
        self.enable()
        status, pending, cookie = self.request('/api/login', {'password': 'test-password'})
        self.assertEqual(200, status)
        self.assertIsNone(cookie)
        self.assertTrue(pending['requires_2fa'])
        self.assertEqual(401, self.request('/api/term/sessions')[0])
        self.assertEqual(401, self.request('/api/security/2fa/setup', {'password': 'test-password'})[0])
        self.assertEqual(404, self.request('/api/security/2fa/policy')[0])


class SecurityPartitionTests(unittest.TestCase):
    def test_factor_configuration_belongs_only_to_private_credentials(self):
        from xgent_app.data_parts import config_part
        self.assertEqual('secrets', config_part(CONFIG_KEY))
