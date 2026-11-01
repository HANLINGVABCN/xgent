"""Optional TOTP for Web password login; no chat/model records or Bot gating."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import re
import secrets
import struct
import time
from urllib.parse import quote

from . import web_auth

CONFIG_KEY = 'web_two_factor_secret'
PASSWORD_KEY = 'web_password_hash'
STEP_SECONDS = 30
CHALLENGE_TTL = 300
FACTOR_ACCOUNT = 'web-factor-account'
_MISSING = object()


class TwoFactorError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def totp(secret, counter, digits=6):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack('>Q', int(counter)), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff
    return str(value % (10 ** digits)).zfill(digits)


def matching_counter(secret, code, now=None):
    if not isinstance(code, str) or not re.fullmatch('[0-9]{6}', code):
        return None
    current = int(time.time() if now is None else now) // STEP_SECONDS
    for counter in (current, current - 1, current + 1):
        if counter >= 0 and hmac.compare_digest(totp(secret, counter), code):
            return counter
    return None


def recovery_hash(code):
    value = re.sub(r'[\s-]', '', str(code or '')).upper()
    return hashlib.sha256(('XGent recovery\0' + value).encode()).hexdigest()


def new_recovery_codes():
    codes = []
    while len(codes) < 10:
        code = '-'.join(re.findall('.{4}', secrets.token_hex(10).upper()))
        if code not in codes:
            codes.append(code)
    return codes


def qr_data_url(uri):
    import qrcode
    buffer = io.BytesIO()
    qrcode.make(uri).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


class WebTwoFactor:
    def __init__(self, database):
        self.database = database
        self.pending = {}
        self.challenges = {}
        self.limiter = web_auth.LoginRateLimiter()

    def _prune(self):
        now = time.monotonic()
        for store in (self.pending, self.challenges):
            for key in list(store):
                if store[key]['expires'] <= now:
                    store.pop(key, None)
            while len(store) >= 128:
                store.pop(next(iter(store)))

    @staticmethod
    def _state(value):
        if value is _MISSING:
            return {'version': 1, 'enabled': False, 'auth_version': ''}
        if (not isinstance(value, dict) or value.get('version') != 1 or type(value.get('enabled')) is not bool
                or not isinstance(value.get('auth_version'), str)):
            raise TwoFactorError('两步验证配置异常，请通过本地管理工具恢复', 503)
        if value['enabled']:
            if (not isinstance(value.get('secret'), str) or not re.fullmatch('[A-Z2-7]{32}', value['secret'])
                    or not re.fullmatch('[a-f0-9]{32}', value['auth_version'])
                    or not isinstance(value.get('recovery_hashes'), list)
                    or not all(isinstance(code, str) and re.fullmatch('[a-f0-9]{64}', code) for code in value['recovery_hashes'])
                    or len(value['recovery_hashes']) != len(set(value['recovery_hashes']))
                    or type(value.get('last_counter')) is not int or value['last_counter'] < 0):
                raise TwoFactorError('两步验证配置异常，请通过本地管理工具恢复', 503)
        return dict(value)

    async def _load(self):
        db = await self.database()
        return db, self._state(await db.get_config_fresh(CONFIG_KEY, _MISSING))

    @staticmethod
    async def _write(conn, state):
        await conn.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)',
                           (CONFIG_KEY, json.dumps(state, ensure_ascii=False)))

    @staticmethod
    async def _transaction_state(conn):
        row = await (await conn.execute('SELECT value FROM config WHERE key=?', (CONFIG_KEY,))).fetchone()
        try:
            value = json.loads(row['value']) if row else _MISSING
        except (ValueError, TypeError) as exc:
            raise TwoFactorError('两步验证配置异常，请通过本地管理工具恢复', 503) from exc
        return WebTwoFactor._state(value)

    @staticmethod
    async def _password_fingerprint(conn):
        row = await (await conn.execute('SELECT value FROM config WHERE key=?', (PASSWORD_KEY,))).fetchone()
        try:
            stored = json.loads(row['value']) if row else ''
        except (ValueError, TypeError) as exc:
            raise TwoFactorError('访问密码配置异常', 503) from exc
        if not isinstance(stored, str):
            raise TwoFactorError('访问密码配置异常', 503)
        return hashlib.sha256(stored.encode()).hexdigest()

    async def _password(self, db, password, owner):
        if self.limiter.is_locked(owner):
            raise TwoFactorError('尝试次数过多，请稍后再试', 429)
        stored = await db.get_config_fresh(PASSWORD_KEY, '')
        if not await asyncio.to_thread(web_auth.verify_password, str(password or ''), stored):
            self.limiter.record_failure(owner)
            raise TwoFactorError('当前访问密码不正确')
        return hashlib.sha256(stored.encode()).hexdigest()

    def _factor(self, state, code, owner):
        if self.limiter.is_locked(owner) or self.limiter.is_locked(FACTOR_ACCOUNT):
            raise TwoFactorError('尝试次数过多，请稍后再试', 429)
        code = str(code or '').strip()
        counter = matching_counter(state['secret'], code)
        if counter is not None:
            if counter <= state['last_counter']:
                self.limiter.record_failure(owner)
                self.limiter.record_failure(FACTOR_ACCOUNT)
                raise TwoFactorError('这个验证码已使用，请等待验证器显示下一码')
            state['last_counter'] = counter
            return
        digest = recovery_hash(code)
        found = next((index for index, saved in enumerate(state['recovery_hashes'])
                      if isinstance(saved, str) and hmac.compare_digest(saved, digest)), None)
        if found is None:
            self.limiter.record_failure(owner)
            self.limiter.record_failure(FACTOR_ACCOUNT)
            raise TwoFactorError('动态验证码或恢复码不正确')
        state['recovery_hashes'] = [value for index, value in enumerate(state['recovery_hashes']) if index != found]

    async def handle(self, method, action, data, owner=''):
        self._prune()
        db, state = await self._load()
        if method == 'GET':
            if action == 'policy':
                return {'enabled': state['enabled'], 'auth_version': state['auth_version']}
            if action == 'status':
                return {'enabled': state['enabled'], 'recovery_remaining': len(state.get('recovery_hashes', []))}
        if action == 'login_start':
            if not state['enabled']:
                return {'requires_2fa': False, '_auth_version': state['auth_version']}
            if self.limiter.is_locked(FACTOR_ACCOUNT):
                raise TwoFactorError('验证码尝试次数过多，请稍后再试', 429)
            stored = await db.get_config_fresh(PASSWORD_KEY, '')
            if stored != data.get('password_hash'):
                raise TwoFactorError('访问密码已更新，请重新登录', 409)
            challenge = secrets.token_urlsafe(24)
            self.challenges[challenge] = {'owner': owner, 'expires': time.monotonic() + CHALLENGE_TTL,
                'auth_version': state['auth_version'], 'password_hash': hashlib.sha256(stored.encode()).hexdigest(), 'attempts': 0}
            return {'requires_2fa': True, 'challenge_id': challenge, 'expires_in': CHALLENGE_TTL}
        if action == 'login_finish':
            key = str(data.get('challenge_id') or '')
            entry = self.challenges.get(key)
            if entry is None or entry['owner'] != owner:
                raise TwoFactorError('验证流程已过期，请重新输入密码', 410)
            stored = await db.get_config_fresh(PASSWORD_KEY, '')
            if entry['password_hash'] != hashlib.sha256(stored.encode()).hexdigest():
                self.challenges.pop(key, None)
                raise TwoFactorError('访问密码已更新，请重新登录', 410)
            entry['attempts'] += 1
            try:
                async with db._transaction() as conn:
                    if self.challenges.get(key) is not entry:
                        raise TwoFactorError('验证流程已使用，请重新登录', 410)
                    if await self._password_fingerprint(conn) != entry['password_hash']:
                        raise TwoFactorError('访问密码已更新，请重新登录', 410)
                    state = await self._transaction_state(conn)
                    if not state['enabled'] or state['auth_version'] != entry['auth_version']:
                        raise TwoFactorError('两步验证设置已更新，请重新登录', 410)
                    self._factor(state, data.get('code'), owner)
                    await self._write(conn, state)
            except TwoFactorError:
                if entry['attempts'] >= 5:
                    self.challenges.pop(key, None)
                raise
            self.challenges.pop(key, None)
            self.limiter.record_success(owner)
            self.limiter.record_success(FACTOR_ACCOUNT)
            return {'ok': True, '_auth_version': state['auth_version']}
        if action == 'setup':
            if state['enabled']:
                raise TwoFactorError('两步验证已启用', 409)
            fingerprint = await self._password(db, data.get('password'), owner)
            secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
            setup = secrets.token_urlsafe(24)
            self.pending[setup] = {'owner': owner, 'secret': secret, 'auth_version': state['auth_version'],
                'password_hash': fingerprint, 'expires': time.monotonic() + CHALLENGE_TTL, 'attempts': 0}
            uri = 'otpauth://totp/' + quote('XGent:Web', safe='') + '?secret=' + secret + '&issuer=XGent&algorithm=SHA1&digits=6&period=30'
            return {'setup_id': setup, 'secret': secret, 'qr': await asyncio.to_thread(qr_data_url, uri),
                    'expires_in': CHALLENGE_TTL}
        if action == 'confirm':
            key = str(data.get('setup_id') or '')
            entry = self.pending.get(key)
            if entry is None or entry['owner'] != owner:
                raise TwoFactorError('绑定信息已过期，请重新添加', 410)
            if state['enabled'] or state['auth_version'] != entry['auth_version']:
                raise TwoFactorError('安全设置已更新，请重新添加', 409)
            stored = await db.get_config_fresh(PASSWORD_KEY, '')
            if hashlib.sha256(stored.encode()).hexdigest() != entry['password_hash']:
                raise TwoFactorError('访问密码已更新，请重新添加', 410)
            entry['attempts'] += 1
            counter = matching_counter(entry['secret'], str(data.get('code') or '').strip())
            if counter is None:
                if entry['attempts'] >= 5:
                    self.pending.pop(key, None)
                raise TwoFactorError('验证码不正确，尚未启用两步验证')
            codes = new_recovery_codes()
            auth_version = secrets.token_hex(16)
            async with db._transaction() as conn:
                if await self._password_fingerprint(conn) != entry['password_hash']:
                    raise TwoFactorError('访问密码已更新，请重新添加', 410)
                current = await self._transaction_state(conn)
                if current['enabled'] or current['auth_version'] != entry['auth_version']:
                    raise TwoFactorError('安全设置已更新，请重新添加', 409)
                await self._write(conn, {'version': 1, 'enabled': True, 'secret': entry['secret'],
                    'recovery_hashes': [recovery_hash(code) for code in codes], 'last_counter': counter,
                    'auth_version': auth_version})
            self.pending.pop(key, None)
            self.limiter.record_success(owner)
            self.limiter.record_success(FACTOR_ACCOUNT)
            return {'ok': True, 'enabled': True, 'recovery_codes': codes, '_auth_version': auth_version}
        if action in {'disable', 'recovery'}:
            fingerprint = await self._password(db, data.get('password'), owner)
            codes = new_recovery_codes() if action == 'recovery' else []
            async with db._transaction() as conn:
                if await self._password_fingerprint(conn) != fingerprint:
                    raise TwoFactorError('访问密码已更新，请重新验证', 409)
                state = await self._transaction_state(conn)
                if not state['enabled']:
                    raise TwoFactorError('尚未启用两步验证', 409)
                self._factor(state, data.get('code'), owner)
                if action == 'disable':
                    state = {'version': 1, 'enabled': False, 'auth_version': secrets.token_hex(16)}
                else:
                    state.update(recovery_hashes=[recovery_hash(code) for code in codes], auth_version=secrets.token_hex(16))
                await self._write(conn, state)
            self.limiter.record_success(owner)
            self.limiter.record_success(FACTOR_ACCOUNT)
            return {'ok': True, 'enabled': state['enabled'], '_auth_version': state['auth_version'],
                    **({'recovery_codes': codes} if codes else {})}
        raise TwoFactorError('未知的两步验证操作', 404)

    async def reset_local(self):
        db = await self.database()
        async with db._transaction() as conn:
            await self._write(conn, {'version': 1, 'enabled': False, 'auth_version': secrets.token_hex(16)})
        self.pending.clear()
        self.challenges.clear()
