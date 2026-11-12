"""Native Telegram rendering through the existing delivery worker and SDK request."""
from __future__ import annotations

from copy import deepcopy
import asyncio
import inspect
import time
import weakref

from .protocols import ProtocolParser

OP_NATIVE_CONTROL = 'telegram_generation_control'
OP_NATIVE_DRAFT = 'telegram_rich_draft'
OP_NATIVE_RENDER = 'telegram_rich_render'
OP_NATIVE_MARKUP = 'telegram_native_markup'
OP_NATIVE_DELETE = 'telegram_native_delete'
OP_NATIVE_CLEANUP = 'telegram_generation_cleanup'
OP_NATIVE_MEDIA = 'telegram_media_reply'
NATIVE_KINDS = frozenset({OP_NATIVE_CONTROL, OP_NATIVE_DRAFT, OP_NATIVE_RENDER,
                         OP_NATIVE_MARKUP, OP_NATIVE_DELETE, OP_NATIVE_CLEANUP, OP_NATIVE_MEDIA})

_states = weakref.WeakKeyDictionary()
_fallback_states = {}
PREVIEW_INTERVAL_SECONDS = 2.0
PROGRESS_INTERVAL_SECONDS = 3.0


async def _preview_ready(state, op, interval):
    deadlines = state.setdefault('preview_deadlines', {})
    now = time.monotonic()
    delay = deadlines.get(op.chat_id, 0.0) - now
    if delay > 0:
        await asyncio.sleep(delay)
    from .stop_targets import active_target
    spec = op.payload['telegram_native']
    run_id = (op.conversation_context or {}).get('run_id')
    if (op.superseded or spec.get('ref') and not active_target(run_id, spec['ref'])
            or time.time() - op.created_at > 30):
        return False
    deadlines[op.chat_id] = time.monotonic() + interval
    return True


def request_capable(bot):
    method = getattr(bot, '_post', None)
    return callable(method) and (inspect.iscoroutinefunction(method) or type(bot).__module__.startswith('telegram.'))


def _state(bot):
    try:
        return _states.setdefault(bot, {'rich': None, 'draft': None, 'messages': {}})
    except TypeError:
        if len(_fallback_states) > 64:
            _fallback_states.clear()
        return _fallback_states.setdefault(id(bot), {'rich': None, 'draft': None, 'messages': {}})


def rich_available(bot):
    return request_capable(bot) and _state(bot)['rich'] is not False


def _unsupported(exc):
    from telegram.error import BadRequest, TelegramError
    if not isinstance(exc, TelegramError):
        return False
    text = str(exc).lower()
    return (text in {'not found', 'not found (404)'} or 'method not found' in text or 'unknown method' in text or
            isinstance(exc, BadRequest) and any(value in text for value in (
                'rich messages are not supported', 'rich_message is not supported',
                'unsupported rich message', 'drafts are not supported')))


def native_offer_kind(kind, payload, bot):
    """Convert only Telegram's projection; the original UI frame keeps its kind."""
    from .fanout import OP_SEND, OP_EDIT, OP_EDIT_MARKUP, OP_DELETE
    spec = payload.get('telegram_native')
    if not isinstance(spec, dict):
        return kind
    if spec.get('form_receipt') and kind in {OP_SEND, OP_EDIT}:
        return OP_NATIVE_RENDER
    if not request_capable(bot) and spec.get('mode') != 'background':
        return kind
    if spec.get('auxiliary'):
        return None
    if spec.get('phase') == 'cleanup':
        return OP_NATIVE_CLEANUP
    if kind == OP_DELETE:
        return OP_NATIVE_DELETE
    if kind == OP_EDIT_MARKUP:
        return OP_NATIVE_MARKUP
    if kind not in {OP_SEND, OP_EDIT}:
        return kind
    phase = spec.get('phase')
    if phase == 'control':
        return OP_NATIVE_CONTROL
    if phase == 'draft':
        return OP_NATIVE_DRAFT
    return OP_NATIVE_RENDER


def _bot_id(bot):
    try:
        return int(bot.id)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


