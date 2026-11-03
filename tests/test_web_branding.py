"""Branding is an atomic public appearance config, never a model instruction."""
import base64
from copy import deepcopy
import http.client
import json
import unittest

from tests import test_conversations as base_tests
from tests.test_full_output_web import full_output_server  # noqa: F401
from xgent_app.web_appearance import read_appearance, write_appearance
from xgent_app.web_branding import BRANDING_KEY, DEFAULT_BRANDING, MAX_IMAGE_BYTES, read_branding, validate_branding, delete_avatar


class BrandingConfigTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base_tests.ConversationTests.asyncSetUp
    asyncTearDown = base_tests.ConversationTests.asyncTearDown

    async def test_default_atomic_save_restart_and_shared_revision(self):
        before = await read_branding(self.db)
        self.assertEqual(DEFAULT_BRANDING, before['branding'])
        value = {**DEFAULT_BRANDING, 'name': '自定义 <名字>', 'mode': 'custom',
                 'source': '<div style="color:cyan">LOGO</div>'}
        saved = await write_appearance(self.db, BRANDING_KEY, value)
        self.assertGreater(saved['revision'], before['revision'])
        self.assertEqual(value, saved['values'][BRANDING_KEY])
        self.assertEqual(value, await self.db.get_config_fresh(BRANDING_KEY))
        await self.db.close()
        await self.db._init_db()
        self.assertEqual(value, (await read_branding(self.db))['branding'])
        fonts = await write_appearance(self.db, 'web_ui_font_size', 18)
        self.assertEqual(value, fonts['values'][BRANDING_KEY])
        self.assertEqual(18, (await read_appearance(self.db))['values']['web_ui_font_size'])

    async def test_invalid_save_keeps_whole_previous_brand_and_revision(self):
        saved = await write_appearance(self.db, BRANDING_KEY, {**DEFAULT_BRANDING, 'preset': '4-D'})
        for update in ({'name': ''}, {'name': 'x'*81}, {'mode': 'other'}, {'preset': '4-Z'},
                       {'mode': 'upload', 'source': 'https://example.invalid/image.png'},
                       {'mode': 'custom', 'source': 'javascript:alert(1)'}, {'version': True}):
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    await write_appearance(self.db, BRANDING_KEY, {**DEFAULT_BRANDING, **update})
                self.assertEqual(saved, await read_appearance(self.db))

    async def test_image_code_limits_and_canonical_presets(self):
        for source in ('https://images.example/avatar.png', 'http://images.example/avatar.webp',
                       'data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22/%3E',
                       '<svg viewBox="0 0 32 32"><path d="M1 1L2 2"/></svg>', ''):
            self.assertEqual(source, validate_branding({**DEFAULT_BRANDING, 'mode': 'custom', 'source': source})['source'])
        self.assertEqual('', validate_branding({**DEFAULT_BRANDING, 'source': '<script>ignored preset override</script>'})['source'])
        large = 'data:image/png;base64,' + base64.b64encode(b'x'*(1024*1024+10)).decode()
        saved = await write_appearance(self.db, BRANDING_KEY, {**DEFAULT_BRANDING, 'mode': 'upload', 'source': large})
        self.assertEqual(large, saved['values'][BRANDING_KEY]['source'])
        for source in ('data:image/png;base64,broken!', 'data:image/png;base64,',
                       'data:image/png;base64,' + base64.b64encode(b'x'*(MAX_IMAGE_BYTES+1)).decode(),
                       '<div>' + 'x'*65536 + '</div>'):
            with self.assertRaises(ValueError):
                validate_branding({**DEFAULT_BRANDING, 'mode': 'custom', 'source': source})

    async def test_saved_avatar_library_selection_name_and_invalid_relation(self):
        avatar = {'id': 'my-avatar', 'name': '名字', 'mode': 'custom', 'source': '<div>SVG or HTML</div>'}
        value = {**DEFAULT_BRANDING, 'mode': 'custom', 'avatar_id': avatar['id'], 'avatars': [avatar]}
        saved = await write_appearance(self.db, BRANDING_KEY, value)
        self.assertEqual(value, saved['values'][BRANDING_KEY])
        await self.db.close()
        await self.db._init_db()
        self.assertEqual(value, (await read_branding(self.db))['branding'])
        renamed = {**value, 'avatars': [{**avatar, 'name': '改名'}]}
        after = await write_appearance(self.db, BRANDING_KEY, renamed)
        self.assertEqual('改名', after['values'][BRANDING_KEY]['avatars'][0]['name'])
        for invalid in ({**value, 'avatar_id': 'missing'}, {**value, 'avatars': [avatar, avatar]},
                        {**value, 'avatars': [{**avatar, 'name': ''}]}):
            with self.assertRaises(ValueError):
                await write_appearance(self.db, BRANDING_KEY, invalid)
            self.assertEqual(after, await read_appearance(self.db))

    async def test_deletion_only_removes_selected_id_and_is_idempotent(self):
        first = {'id': 'first', 'name': '第一个', 'mode': 'custom', 'source': '<div>first</div>'}
        active = {'id': 'active', 'name': '当前', 'mode': 'custom', 'source': '<svg/>'}
        value = {**DEFAULT_BRANDING, 'name': '系统名保留', 'mode': 'custom', 'avatar_id': 'active', 'avatars': [first, active]}
        await write_appearance(self.db, BRANDING_KEY, value)
        removed = await delete_avatar(self.db, 'first')
        self.assertEqual([active], removed['values'][BRANDING_KEY]['avatars'])
        self.assertEqual('active', removed['values'][BRANDING_KEY]['avatar_id'])
        self.assertEqual(removed, await delete_avatar(self.db, 'first'))
        with self.assertRaises(ValueError):
            await delete_avatar(self.db, '4-B')
        self.assertEqual(removed, await read_appearance(self.db))
        empty = (await delete_avatar(self.db, 'active'))['values'][BRANDING_KEY]
        self.assertEqual({**DEFAULT_BRANDING, 'name': '系统名保留'}, empty)


