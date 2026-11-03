"""Public Web appearance only; credentials and model identity stay separate."""
from copy import deepcopy
import base64
import binascii
import json
import re
from urllib.parse import unquote_to_bytes, urlsplit

BRANDING_KEY = 'web_branding'
BRANDING_DELETE_KEY = 'web_branding_delete_avatar'
PRESET_IDS = ('4-A', '4-B', '4-C', '4-D', '4-E', '4-F')
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_CODE_CHARS = 64 * 1024
MAX_SOURCE_CHARS = (MAX_IMAGE_BYTES + 2) // 3 * 4 + 4096
MAX_LIBRARY_SOURCE_CHARS = 24 * 1024 * 1024
MAX_BRANDING_REQUEST = 32 * 1024 * 1024
DEFAULT_BRANDING = {'version': 1, 'name': 'XGent', 'mode': 'preset', 'preset': '4-B', 'source': '',
                    'avatar_id': '', 'avatars': []}


def validate_logo_source(source, mode):
    if not isinstance(source, str) or len(source) > MAX_SOURCE_CHARS:
        raise ValueError('Logo 内容过大，图片最多支持 8 MB。')
    source = source.strip()
    if mode == 'preset':
        source = ''
    elif source:
        if re.match(r'^https?://', source, re.I):
            try:
                valid_url = bool(urlsplit(source).hostname) and not re.search(r'\s', source)
            except ValueError:
                valid_url = False
            if not valid_url:
                raise ValueError('请输入有效的 HTTP 或 HTTPS 图片地址。')
        elif source.lower().startswith('data:image/'):
            header, separator, body = source.partition(',')
            if not separator or not re.fullmatch(r'data:image/[a-z0-9.+-]+(?:;[a-z0-9=.+-]+)*', header, re.I):
                raise ValueError('图片 DataURL 无效。')
            try:
                payload = (base64.b64decode(body, validate=True) if ';base64' in header.lower()
                           else unquote_to_bytes(body))
            except (ValueError, binascii.Error):
                raise ValueError('图片 Base64 编码无效。') from None
            if not payload or len(payload) > MAX_IMAGE_BYTES:
                raise ValueError('图片为空或超过 8 MB。')
        elif mode == 'upload' or not source.startswith('<'):
            raise ValueError('请输入 SVG／HTML 代码、图片网址或 data:image/ 地址。')
        elif len(source) > MAX_CODE_CHARS:
            raise ValueError('SVG／HTML 代码最多支持 65,536 个字符。')
    elif mode == 'upload':
        raise ValueError('请先选择本地图片。')
    if mode == 'upload' and not source.lower().startswith('data:image/'):
        raise ValueError('本地图片必须保存为图片 DataURL。')
    return source