async def _stored_parts(bot, op, value=None):
    record_id = op.payload.get('telegram_native', {}).get('record_id')
    if not isinstance(record_id, int) or _bot_id(bot) is None:
        return None
    from .web_history import _section_ns
    from .presentation import metadata_dict
    ns = _section_ns()
    if not ns:
        return None
    db = await ns['BotMemoryDB'].get_instance()
    row = await db.get_display_message(record_id)
    if not row:
        return None
    metadata = metadata_dict(row.get('metadata'))
    saved = metadata.get('telegram_native_parts') or {}
    if value is None:
        return saved.get('ids') if (saved.get('bot_id') == _bot_id(bot) and saved.get('owner_id') == op.logical_id
            and saved.get('conversation_id') in {None, row['session_id']}
            and saved.get('record_id') in {None, row['id']}
            and (not row.get('source_record_id') or saved.get('record_id') == row['id'])) else None
    metadata['telegram_native_parts'] = {'bot_id': _bot_id(bot), 'owner_id': op.logical_id, 'ids': list(value),
                                        'conversation_id': row['session_id'], 'record_id': row['id']}
    await db.patch_display_metadata(record_id, {'telegram_native_parts': metadata['telegram_native_parts']})
    return value


async def _post(bot, method, data, extra):
    if method=='editMessageText':
        data={key:value for key,value in data.items() if key in {'chat_id','message_id','text','rich_message',
            'parse_mode','entities','reply_markup','link_preview_options'}}
    if not request_capable(bot):
        names = {'sendMessage':'send_message', 'editMessageText':'edit_message_text',
                 'deleteMessage':'delete_message', 'editMessageReplyMarkup':'edit_message_reply_markup'}
        result = await getattr(bot, names[method])(**deepcopy(data))
        mid = getattr(result, 'message_id', None)
        return {'message_id':mid} if mid is not None else result
    return await bot._post(method, deepcopy(data), **{key: value for key, value in extra.items()
        if key in {'read_timeout', 'write_timeout', 'connect_timeout', 'pool_timeout'}})


async def _ignore_same_edit(bot, method, data, extra):
    from telegram.error import BadRequest
    try:
        return await _post(bot, method, data, extra)
    except BadRequest as exc:
        if 'message is not modified' not in str(exc).lower():
            raise
        return True


async def _delete_control(bot, chat_id, entry, extra):
    control = entry.get('control_id')
    if control:
        from telegram.error import BadRequest
        try:
            await _post(bot, 'deleteMessage', {'chat_id': chat_id, 'message_id': control}, extra)
        except BadRequest as exc:
            if 'message to delete not found' not in str(exc).lower():
                raise
        entry['control_id'] = None


def _generation_status(spec):
    mode = spec.get('mode')
    label = {'background': '后台流式', 'nonstream': '非流式'}.get(mode, '前台流式')
    raw = str(spec.get('raw') or '')
    detail = ('等待完整回复' if mode == 'nonstream' else
              '已生成 ' + str(len(raw)) + ' 字' if raw else '等待首段内容')
    return label + '输出中… ' + detail


async def _generation_control(bot, op, state, entry, keyboard, delivery, extra, *,
                              paced=True, text=None, parse_mode=None):
    """Reuse the same status and Stop target for waiting and streamed previews."""
    from .web_bridge import markup_from_frame
    spec = op.payload['telegram_native']
    controls = markup_from_frame(spec.get('control_markup'))
    control_keyboard = controls.to_dict() if controls else keyboard
    text = _generation_status(spec) if text is None else text
    signature = (text, control_keyboard, parse_mode)
    if entry['control_id'] and entry.get('control_signature') == signature:
        return
    if paced and entry['control_id'] and not await _preview_ready(state, op, PROGRESS_INTERVAL_SECONDS):
        return
    data = {'chat_id': op.chat_id, 'text': text, 'reply_markup': control_keyboard, **delivery}
    if parse_mode:
        data['parse_mode'] = parse_mode
    if entry['control_id']:
        await _ignore_same_edit(bot, 'editMessageText', {**data, 'message_id': entry['control_id']}, extra)
    else:
        sent = await _post(bot, 'sendMessage', data, extra)
        entry['control_id'] = sent['message_id']
    entry['control_signature'] = signature


