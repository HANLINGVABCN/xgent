"""Native model calls projected onto the existing Agent operation contract.

No command is executed here. The response and run captures are task-local;
only the established Agent loop may dispatch their validated operations.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from .attachments import AttachmentContextError

MODES = ('toolcall', 'fence')
LABELS = {'toolcall': 'Tool call', 'fence': '正则围栏'}
_session = ContextVar('agent_call_session', default=None)
_response = ContextVar('native_call_response', default=None)


def normalize_mode(value):
    if value not in MODES:
        raise ValueError('工具调用模式必须是 Tool call 或正则围栏')
    return value


def _schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


def _text(description):
    return {'type': 'string', 'description': description}


# Public native names describe capabilities; legacy protocol labels remain a UI concern.
TOOL_NAMES = {
    'run': 'exec_command', 'shell': 'start_terminal', 'stdin': 'terminal_input', 'shellkill': 'close_terminal',
    'read': 'read_file', 'grep': 'search_files', 'intel': 'inspect_code', 'search': 'search_web', 'fetch': 'fetch_urls',
    'sendfile': 'send_file', 'media': 'generate_media', 'over': 'finish_task',
    'file': 'write_file', 'file_base64': 'write_binary', 'edit': 'edit_file', 'ask': 'ask_user',
}
SCALAR_FIELDS = {'run': 'command', 'shell': 'command', 'read': 'path', 'grep': 'query', 'intel': 'request',
                 'search': 'query', 'sendfile': 'path', 'over': 'message', 'stdin': 'input'}
TOOLS = {}


def _tool(kind, description, properties, required):
    TOOLS[TOOL_NAMES[kind]] = {'kind': kind, 'description': description, 'parameters': _schema(properties, required)}


for _kind, _description in {
    'run': '执行一次性非交互命令，等待真实结果。command 是要执行的完整命令。',
    'shell': '启动持续交互终端并返回终端会话 ID。command 是启动命令。',
    'read': '读取文件或原生图片/二进制。path 是实际路径，可用路径:10-20等范围。',
    'grep': '检索文件。query 首行是字面量 pattern；可加 -r 正则、path:、glob:、-i 忽略大小写、-n: 前后上下文行数、-m: 命中上限。',
    'intel': '代码分析。request 为 summary/map/context/callers 等子命令和参数。',
    'search': '联网搜索。query 首行是查询；可另写 max: 1-20、depth: basic/advanced、site: 域名（可重复）、-raw 附正文。',
    'sendfile': '向用户交付已有服务器文件。path 是文件完整路径。',
    'over': '免回传收尾。仅同批执行命令、编辑/写入文件、关闭终端全部成功时省略再问模型。message 写中性收尾语。',
}.items():
    field = SCALAR_FIELDS[_kind]
    _tool(_kind, _description, {field: _text('完整参数；保留换行、缩进及空格，不包围栏。')}, [field])
_tool('stdin', '输入已存在的交互终端；input 支持 line: 文本行、keys: 按键、paste: 多行粘贴及 wait: 秒数。会话 ID 来自真实结果。',
      {'session_id': _text('终端会话 ID'), 'input': _text('完整输入和等待参数，保留换行。')}, ['session_id', 'input'])
_tool('shellkill', '关闭已存在的交互终端。会话 ID 必须来自真实返回。',
      {'session_id': _text('终端会话 ID')}, ['session_id'])
_tool('fetch', '抓取网页。一次最多五个 HTTP/HTTPS URL；结果可能截断并注明，不代表已读取网页全部内容。',
      {'urls': {'type': 'array', 'minItems': 1, 'maxItems': 5, 'items': {'type': 'string'}}}, ['urls'])
_tool('media', '独立媒体模型生成或编辑图片。prompt 是完整任务，files 是可选参考文件的服务器绝对路径；媒体模型不接收聊天历史。',
      {'prompt': _text('完整生成或编辑任务'), 'files': {'type': 'array', 'items': {'type': 'string'}}}, ['prompt'])
_tool('file', '新建或明确授权的整体重写；局部修改使用 edit_file。只写盘不发送，向用户交付文件使用 send_file。',
      {'path': _text('目标文件路径'), 'content': _text('文件完整原文，保留所有空格与换行。')}, ['path', 'content'])
_tool('file_base64', '将 Base64 数据写入文件；用于二进制，不能代替媒体生成接口。只写盘不发送，交付使用 send_file。',
      {'path': _text('目标文件路径'), 'base64_data': _text('完整 Base64 编码')}, ['path', 'base64_data'])
_tool('edit', '唯一字符串原地替换，自动备份；匹配失败需重读，不用整体覆盖。',
      {'path': _text('已有文件路径'), 'old': _text('唯一旧串，保留原缩进与换行。'),
       'new': _text('替换后的原文，保留所有空格与换行。')}, ['path', 'old', 'new'])
_tool('ask', '向用户发多问题表单；密钥只进入用户私密字段，模型只能取得变量名。',
      {'questions': {'type': 'array', 'minItems': 1, 'items': _schema({
          'label': _text('题号，如 Q1'), 'type': {'type': 'string', 'enum': ['single', 'multi', 'text', 'secret']},
          'prompt': _text('问题文字'), 'options': {'type': 'array', 'items': {'type': 'string'}},
          'other': {'type': 'boolean'}, 'variable': _text('secret 类型的大写环境变量名')},
          ['label', 'type', 'prompt'])}}, ['questions'])


def definitions(provider):
    values = [{'name': name, 'description': item['description'], 'parameters': copy.deepcopy(item['parameters'])}
              for name, item in TOOLS.items()]
    if provider in {'gemini', 'vertex'}:
        # Gemini's schema subset has no additionalProperties.
        def subset(value):
            if isinstance(value, dict):
                return {key: subset(item) for key, item in value.items() if key != 'additionalProperties'}
            return [subset(item) for item in value] if isinstance(value, list) else value
        return [{'functionDeclarations': subset(values)}]
    if provider == 'claude':
        return [{'name': v['name'], 'description': v['description'], 'input_schema': v['parameters']} for v in values]
    return [{'type': 'function', 'function': value} for value in values]


def validate_arguments(name, arguments):
    from jsonschema import Draft202012Validator
    if name not in TOOLS:
        raise AttachmentContextError(f'未知工具调用：{name}；未执行。')
    errors = sorted(Draft202012Validator(TOOLS[name]['parameters']).iter_errors(arguments), key=lambda e: str(e.path))
    if errors:
        # Schema diagnostics must not print values, which may be sensitive.
        raise AttachmentContextError(f'工具 {name} 参数格式错误，位置 {list(errors[0].path)}；未执行。')
    if name == 'ask_user':
        for question in arguments['questions']:
            if question['type'] in {'single', 'multi'} and not question.get('options'):
                raise AttachmentContextError('表单选择题缺少选项；未执行。')
            if question['type'] == 'secret' and not re.fullmatch(r'[A-Z_][A-Z0-9_]*', question.get('variable', '')):
                raise AttachmentContextError('表单密钥变量名无效；未执行。')
    if name == 'fetch_urls':
        from urllib.parse import urlsplit
        for url in arguments['urls']:
            parsed = urlsplit(url)
            if '\n' in url or '\r' in url or parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                raise AttachmentContextError('网页地址无效；未执行。')
    if name == 'generate_media':
        from .media_inputs import validate_media_path, MediaInputError
        for path in arguments.get('files', []):
            try:
                if '\n' in path or '\r' in path:
                    raise MediaInputError('参考路径包含换行')
                validate_media_path(path)
            except MediaInputError as exc:
                raise AttachmentContextError('媒体参考文件必须是合法的服务器绝对路径；未执行。') from exc


def operation(call):
    name, args = call['name'], call['arguments']
    validate_arguments(name, args)
    kind = TOOLS[name]['kind']
    block = {'type': kind, 'path': '', 'body': args.get(SCALAR_FIELDS.get(kind), ''), 'native_call_id': call['id'],
             'native_response_id': call.get('response_id')}
    if kind in {'stdin', 'shellkill'}:
        block['path'] = args['session_id']
    elif kind in {'file', 'file_base64'}:
        block.update(path=args['path'], body=args['content'] if kind == 'file' else args['base64_data'])
    elif kind == 'fetch':
        block['body'] = '\n'.join(args['urls'])
    elif kind == 'media':
        block['body'] = ''.join('file: ' + path + '\n' for path in args.get('files', [])) + 'prompt: ' + args['prompt']
    elif kind == 'edit':
        nonce = uuid.uuid4().hex[:12]
        while f'<<OLD_{nonce}' in args['old'] or f'<<NEW_{nonce}' in args['old']:
            nonce = uuid.uuid4().hex[:12]
        block.update(path=args['path'], body=f"<<OLD_{nonce}\n{args['old']}\n<<NEW_{nonce}\n{args['new']}")
        block['native_edit'] = (args['old'], args['new'])
    elif kind == 'ask':
        from .agent_ask import AskForm, AskQuestion
        block['ask_form'] = AskForm(questions=[AskQuestion(
            qid=str(index), label=q['label'], qtype=q['type'], prompt=q['prompt'],
            options=list(q.get('options', [])), other=q.get('other', False), var=q.get('variable', ''),
        ) for index, q in enumerate(args['questions'])])
        block['body'] = '\n'.join(q['prompt'] for q in args['questions'])
    return block



# Fixed conversion for already-saved records only. Provider input is validated
# against TOOLS before rendering or dispatch; these retired names are not offered.
_LEGACY_NAMES = {kind + '_x': kind for kind in TOOL_NAMES}


def normalize_history_call(call):
    kind = _LEGACY_NAMES.get(call.get('name'))
    if kind is None:
        return call
    args = call.get('arguments') or {}
    if kind in SCALAR_FIELDS:
        converted = {SCALAR_FIELDS[kind]: args.get('body', '')}
        if kind == 'stdin':
            converted['session_id'] = args.get('session_id', '')
    elif kind == 'shellkill':
        converted = {'session_id': args.get('session_id', '')}
    elif kind == 'fetch':
        from .agent_search import parse_fetch_body
        converted = {'urls': parse_fetch_body(args.get('body', ''))}
    elif kind == 'media':
        from .media_inputs import parse_media_request
        try:
            request = parse_media_request(args.get('body', ''))
            converted = {'prompt': request.prompt, 'files': list(request.files)}
        except ValueError:
            converted = {'prompt': args.get('body', ''), 'files': []}
    elif kind == 'file_base64':
        converted = {'path': args.get('path', ''), 'base64_data': args.get('content', '')}
    else:
        converted = dict(args)
    return {**call, 'name': TOOL_NAMES[kind], 'arguments': converted}


def display_operation(call):
    kind = _LEGACY_NAMES.get(call.get('name'))
    if kind is not None:
        args = call.get('arguments') or {}
        body = args.get('body', '')
        if kind in {'file', 'file_base64'}:
            body = args.get('content', '')
        elif kind == 'edit':
            body = 'OLD\n' + args.get('old', '') + '\nNEW\n' + args.get('new', '')
        elif kind == 'ask':
            body = '\n'.join(q.get('prompt', '') for q in args.get('questions', []))
        return {'type': kind, 'path': args.get('session_id', args.get('path', '')), 'body': body,
                'native_call_id': call.get('id'), 'native_response_id': call.get('response_id')}
    return operation(normalize_history_call(call))


class ModelReply(str):
    def __new__(cls, text, capture):
        obj = super().__new__(cls, str(text or ''))
        obj.capture = capture
        return obj

    def __bool__(self):
        return bool(str(self)) or bool(self.capture.calls)


class ResponseCapture:
    def __init__(self, session):
        self.session = session
        self.provider = session.provider
        self.parts = {}
        self.calls = []
        self.finished = False
        self.reason = None
        self.response_id = uuid.uuid4().hex
        self.continuation = None

    def observe(self, data, provider='openai', *, stream=False):
        if not isinstance(data, dict):
            return
        if isinstance(data.get('id'), str):
            self.response_id = data['id']
        if provider == 'openai':
            choices = data.get('choices') or []
            if not choices:
                return
            choice = choices[0]
            message = choice.get('delta') or choice.get('message') or {}
            if not stream:
                self.continuation = {key: copy.deepcopy(message[key]) for key in ('reasoning_details', 'reasoning_content') if key in message}
            else:
                if self.continuation is None:
                    self.continuation = {}
                if isinstance(message.get('reasoning_content'), str):
                    self.continuation['reasoning_content'] = self.continuation.get('reasoning_content', '') + message['reasoning_content']
                for piece in message.get('reasoning_details') or []:
                    if not isinstance(piece, dict):
                        continue
                    details = self.continuation.setdefault('reasoning_details', [])
                    found = next((d for d in details if piece.get('index') is not None and d.get('index') == piece['index']
                                  or piece.get('id') is not None and d.get('id') == piece['id']), None)
                    if found is None:
                        details.append(copy.deepcopy(piece))
                    else:
                        for key, value in piece.items():
                            found[key] = found.get(key, '') + value if key in {'text', 'summary', 'data'} and isinstance(value, str) else value
            for index, call in enumerate(message.get('tool_calls') or []):
                slot = call.get('index', index)
                entry = self.parts.setdefault(slot, {'id': '', 'name': '', 'raw': ''})
                if call.get('id'):
                    entry['id'] = call['id']
                function = call.get('function') or {}
                if function.get('name'):
                    entry['name'] = function['name']
                arguments = function.get('arguments')
                if isinstance(arguments, str):
                    entry['raw'] = entry['raw'] + arguments if stream else arguments
            if choice.get('finish_reason'):
                self.reason = choice['finish_reason']
        elif provider == 'gemini':
            candidates = data.get('candidates') or []
            if not candidates:
                return
            parts = candidates[0].get('content', {}).get('parts', [])
            if parts:
                if self.continuation is None:
                    self.continuation = []
                self.continuation.extend(copy.deepcopy(parts))
            for part in parts:
                function = part.get('functionCall')
                if not isinstance(function, dict):
                    continue
                cid = function.get('id') or 'call_' + uuid.uuid4().hex
                previous = next((value for value in self.parts.values() if value['id'] == cid), None)
                if previous is not None:
                    if previous['name'] != function.get('name') or json.loads(previous['raw']) != function.get('args', {}):
                        raise AttachmentContextError('同一工具调用 ID 出现不同参数；未执行。')
                    continue
                self.parts[len(self.parts)] = {'id': cid, 'name': function.get('name', ''),
                                               'raw': json.dumps(function.get('args', {}), ensure_ascii=False)}
            self.reason = candidates[0].get('finishReason') or self.reason
        elif provider == 'claude':
            if not stream:
                self.continuation = copy.deepcopy(data.get('content') or [])
                for index, block in enumerate(self.continuation):
                    if block.get('type') == 'tool_use':
                        self.parts[index] = {'id': block.get('id', ''), 'name': block.get('name', ''),
                                             'raw': json.dumps(block.get('input', {}), ensure_ascii=False)}
                self.reason = data.get('stop_reason')
            else:
                event, index = data.get('type'), data.get('index', 0)
                if self.continuation is None:
                    self.continuation = {}
                if event == 'content_block_start':
                    block = copy.deepcopy(data.get('content_block') or {})
                    self.continuation[index] = block
                    if block.get('type') == 'tool_use':
                        self.parts[index] = {'id': block.get('id', ''), 'name': block.get('name', ''), 'raw': ''}
                elif event == 'content_block_delta':
                    delta = data.get('delta') or {}
                    block = self.continuation.get(index, {})
                    if delta.get('type') == 'input_json_delta' and index in self.parts:
                        self.parts[index]['raw'] += delta.get('partial_json', '')
                    for key in ('text', 'thinking', 'signature'):
                        if key in delta:
                            block[key] = block.get(key, '') + delta[key]
                elif event == 'message_delta':
                    self.reason = (data.get('delta') or {}).get('stop_reason') or self.reason
        if not stream:
            self.finished = True

    def finalize(self):
        if not self.parts:
            self.calls = []
            return
        if not self.finished or str(self.reason or '').lower() not in {
            'stop', 'tool_calls', 'function_call', 'tool_use', 'end_turn', 'stop_sequence', 'eos_token',
        }:
            raise AttachmentContextError(f'工具调用未正常结束（{self.reason or "缺少结束事件"}）；未执行。')
        seen, calls = set(), []
        for index in sorted(self.parts):
            part = self.parts[index]
            if not part['id'] or part['id'] in seen:
                raise AttachmentContextError('工具调用 ID 缺失或重复；未执行。')
            seen.add(part['id'])
            try:
                args = json.loads(part['raw'] or '{}')
            except (ValueError, TypeError) as exc:
                raise AttachmentContextError('工具参数 JSON 不完整；未执行。') from exc
            validate_arguments(part['name'], args)
            calls.append({'id': part['id'], 'name': part['name'], 'arguments': args,
                          'run_id': self.session.run_id, 'response_id': self.response_id})
        self.calls = calls
        if self.provider == 'claude' and isinstance(self.continuation, dict):
            blocks = []
            for index, block in sorted(self.continuation.items()):
                if index in self.parts:
                    block['input'] = json.loads(self.parts[index]['raw'] or '{}')
                blocks.append(block)
            self.continuation = blocks

    def message(self, text):
        result = {'role': 'assistant', 'content': str(text), 'native_calls': copy.deepcopy(self.calls)}
        if self.calls:
            result['native_binding'] = list(self.session.binding)
            result['_native_continuation'] = copy.deepcopy(self.continuation)
        return result


class ToolSession:
    def __init__(self, provider, provider_name, model, run_id, *, mode='toolcall', resume=None):
        self.mode = normalize_mode(mode)
        self.provider, self.provider_name, self.model = provider, provider_name, model
        self.run_id = run_id
        self.binding = [provider, provider_name, model, run_id]
        self.reply = None
        self.executed = set()
        self.current = None
        self.current_response_id = None
        self.current_results = []
        self.resume = resume
        self.remaining = []
        self.provider_config = None
        self.presentation = None

    def claim(self, block):
        cid = block.get('native_call_id')
        if not cid:
            return True
        key = (block.get('native_response_id'), cid)
        if key in self.executed:
            return False
        self.executed.add(key)
        self.current = cid
        self.current_response_id = block.get('native_response_id')
        self.current_results = []
        return True

    def finish(self, history, *, text=None):
        if not self.current:
            return
        messages = self.current_results
        if not messages:
            messages = [{'role': 'user', 'content': text or '[工具结果] 已处理，无附加输出。'}]
            history.extend(messages)
        for message in messages:
            message['native_result'] = {'id': self.current, 'run_id': self.run_id,
                                        'response_id': self.current_response_id}
        self.current = None
        self.current_response_id = None
        self.current_results = []


def current_session():
    return _session.get()


def current_response():
    return _response.get()


@contextmanager
def session_scope(session):
    token = _session.set(session)
    try:
        yield session
    finally:
        _session.reset(token)


def has_calls():
    response = current_response()
    return bool(response and response.parts)


def observe(data, provider='openai', *, stream=False):
    response = current_response()
    if response:
        response.observe(data, provider, stream=stream)


def note_finish(reason=None, finished=None):
    response = current_response()
    if response:
        if reason is not None:
            response.reason = reason
        if finished is not None:
            response.finished = bool(finished)


def _plain_call(call):
    call = normalize_history_call(call)
    return '[已发生的工具调用] ' + call['name'] + '\n' + json.dumps(call['arguments'], ensure_ascii=False)


def historical_content(message):
    content = message.get('content', '')
    calls = message.get('native_calls') or []
    if not calls:
        return content
    text = '\n'.join(_plain_call(call) for call in calls)
    if isinstance(content, list):
        return [*content, {'type': 'text', 'text': text}]
    return (str(content) + '\n' + text).lstrip('\n')


def wire_history(history, session, convert):
    """Only complete, same-run pairs use native envelopes; older facts stay data."""
    provider = session.provider
    def key(call):
        return (call.get('response_id'), call.get('id'))
    results = {key(m.get('native_result', {})) for m in history}
    eligible = {key(c) for m in history if m.get('native_binding') == session.binding
                and m.get('native_calls') and all(key(c) in results for c in m['native_calls'])
                for c in m['native_calls']}
    groups = {}
    for msg in history:
        cid = key(msg.get('native_result', {}))
        if cid in eligible:
            content = msg.get('content', '')
            groups.setdefault(cid, []).extend(content if isinstance(content, list) else [{'type': 'text', 'text': content}])
    emitted, values = set(), []
    for msg in history:
        content = msg.get('content', '')
        calls = msg.get('native_calls') or []
        link = msg.get('native_result') or {}
        if key(link) in eligible:
            continue  # Results were emitted as one complete batch after their call.
        if calls and all(key(c) in eligible for c in calls):
            signature = tuple(key(c) for c in calls)
            if signature in emitted:
                continue
            emitted.add(signature)
            if provider == 'claude':
                parts = copy.deepcopy(msg.get('_native_continuation'))
                if not parts:
                    parts = ([{'type': 'text', 'text': str(content)}] if content else []) + [
                        {'type': 'tool_use', 'id': c['id'], 'name': c['name'], 'input': c['arguments']} for c in calls]
                values.append({'role': 'assistant', 'content': parts})
            elif provider in {'gemini', 'vertex'}:
                parts = copy.deepcopy(msg.get('_native_continuation')) or [
                    {'functionCall': {'id': c['id'], 'name': c['name'], 'args': c['arguments']}} for c in calls]
                values.append({'role': 'model', 'parts': parts})
            else:
                values.append({'role': 'assistant', 'content': convert(content) if content else None,
                    'tool_calls': [{'id': c['id'], 'type': 'function', 'function': {
                        'name': c['name'], 'arguments': json.dumps(c['arguments'], ensure_ascii=False)}} for c in calls],
                    **(msg.get('_native_continuation') or {})})
            native_results, assets = [], []
            for call in calls:
                converted = convert(groups[key(call)])
                if provider == 'claude':
                    native_results.append({'type': 'tool_result', 'tool_use_id': call['id'],
                        'content': converted if isinstance(converted, list) else [{'type': 'text', 'text': converted}]})
                elif provider in {'gemini', 'vertex'}:
                    text = '\n'.join(part.get('text', '') for part in converted if 'text' in part)
                    native_results.append({'functionResponse': {'name': call['name'], 'id': call['id'], 'response': {'output': text}}})
                    assets.extend(part for part in converted if 'text' not in part)
                else:
                    text = converted if isinstance(converted, str) else '\n'.join(
                        part.get('text', '') for part in converted if part.get('type') == 'text')
                    values.append({'role': 'tool', 'tool_call_id': call['id'], 'content': text})
                    if isinstance(converted, list):
                        assets.extend(part for part in converted if part.get('type') != 'text')
            if provider == 'claude':
                values.append({'role': 'user', 'content': native_results})
            elif provider in {'gemini', 'vertex'}:
                values.append({'role': 'user', 'parts': native_results + assets})
            elif assets:
                # All required tool messages precede native attachments. Adding
                # a user image between two tool results is invalid in Chat Completions.
                values.append({'role': 'user', 'content': assets})
        else:
            if calls:
                content = historical_content(msg)
            if not content:
                continue
            role = 'assistant' if msg.get('role') == 'model' else msg.get('role', 'user')
            if provider in {'gemini', 'vertex'}:
                values.append({'role': 'model' if role == 'assistant' else 'user', 'parts': convert(content)})
            else:
                values.append({'role': 'user' if provider == 'claude' and role == 'system' else role, 'content': convert(content)})
    if provider == 'claude':
        merged = []
        for value in values:
            parts = value['content'] if isinstance(value['content'], list) else [{'type': 'text', 'text': value['content']}]
            if merged and merged[-1]['role'] == value['role']:
                merged[-1]['content'].extend(parts)
            else:
                merged.append({'role': value['role'], 'content': parts})
        return merged
    return values


def apply_request(body, history, converters):
    response = current_response()
    if response is None:
        return
    session = response.session
    provider = session.provider
    messages = wire_history(history, session, converters[provider])
    if provider in {'gemini', 'vertex'}:
        body['contents'] = messages
    elif provider == 'claude':
        body['messages'] = messages
    else:
        prompt = getattr(history, 'system_prompt', None)
        systems = [{'role': 'system', 'content': prompt}] if prompt else []
        if prompt is None:
            systems = [m for m in body.get('messages', [])[:1] if m.get('role') == 'system' and
                       not any(m == candidate for candidate in messages)]
        body['messages'] = systems + messages
    body['tools'] = definitions(provider)


def metadata(response=None, text=''):
    response = response or (current_session().reply if current_session() else None)
    if not response or not response.calls:
        return {}
    message = response.message(getattr(response, 'text', text))
    message.pop('_native_continuation', None)
    return {'native_calls': copy.deepcopy(response.calls), 'agent_call_mode': 'toolcall',
            'model_context': {'version': 1, 'messages': [message], 'assets': []}}


def rendering_capture(style):
    """Install one response sink across the existing generation and UI pipeline."""
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            session = current_session()
            if session is None or session.mode != 'toolcall':
                return await function(*args, **kwargs)
            response = ResponseCapture(session)
            session.reply = response
            token = _response.set(response)
            try:
                value = await function(*args, **kwargs)
                return ModelReply(value, response) if value is not None else None
            except (asyncio.CancelledError, GeneratorExit):
                response.calls.clear()
                raise
            finally:
                _response.reset(token)
        return wrapped
    return decorate


def process_scope(function):
    """Pin mode/provider for all generations and form continuations of a turn."""
    @wraps(function)
    async def wrapped(*args, **kwargs):
        import inspect
        ns = function.__globals__
        arguments = inspect.signature(function).bind_partial(*args, **kwargs).arguments
        resume = arguments.get('resume_state') or {}
        session = resume.get('native_session')
        if session is None:
            db = await ns['BotMemoryDB'].get_instance()
            selected = normalize_mode(await db.get_config_fresh('agent_call_mode', 'fence'))
            enabled = arguments.get('force_agent_mode') or ns['UserDataManager'].get('agent_mode', False)
            name, provider = ns['get_current_provider']()
            provider = provider or {}
            model = ns['resolve_effective_chat_model'](ns['UserDataManager'].get('default_model'),
                ns['UserDataManager'].get('default_model'), provider)
            from .conversations import current_scope
            scope = current_scope(required=False)
            session = ToolSession(provider.get('api_format', 'openai'), name, model,
                scope.run_id if scope else uuid.uuid4().hex, mode=selected if enabled else 'fence')
            session.provider_config = copy.deepcopy(provider)
        with session_scope(session):
            turn = ns['current_turn']()
            if resume and session.presentation is not None and turn is not None:
                turn.replies = copy.deepcopy(session.presentation['replies'])
                turn.operations = copy.deepcopy(session.presentation['operations'])
                turn.started_at = session.presentation['started_at']
            return await function(*args, **kwargs)
    return wrapped