def validate_branding(value):
    if not isinstance(value, dict) or type(value.get('version', 1)) is not int or value.get('version', 1) != 1:
        raise ValueError('品牌配置格式无效。')
    name = value.get('name', 'XGent')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80 or re.search(r'[\x00-\x1f\x7f]', name):
        raise ValueError('系统名称需为 1–80 个可见字符。')
    mode = value.get('mode', 'preset')
    if not isinstance(mode, str) or mode not in {'preset', 'custom', 'upload'}:
        raise ValueError('请选择预设、自定义或上传图片。')
    preset = value.get('preset', '4-B')
    if preset not in PRESET_IDS:
        raise ValueError('Logo 预设不存在。')
    items = value.get('avatars', [])
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError('头像列表无效或超过 100 项。')
    avatars, identifiers, total = [], set(), 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('保存的头像格式无效。')
        identifier, label, item_mode = item.get('id'), item.get('name'), item.get('mode', 'custom')
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', identifier) or identifier in identifiers:
            raise ValueError('头像 ID 无效或重复。')
        if identifier in PRESET_IDS or identifier == 'custom':
            raise ValueError('自定义头像 ID 不能与预设冲突。')
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 40 or re.search(r'[\x00-\x1f\x7f]', label):
            raise ValueError('头像名称需为 1–40 个可见字符。')
        if item_mode not in ('custom', 'upload'):
            raise ValueError('保存的头像类型无效。')
        source = validate_logo_source(item.get('source', ''), item_mode)
        if not source:
            raise ValueError('保存的头像内容不能为空。')
        total += len(source)
        if total > MAX_LIBRARY_SOURCE_CHARS:
            raise ValueError('头像库内容超过 24 MB。')
        identifiers.add(identifier)
        avatars.append({'id': identifier, 'name': label.strip(), 'mode': item_mode, 'source': source})
    avatar_id = value.get('avatar_id', '')
    if not isinstance(avatar_id, str):
        raise ValueError('所选头像 ID 无效。')
    if avatar_id:
        selected = next((item for item in avatars if item['id'] == avatar_id), None)
        if selected is None or mode == 'preset':
            raise ValueError('所选头像已不存在，请重新选择。')
        mode, source = selected['mode'], ''  # Keep one copy of uploaded image bytes.
    else:
        source = validate_logo_source(value.get('source', ''), mode)
        if total + len(source) > MAX_LIBRARY_SOURCE_CHARS:
            raise ValueError('头像库内容超过 24 MB。')
    return {'version': 1, 'name': name.strip(), 'mode': mode, 'preset': preset, 'source': source,
            'avatar_id': avatar_id, 'avatars': avatars}


def public_branding(value):
    """Login displays the current logo, not the owner's unused saved images."""
    public = {**value, 'avatar_id': '', 'avatars': []}
    if value['avatar_id']:
        selected = next(item for item in value['avatars'] if item['id'] == value['avatar_id'])
        public.update(mode=selected['mode'], source=selected['source'])
    return public


def saved_branding(value):
    try:
        return validate_branding(value)
    except (ValueError, TypeError):
        return deepcopy(DEFAULT_BRANDING)


async def branding_for_revision(db, conn, revision):
    """Do not reparse a multi-megabyte image on every configuration poll."""
    cached = getattr(db, '_web_branding_cache', None)
    if cached is not None and cached[0] is conn and cached[1] == revision:
        return cached[2]
    cursor = await conn.execute('SELECT value FROM config WHERE key=?', (BRANDING_KEY,))
    row = await cursor.fetchone()
    await cursor.close()
    import json
    try:
        raw = json.loads(row['value']) if row else None
    except (ValueError, TypeError):
        raw = None
    value = saved_branding(raw)
    db._web_branding_cache = (conn, revision, value)
    return value


async def read_branding(db):
    from .web_appearance import read_appearance
    appearance = await read_appearance(db)
    return {'revision': appearance['revision'], 'branding': appearance['values'][BRANDING_KEY]}


async def delete_avatar(db, identifier):
    """Delete only this saved ID against the latest config in one transaction."""
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', identifier):
        raise ValueError('头像 ID 无效。')
    if identifier in PRESET_IDS or identifier == 'custom':
        raise ValueError('默认头像不能删除。')
    changed = False
    async with db._transaction() as conn:
        cursor = await conn.execute('SELECT key,value FROM config WHERE key IN (?,?)',
                                    (BRANDING_KEY, 'web_settings_revision'))
        raw = {row['key']: json.loads(row['value']) for row in await cursor.fetchall()}
        await cursor.close()
        value = saved_branding(raw.get(BRANDING_KEY))
        if any(item['id'] == identifier for item in value['avatars']):
            value['avatars'] = [item for item in value['avatars'] if item['id'] != identifier]
            if value['avatar_id'] == identifier:
                value.update(mode='preset', preset='4-B', source='', avatar_id='')
            revision = int(raw.get('web_settings_revision') or 0) + 1
            await conn.executemany('INSERT INTO config(key,value) VALUES(?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                [(BRANDING_KEY, json.dumps(value)), ('web_settings_revision', json.dumps(revision))])
            changed = True
    if changed:
        db._config_cache.pop(BRANDING_KEY, None)
        db._web_branding_cache = None
    from .web_appearance import read_appearance
    return await read_appearance(db)