async def _background_body(bot, op, state, entry, keyboard, delivery, extra):
    """Keep received parts in order; the last message owns the Stop button."""
    from .protocols import _telegram_units
    spec = op.payload['telegram_native']
    bodies = [ProtocolParser.to_telegram_html(str(value)) for value in
              (spec.get('fallback') or [op.payload.get('text') or ''])]
    ids = [*entry.get('preview_ids', []), *([entry['control_id']] if entry['control_id'] else [])]
    previous = entry.get('preview_html', [])
    for index, body in enumerate(bodies[:-1]):
        data = {'chat_id': op.chat_id, 'text': body, 'parse_mode': 'HTML', 'reply_markup': None, **delivery}
        if index < len(ids):
            if index >= len(previous) or previous[index] != body or ids[index] == entry['control_id']:
                await _ignore_same_edit(bot, 'editMessageText', {**data, 'message_id': ids[index]}, extra)
        else:
            sent = await _post(bot, 'sendMessage', data, extra)
            ids.append(sent['message_id'])
    last = len(bodies) - 1
    entry['preview_ids'] = ids[:last]
    entry['preview_body'] = True
    active = ids[last] if last < len(ids) else None
    if active != entry['control_id']:
        entry['control_id'] = active
        entry.pop('control_signature', None)
    body = bodies[-1]
    text = _generation_status(spec) + ('\n\n' + body if body.strip() else '')
    if _telegram_units(text) > 3900:
        text = body
    await _generation_control(bot, op, state, entry, keyboard, delivery, extra,
                              paced=False, text=text, parse_mode='HTML')
    for mid in ids[len(bodies):]:
        await _post(bot, 'deleteMessage', {'chat_id': op.chat_id, 'message_id': mid}, extra)
    entry['preview_ids'] = ids[:last]
    entry['preview_html'] = bodies[:-1]
    entry['preview_body'] = True


