"""Compact write results; files are delivered only by the explicit sendfile tool."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping
import html

from .presentation import current_turn, message_presentation
from .web_display import web_display_scope


async def present_written_agent_file(
    written_file: Mapping[str, Any],
    *,
    protocol: str,
    context: Any,
    chat_id: Any,
    safe_send_message: Callable[..., Awaitable[Any]],
    safe_text: Callable[[Any], str],
    html_parse_mode: Any,
) -> str:
    """Show the actual write result without uploading a file or creating a media card."""
    saved_path = str(written_file["path"])
    saved_size = int(written_file["size"])
    text = f"✅ 已写入 · {saved_path}"
    facts = {'version': 1, 'protocol': protocol, 'path': saved_path,
             'filename': str(written_file['filename']), 'size': saved_size,
             'overwritten': bool(written_file['existed']), 'text': text}
    turn = current_turn()
    facts['operation_sequence'] = (turn.active_operation or {}).get('sequence') if turn else None
    if turn and turn.active_operation is not None:
        turn.active_operation['file_write'] = facts
    previous_message = turn.last_message if turn else None
    from .message_policy import new_policy
    display = {'version': 1, 'segments': [{'kind': 'html',
               'text': '<span class="file-write-result">' + html.escape(text) + '</span>'}],
               'presentation_mode': 'folded'}
    with message_presentation({'kind': 'agent_result', 'purpose': 'status',
            'message_policy': new_policy('agent_result', hint={'purpose': 'status'}).to_dict(),
            'telegram_display': {'text': text, 'parse_mode': None}}), web_display_scope(display):
        await safe_send_message(context, chat_id, html.escape(text), parse_mode=html_parse_mode)
    if turn is not None and turn.last_message is not None and turn.last_message is not previous_message:
        turn.last_message.file_write = facts

    return (
        f"[{protocol}结果] 已写入服务器文件: {saved_path} "
        f"({saved_size} bytes, {'覆盖' if written_file['existed'] else '新建'})"
    )
