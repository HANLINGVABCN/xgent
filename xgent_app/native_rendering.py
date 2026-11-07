"""Display native calls using existing compact protocol cards and delivery IDs."""
from __future__ import annotations

import html
import json
import time

from . import tool_calls
from .web_display import web_block_html, web_display_scope
from .presentation import message_presentation
from .telegram_rich import Block, markdown_blocks, split_blocks, html_block
from .protocols import ProtocolParser


def rich_calls(text, calls, *, details=''):
    blocks = markdown_blocks(str(text)) if text else []
    from .web_history import _section_ns
    namespace = _section_ns()
    legacy = namespace['markdown_to_telegram_html'](str(text)) if namespace and text else html.escape(str(text or ''))
    for call in calls:
        block = tool_calls.display_operation(call)
        if block['type']=='render':
            blocks.append(Block(text='渲染页面',inline=True));legacy+='\n渲染页面';continue
        if block['type']=='over':
            continue
        name = 'file-x' if block['type'] == 'file_base64' else block['type'] + '-x'
        body = block['body']
        preview, note = ProtocolParser._telegram_preview(body)
        header = '<b>' + html.escape(name) + '</b> · ' + str(body.count('\n') + 1) + ' 行<br>'
        blocks.append(Block('blockquote', {'expandable': True}, children=[
            Block(text=header, inline=True), Block('code', children=[Block(text=preview, inline=True)]), Block(text=note, inline=True)]))
        legacy += ('\n' if legacy else '') + '<blockquote expandable>' + header.replace('<br>', '\n') + '<code>' + preview + '</code>' + note + '</blockquote>'
    if details:
        blocks.append(html_block(details))
    fallback = namespace['split_html_for_telegram'](legacy or ' ', 3900) if namespace else split_blocks([Block(text=legacy, inline=True)], budget=3800)
    return split_blocks(blocks), fallback


def segments(text, calls, operations=()):
    values = [{'kind': 'markdown', 'text': str(text)}] if text else []
    for call in calls:
        block = tool_calls.display_operation(call)
        if block['type']=='render':
            values.append({'kind':'html','text':'<span class="file-write-result">渲染页面</span>'});continue
        if block['type']=='over':
            continue
        matched = next((op for op in operations if op.get('native_call_id') == call['id']), None)
        values.append({'kind': 'html', 'text': web_block_html(block['body'],
            protocol='file-x' if block['type'] == 'file_base64' else block['type'] + '-x',
            state=matched.get('state', 'pending') if matched else 'pending', path=block.get('path'),
            raw=json.dumps({'name': call['name'], 'arguments': call['arguments']}, ensure_ascii=False, indent=2))})
    return values


async def finish(ns, context, chat_id, msg, reply, text, usage_sink, started, token_sink, *, renderer=None):
    capture = tool_calls.current_response()
    capture.finalize()
    capture.text = str(text)
    reply.native_capture = capture
    if renderer:
        await renderer.cancel()
    text, artifacts = await reply.prepare(str(text))
    capture.text = text
    if not reply.recorded:
        metadata = {**tool_calls.metadata(capture, text), **ns['live_reply_metadata'](reply)}
        reply.record_id = await ns['GlobalRecorder'].record_ai_reply(
            text, chat_id, provider=capture.session.provider_name, model=capture.session.model, metadata=metadata)
        if reply.record_id is None:
            raise ns['AttachmentContextError']('工具调用记录保存失败，未执行。')
        reply.recorded = True
    turn = ns['current_turn']()
    if turn and turn.active_reply is not None:
        turn.active_reply['native_calls'] = capture.calls
    display = {'version': 1, 'segments': segments(text, capture.calls), 'presentation_mode': 'folded'}
    hint = {'kind': 'ai_reply', 'mode': 'folded', 'native_calls': capture.calls, 'record_id': reply.record_id,
            'telegram_content': {'raw': text, 'complete': True, 'owner_id': getattr(msg, 'message_id', None)}}
    # The visible card is a projection. DB/model text remains the exact prose.
    legacy = '\n'.join(ns['markdown_to_telegram_html'](s['text']) if s['kind'] == 'markdown' else s['text']
                       for s in display['segments'])
    with message_presentation(hint), web_display_scope(display):
        await ns['finalize_html_response'](context, chat_id, msg, legacy, 3900)
    if artifacts:
        with ns['media_presentation_scope'](ns['build_media_presentation'](text, artifacts)):
            await ns['send_generated_media_artifacts'](context, chat_id, artifacts, caption=text)
    await ns['send_token_usage_message'](context, chat_id, usage_sink[0] if usage_sink else None,
        time.monotonic() - started, token_text_sink=token_sink)
    return tool_calls.ModelReply(text, capture)
