"""Human companion files; never used as model input or execution instructions."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from .compression import _text, metadata_of
from .native_history import call_key


def _stamp(row):
    value = row.get('timestamp')
    if type(value) in {int, float} and math.isfinite(value):
        try:
            return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='seconds')
        except (OverflowError, OSError, ValueError):
            pass
    return str(value) if value is not None else '未记录'


def _messages(row):
    metadata = metadata_of(row)
    payload = metadata.get('model_context')
    if isinstance(payload, dict) and isinstance(payload.get('messages'), list):
        return [message for message in payload['messages'] if isinstance(message, dict)]
    calls = metadata.get('native_calls')
    return [{'native_calls': calls}] if isinstance(calls, list) else []


def _content(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return _text(value)
    parts = []
    for part in value:
        if not isinstance(part, dict):
            continue
        if part.get('type') == 'text':
            parts.append(str(part.get('text') or ''))
        elif part.get('type') == '_tool_context_part':
            details = part.get('part') or {}
            parts.append(f"[已保存原生附件]\n路径：{part.get('path', '')}\n类型：{details.get('mime_type', '')}")
        elif part.get('type') in {'image', 'binary'}:
            parts.append(f"[原生附件]\n类型：{part.get('mime_type', '')}\n文件名：{part.get('filename', '')}")
    return '\n'.join(parts)


def _arguments(arguments):
    labels = {'command': '命令原文', 'content': '文件内容原文', 'old': '匹配原文', 'new': '替换原文',
              'path': '路径', 'query': '检索参数', 'request': '代码分析参数', 'prompt': '生成提示词',
              'input': '终端输入原文', 'session_id': '终端会话', 'urls': '网页地址', 'message': '收尾文字',
              'questions': '表单问题', 'files': '参考文件', 'base64_data': 'Base64 数据'}
    if not isinstance(arguments, dict):
        return json.dumps(arguments, ensure_ascii=False, indent=2)
    parts = []
    for key, value in arguments.items():
        if key == 'base64_data' and isinstance(value, str):
            text = f'[编码原文保留在原始 model_context 中；{len(value)} 字符]'
        else:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        parts.append(f'{labels.get(key, key)}（{key}）：\n{text}')
    return '\n\n'.join(parts)


def _result_state(row, message):
    outcome = message.get('native_result') or {}
    saved = (metadata_of(row).get('presentation') or {}).get('operation') or {}
    states = {'success': '成功', 'failed': '失败', 'stopped': '已停止', 'cancelled': '已取消',
              'waiting': '等待用户', 'unknown': '状态未确定'}
    state = outcome.get('state') or saved.get('state')
    if isinstance(state, str) and state in states:
        return states[state]
    success = outcome.get('success', saved.get('success'))
    return '成功' if success is True else '失败' if success is False else '结果已记录，成功状态未单独记录'


def tool_records(records):
    calls, results, orphan_results = [], {}, []
    seen = set()
    for row in records:
        for message in _messages(row):
            for call in message.get('native_calls') or []:
                if not isinstance(call, dict) or not isinstance(call.get('name'), str):
                    continue
                key = call_key(call)
                if key is not None and key in seen:
                    continue
                if key is not None:
                    seen.add(key)
                calls.append((row, call, key))
            if isinstance(message.get('native_result'), dict):
                key = call_key(message['native_result'])
                if key is None:
                    orphan_results.append((row, message))
                else:
                    results.setdefault(key, []).append((row, message))
    if not calls and not results and not orphan_results:
        return None
    parts = ['工具调用记录\n按调用排列；原始结构保留在各段 a全局记忆.txt 的 model_context 中。']
    used = set()
    for index, (row, call, key) in enumerate(calls, 1):
        from .tool_calls import normalize_history_call
        normalized = normalize_history_call(call)
        heading = (f"--- 工具调用 {index} ---\n时间：{_stamp(row)}\n原记录 ID：{row.get('id', '未记录')}\n"
                   f"工具：{normalized['name']}\n运行 ID：{call.get('run_id', '未记录')}\n"
                   f"响应 ID：{call.get('response_id', '未记录')}\n调用 ID：{call.get('id', '未记录')}")
        parts.append(heading + '\n\n' + _arguments(normalized.get('arguments')))
        linked = results.get(key, []) if key is not None else []
        if not linked:
            parts.append('对应结果：未找到已保存的对应结果记录。')
        else:
            used.add(key)
            for result_row, message in linked:
                parts.append(f"对应结果 · 原记录 {result_row.get('id', '未记录')} · {_stamp(result_row)}\n"
                             f"状态：{_result_state(result_row, message)}\n{_content(message.get('content', ''))}")
    orphan_results.extend(item for key, items in results.items() if key not in used for item in items)
    for row, message in orphan_results:
        parts.append(f"--- 未关联的工具结果 · 原记录 {row.get('id', '未记录')} ---\n时间：{_stamp(row)}\n"
                     '未找到可靠的对应调用记录，未推测工具名称。\n' + _content(message.get('content', '')))
    return ('\n\n'.join(parts) + '\n').encode('utf-8')


def thinking_records(records):
    parts = []
    states = {'running': '尚未结束', 'completed': '已结束', 'failed': '失败', 'stopped': '已停止'}
    for row in records:
        thinking = metadata_of(row).get('thinking')
        if not isinstance(thinking, dict) or not isinstance(thinking.get('text'), str) or not thinking['text'].strip():
            continue
        elapsed = thinking.get('elapsed_seconds')
        duration = f'{elapsed:g}s' if type(elapsed) in {int, float} and math.isfinite(elapsed) and elapsed >= 0 else '耗时未记录'
        state = thinking.get('status')
        status = states.get(state, '状态未记录') if isinstance(state, str) else '状态未记录'
        parts.append(f"--- 思考 · 原记录 {row.get('id', '未记录')} ---\n时间：{_stamp(row)}\n"
                     f"状态：{status}\n记录耗时：{duration}\n\n{thinking['text']}")
    return ('\n\n'.join(parts) + '\n').encode('utf-8') if parts else None


def readable_files(records):
    result = {}
    tools = tool_records(records)
    thoughts = thinking_records(records)
    if tools is not None:
        result['工具调用记录.txt'] = tools
    if thoughts is not None:
        result['思考记录.txt'] = thoughts
    return result