def request(server, method, path, payload=None, cookie=''):
    client = http.client.HTTPConnection('127.0.0.1', server.config.port, timeout=8)
    headers = {'Content-Type': 'application/json', 'Cookie': cookie}
    try:
        client.request(method, path, json.dumps(payload) if payload is not None else None, headers)
        response = client.getresponse()
        body = response.read()
        return response.status, dict(response.getheaders()), body
    finally:
        client.close()


def test_login_branding_exposes_only_public_fields_and_writes_still_need_auth(full_output_server):
    server = full_output_server[0]

    async def branding():
        return {'revision': 8, 'branding': {**DEFAULT_BRANDING, 'name': 'Public name', 'bot_token': 'NEVER_EXPOSE'},
                'api_key': 'NEVER_EXPOSE', 'providers': {'secret': 'NEVER_EXPOSE'}}

    server.config.read_branding = branding
    status, headers, body = request(server, 'GET', '/api/branding')
    assert status == 200 and 'no-store' in headers['Cache-Control']
    value = json.loads(body)
    assert value == {'revision': 8, 'branding': {**DEFAULT_BRANDING, 'name': 'Public name'}}
    assert b'NEVER_EXPOSE' not in body
    assert json.loads(request(server, 'GET', '/api/branding?revision=8')[2]) == {'revision': 8, 'unchanged': True}
    assert request(server, 'GET', '/api/config')[0] == 401
    assert request(server, 'POST', '/api/config', {'key': BRANDING_KEY, 'value': DEFAULT_BRANDING})[0] == 401
    svg = request(server, 'GET', '/assets/logo.svg')
    assert svg[0] == 200 and svg[1]['Content-Type'] == 'image/svg+xml'
    assert b'M7.5 7.5L16 16L7.5 24.5' in svg[2]


def test_authenticated_config_accepts_image_larger_than_old_json_budget(full_output_server):
    server = full_output_server[0]
    status, headers, _ = request(server, 'POST', '/api/login', {'password': 'temporary-test-only'})
    assert status == 200
    cookie = headers['Set-Cookie'].split(';')[0]
    seen = []

    async def write(key, value):
        assert key == BRANDING_KEY
        seen.append(validate_branding(value))
        return {'revision': 1, 'values': {BRANDING_KEY: seen[-1]}}

    server.config.write_setting = write
    source = 'data:image/png;base64,' + base64.b64encode(b'x'*(1024*1024+10)).decode()
    value = {**deepcopy(DEFAULT_BRANDING), 'mode': 'upload', 'source': source}
    result = request(server, 'POST', '/api/config', {'key': BRANDING_KEY, 'value': value}, cookie)
    assert result[0] == 200 and seen == [value]


def test_public_login_omits_unused_avatar_library(full_output_server):
    server = full_output_server[0]
    value = {**DEFAULT_BRANDING, 'mode': 'custom', 'avatar_id': 'active', 'avatars': [
        {'id': 'active', 'name': '当前', 'mode': 'custom', 'source': '<svg viewBox="0 0 32 32"/>'},
        {'id': 'unused', 'name': 'UNUSED_PRIVATE_AVATAR', 'mode': 'custom', 'source': '<div>UNUSED_PRIVATE_AVATAR</div>'}]}

    async def branding():
        return {'revision': 1, 'branding': value}

    server.config.read_branding = branding
    public = request(server, 'GET', '/api/branding')
    assert public[0] == 200 and b'UNUSED_PRIVATE_AVATAR' not in public[2]
    assert json.loads(public[2])['branding']['source'] == '<svg viewBox="0 0 32 32"/>'
    _, headers, _ = request(server, 'POST', '/api/login', {'password': 'temporary-test-only'})
    private = request(server, 'GET', '/api/branding', cookie=headers['Set-Cookie'].split(';')[0])
    assert json.loads(private[2])['branding'] == value
