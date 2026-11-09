"""Telegram chat formatting, separate from shared message bodies and Web/CLI."""
from __future__ import annotations

import html
import re

from .protocols import ProtocolParser, _telegram_units

MESSAGE_BUDGET = 3900


def escaped_chunks(text, budget):
    """Split plain text without breaking Unicode or an escaped HTML entity."""
    chunks, current, size = [], [], 0
    for char in str(text):
        escaped = html.escape(char, quote=False)
        width = _telegram_units(escaped)
        if current and size + width > budget:
            chunks.append(''.join(current))
            current, size = [], 0
        current.append(escaped)
        size += width
    if current:
        chunks.append(''.join(current))
    return chunks


def quote_chunks(text, *, heading=''):
    opening, closing = '<blockquote expandable>', '</blockquote>'
    first = '<b>' + html.escape(heading) + '</b>\n' if heading else ''
    chunks = []
    remaining = str(text)
    # The heading is normally short; avoid truncating an actual provider/model.
    while remaining:
        prefix = opening + (first if not chunks else '')
        budget = MESSAGE_BUDGET - _telegram_units(prefix + closing)
        encoded = escaped_chunks(remaining, budget)[0]
        chunks.append(prefix + encoded + closing)
        remaining = remaining[len(html.unescape(encoded)):]
    return chunks or [opening + first.rstrip('\n') + closing]


def output_chunks(operation):
    from .web_display import PROTOCOL_NAMES, operation_state

    kind = operation.get('kind') or 'run'
    protocol = operation.get('protocol_name') or PROTOCOL_NAMES.get(kind, kind + '-x')
    state = operation_state(operation)
    label = {'success': '🟢', 'failed': '🔴', 'running': '⚪', 'stopped': '⚪'}.get(state, '⚪')
    status = {'running': '执行中', 'stopped': '输出 · 已停止', 'failed': '输出 · 失败',
              'success': '输出'}.get(state, '输出 · 未确认')
    body = str(operation.get('output') or operation.get('notice') or '(无输出)')
    header = f'<b>{label} {html.escape(protocol)} · {status}</b> · {body.count(chr(10)) + 1} 行'
    preview, note = ProtocolParser._telegram_preview(body)
    opening, closing = '<blockquote expandable>', '</blockquote>'
    text = opening + header + '\n' + preview + note
    path = operation.get('output_path')
    if not path:
        return [text + closing]
    suffix = (' · ' if note else '\n') + '存档：' + html.escape(str(path), quote=False)
    if _telegram_units(text + suffix + closing) <= MESSAGE_BUDGET:
        return [text + suffix + closing]
    # Preserve the same 50-line/3200-character preview. An exceptional long path
    # becomes a continuation of this output, rather than reducing that preview.
    return [text + closing, *quote_chunks('存档：' + str(path))]


def reply_details(row, facts, summary=None, *, timezone='Asia/Shanghai'):
    from .presentation import metadata_dict, reply_usage_facts, summary_line, usage_line

    metadata = metadata_dict(row.get('metadata'))
    presentation = metadata.get('presentation') or {}
    usage = facts.get('usage') or presentation.get('usage') or {}
    values = reply_usage_facts({**presentation, **facts, 'usage': {'input_tokens': usage.get('input_tokens'),
        'output_tokens': usage.get('output_tokens'), 'cached_tokens': usage.get('cached_tokens')}}, row=row)
    line = usage_line(values, time_at_end=True, timezone=timezone)
    def compact_time(text):
        return re.sub(r'约 (\d+(?:\.\d+)?) 秒', lambda match: match[1].rstrip('0').rstrip('.') + 's'
                      if '.' in match[1] else match[1] + 's', text)
    lines = []
    if summary:
        # The separate terminal notice already states stop/failure once.
        lines.append(compact_time(summary_line({**summary, 'reason': ''})))
    lines.append(line)
    return quote_chunks('\n'.join(lines))


def append_details(base_html, details):
    base = ProtocolParser.to_telegram_html(base_html)
    if base and _telegram_units(base + '\n' + details[0]) <= MESSAGE_BUDGET:
        return [base + '\n' + details[0], *details[1:]]
    return [base, *details] if base else list(details)