async def deliver_native(bot, op, native_id, markup, extra):
    state = _state(bot)
    if op.kind == OP_NATIVE_MEDIA:
        from .telegram_media_reply import send
        media_key = (op.chat_id, op.logical_id)
        cache = state.setdefault('media', {})
        previous = cache.get(media_key)
        if previous:
            op.payload = {**previous, **op.payload, '_native_parts': previous.get('_native_parts', []),
                          '_page_html': previous.get('_page_html', [])}
        if not op.payload.get('_native_parts'):
            op.payload['_native_parts'] = list(await _stored_parts(bot, op) or ([native_id] if native_id else []))
        result = await send(bot, op, extra, rich=state['rich'] is not False and not op.payload.get('_fallback'))
        cache[media_key] = op.payload.copy()
        if op.payload.get('_fallback'):
            state['rich'] = False
        while len(cache)>1000:
            cache.pop(next(iter(cache)))
        await _stored_parts(bot, op, op.payload.get('_native_parts', []))
        return result
    spec = op.payload['telegram_native']
    if spec.get('mode') == 'background' and not request_capable(bot):
        state['rich'] = False
    if spec.get('form_receipt') and not request_capable(bot):
        state['rich'] = False
    context = op.conversation_context or {}
    key = (op.chat_id, op.logical_id, context.get('conversation_id'), context.get('generation'))
    entry = state['messages'].setdefault(key, {'ids': [], 'html': [], 'control_id': None})
    ref, run_id = spec.get('ref'), context.get('run_id')
    if op.kind in {OP_NATIVE_CONTROL, OP_NATIVE_DRAFT}:
        from .stop_targets import active_target
        if ref and not active_target(run_id, ref) or op.kind == OP_NATIVE_DRAFT and time.time() - op.created_at > 30:
            return None
    if spec.get('running') and ref:
        from .stop_targets import active_target
        if not active_target(run_id, ref):
            return None
    kwargs = dict(op.payload.get('kwargs') or {})
    delivery = {key: value for key, value in kwargs.items() if key in {
        'message_thread_id', 'disable_notification', 'protect_content', 'reply_parameters'}}
    keyboard = markup.to_dict() if hasattr(markup, 'to_dict') else markup
    if op.kind == OP_NATIVE_CLEANUP:
        await _delete_control(bot, op.chat_id, entry, extra)
        return None
    if op.kind == OP_NATIVE_CONTROL:
        await _generation_control(bot, op, state, entry, keyboard, delivery, extra)
        return None  # A status ID is never the formal reply ID.
    if op.kind == OP_NATIVE_MARKUP:
        ids = entry['ids'] or ([native_id] if native_id else [])
        if entry['control_id']:
            ids = [*ids, entry['control_id']]
        for mid in ids:
            await _ignore_same_edit(bot, 'editMessageReplyMarkup', {'chat_id': op.chat_id,
                'message_id': mid, 'reply_markup': keyboard}, extra)
        return None
    if op.kind == OP_NATIVE_DELETE:
        await _delete_control(bot, op.chat_id, entry, extra)
        for mid in list(dict.fromkeys([*(entry['ids'] or ([native_id] if native_id else [])), *entry.get('preview_ids', [])])):
            await _post(bot, 'deleteMessage', {'chat_id': op.chat_id, 'message_id': mid}, extra)
        state['messages'].pop(key, None)
        return None
    rich_html = list(spec.get('html') or [' '])
    if op.kind == OP_NATIVE_DRAFT:
        if spec.get('mode') == 'background' and 'preview_raw' in entry and entry['preview_raw'] == spec.get('raw'):
            return None
        interval = PROGRESS_INTERVAL_SECONDS if spec.get('mode') == 'background' else PREVIEW_INTERVAL_SECONDS
        if not await _preview_ready(state, op, interval):
            return None
        if spec.get('mode') == 'background':
            await _background_body(bot, op, state, entry, keyboard, delivery, extra)
            entry['preview_raw'] = spec.get('raw')
            return None
        if state['rich'] is not False and state['draft'] is not False:
            await _generation_control(bot, op, state, entry, keyboard, delivery, extra, paced=False)
            try:
                await _post(bot, 'sendRichMessageDraft', {'chat_id': op.chat_id,
                    'draft_id': spec['draft_id'], 'rich_message': {'html': rich_html[-1]},
                    'can_stop': False, 'keep_on_stop': False,
                    **{key: value for key, value in delivery.items() if key == 'message_thread_id'}}, extra)
                state['draft'] = True
                return None
            except Exception as exc:
                if not _unsupported(exc):
                    raise
                state['draft'] = False
        # Older local API: keep one live status, finalize the complete body later.
        status = _generation_status(spec)
        body = str(op.payload.get('text') or '')
        if spec.get('raw') and body:
            status += '\n\n' + body
        await _generation_control(bot, op, state, entry, keyboard, delivery, extra,
                                  paced=False, text=status, parse_mode=op.payload.get('parse_mode'))
        return None
    if not entry['ids']:
        preview = [*entry.get('preview_ids', []), *([entry['control_id']] if entry.get('preview_body') and entry['control_id'] else [])]
        entry['ids'] = list(op.payload.get('_native_parts') or await _stored_parts(bot, op) or preview or ([native_id] if native_id else []))
        if preview and entry['ids'] == preview:
            entry['control_id'] = None
            entry.pop('preview_ids', None)
            entry.pop('control_signature', None)
    if spec.get('empty'):
        # No generated AI body: keep only the actual terminal status.
        if entry['control_id']:
            await _ignore_same_edit(bot, 'editMessageText', {'chat_id': op.chat_id,
                'message_id': entry['control_id'], 'text': str(op.payload.get('text') or '已结束'), 'reply_markup': None}, extra)
        return None
    values = rich_html if state['rich'] is not False else list(spec.get('fallback') or [op.payload.get('text') or ' '])
    index = 0
    while index < len(values):
        body = values[index]
        use_rich = state['rich'] is not False
        from .telegram_presentation import render_telegram_text
        if not delivery.get('message_thread_id'):
            body = await render_telegram_text(body, 'HTML', limit=2**31)
        if spec.get('form_receipt'):
            from .telegram_form_receipts import materialize
            body = materialize(body, spec, op)
        data = {'chat_id': op.chat_id, **delivery,
                'reply_markup': keyboard if index == len(values) - 1 else None}
        data.update({'rich_message': {'html': body}} if use_rich else
                    {'text': ProtocolParser.to_telegram_html(body), 'parse_mode': 'HTML'})
        editing = index < len(entry['ids'])
        method = 'editMessageText' if editing else 'sendRichMessage' if use_rich else 'sendMessage'
        if editing:
            data['message_id'] = entry['ids'][index]
        try:
            result = await _ignore_same_edit(bot, method, data, extra)
        except Exception as exc:
            if use_rich and _unsupported(exc):
                state['rich'] = False
                values = list(spec.get('fallback') or [op.payload.get('text') or ' '])
                index = 0
                continue
            raise
        if use_rich:
            state['rich'] = True
        if not editing:
            entry['ids'].append(result['message_id'])
        op.payload['_native_parts'] = list(entry['ids'])
        await _stored_parts(bot, op, entry['ids'])
        index += 1
    for mid in entry['ids'][len(values):]:
        await _post(bot, 'deleteMessage', {'chat_id': op.chat_id, 'message_id': mid}, extra)
    del entry['ids'][len(values):]
    entry['html'] = list(values)
    await _stored_parts(bot, op, entry['ids'])
    await _delete_control(bot, op.chat_id, entry, extra)
    return entry['ids'][0] if entry['ids'] else None
