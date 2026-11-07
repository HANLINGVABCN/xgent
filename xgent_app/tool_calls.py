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
from .native_history import call_key, wire_call_ids

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
    if call.get('name')=='render_visual':
        return {'type':'render','path':'','body':'','native_call_id':call.get('id')}
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
        self.invalid_error = None
        self._wire_response_id = None
        self._stream_sealed = False
        self._closed_slots = set()
        self.capture_id = uuid.uuid4().hex
        self.request_attempts = 0
        self.request_summary = {}
        self.parse_state = 'not_requested'

    def trace(self, event, **fields):
        self.session.trace(event, capture_id=self.capture_id, response_id=self.response_id,
                           received_calls=len(self.parts), parsed_calls=len(self.calls), **fields)

    def request_attempt(self):
        self.request_attempts += 1
        self.trace('tool_request', stage='client_request_attempt', attempt=self.request_attempts, **self.request_summary)

    def observe(self, data, provider='openai', *, stream=False):
        if self.invalid_error is not None:
            raise self.invalid_error
        try:
            return self._observe(data, provider, stream=stream)
        except AttachmentContextError as exc:
            self.invalid_error = exc
            self.calls.clear()
            self.parse_state = 'failed'
            self.trace('tool_parse', stage='stream_validation', status='failed', error=str(exc)[:2000])
            raise

    def _slot(self, index):
        if type(index) is not int or index < 0:
            raise AttachmentContextError('工具调用分片索引无效；未执行。')
        return index

    def _observe(self, data, provider='openai', *, stream=False):
        if not isinstance(data, dict):
            return
        response_id = data.get('responseId') if provider == 'gemini' else data.get('id')
        if provider == 'claude' and data.get('type') == 'message_start':
            response_id = (data.get('message') or {}).get('id')
        if isinstance(response_id, str) and response_id:
            if self._wire_response_id is not None and self._wire_response_id != response_id:
                raise AttachmentContextError('同一响应的 ID 在分片中变化；未执行。')
            self._wire_response_id = self.response_id = response_id
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
            incoming = message.get('tool_calls') or []
            if not isinstance(incoming, list):
                raise AttachmentContextError('工具调用字段格式错误；未执行。')
            if stream and self._stream_sealed and incoming:
                raise AttachmentContextError('工具调用结束后仍收到参数分片；未执行。')
            slots = set()
            for index, call in enumerate(incoming):
                if not isinstance(call, dict):
                    raise AttachmentContextError('工具调用分片格式错误；未执行。')
                slot = call.get('index')
                if slot is None:
                    if stream and (len(incoming) > 1 or len(self.parts) > 1):
                        raise AttachmentContextError('多工具流式分片缺少索引；未执行。')
                    slot = index
                slot = self._slot(slot)
                if slot in slots:
                    raise AttachmentContextError('同一事件的工具调用索引重复；未执行。')
                slots.add(slot)
                entry = self.parts.setdefault(slot, {'id': '', 'name': '', 'raw': ''})
                if call.get('id'):
                    if not isinstance(call['id'], str) or entry['id'] and entry['id'] != call['id']:
                        raise AttachmentContextError('同一工具调用分片的 ID 冲突；未执行。')
                    entry['id'] = call['id']
                function = call.get('function') or {}
                if not isinstance(function, dict):
                    raise AttachmentContextError('工具函数字段格式错误；未执行。')
                if function.get('name'):
                    name = function['name']
                    if not isinstance(name, str):
                        raise AttachmentContextError('工具函数名格式错误；未执行。')
                    previous = entry['name']
                    if not previous or name == previous:
                        entry['name'] = name
                    elif stream and previous not in TOOLS and any(tool.startswith(previous + name) for tool in TOOLS):
                        entry['name'] = previous + name
                    else:
                        raise AttachmentContextError('同一工具调用分片的函数名冲突；未执行。')
                arguments = function.get('arguments')
                if isinstance(arguments, str):
                    entry['raw'] = entry['raw'] + arguments if stream else arguments
                elif arguments is not None:
                    raise AttachmentContextError('工具参数字段不是 JSON 字符串；未执行。')
            if choice.get('finish_reason'):
                self.reason = choice['finish_reason']
                self._stream_sealed = stream
        elif provider == 'gemini':
            candidates = data.get('candidates') or []
            if not candidates:
                return
            parts = candidates[0].get('content', {}).get('parts', [])
            if not isinstance(parts, list) or not all(isinstance(part, dict) for part in parts):
                raise AttachmentContextError('工具响应内容块格式错误；未执行。')
            if stream and self._stream_sealed and any(isinstance(part, dict) and part.get('functionCall') for part in parts):
                raise AttachmentContextError('工具调用结束后仍收到函数分片；未执行。')
            if parts:
                if self.continuation is None:
                    self.continuation = []
            for part in parts:
                function = part.get('functionCall')
                if function is None:
                    self.continuation.append(copy.deepcopy(part))
                    continue
                if not isinstance(function, dict):
                    raise AttachmentContextError('工具函数字段格式错误；未执行。')
                cid = function.get('id') or 'call_' + uuid.uuid4().hex
                if not isinstance(cid, str):
                    raise AttachmentContextError('工具调用 ID 格式错误；未执行。')
                previous = next((value for value in self.parts.values() if value['id'] == cid), None)
                if previous is not None:
                    if previous['name'] != function.get('name') or json.loads(previous['raw']) != function.get('args', {}):
                        raise AttachmentContextError('同一工具调用 ID 出现不同参数；未执行。')
                    continue
                self.parts[len(self.parts)] = {'id': cid, 'name': function.get('name', ''),
                                               'raw': json.dumps(function.get('args', {}), ensure_ascii=False)}
                saved = copy.deepcopy(part)
                saved['functionCall']['id'] = cid
                self.continuation.append(saved)
            self.reason = candidates[0].get('finishReason') or self.reason
            if stream and candidates[0].get('finishReason'):
                self._stream_sealed = True
        elif provider == 'claude':
            if not stream:
                self.continuation = copy.deepcopy(data.get('content') or [])
                for index, block in enumerate(self.continuation):
                    if block.get('type') == 'tool_use':
                        self.parts[index] = {'id': block.get('id', ''), 'name': block.get('name', ''),
                                             'raw': json.dumps(block.get('input', {}), ensure_ascii=False)}
                self.reason = data.get('stop_reason')
            else:
                event, index = data.get('type'), self._slot(data.get('index', 0))
                if self.continuation is None:
                    self.continuation = {}
                if event == 'content_block_start':
                    if self._stream_sealed or index in self.continuation:
                        raise AttachmentContextError('工具响应块重复开始或发生在结束之后；未执行。')
                    block = copy.deepcopy(data.get('content_block') or {})
                    self.continuation[index] = block
                    if block.get('type') == 'tool_use':
                        self.parts[index] = {'id': block.get('id', ''), 'name': block.get('name', ''), 'raw': '',
                                             'initial': block.get('input') or {}}
                elif event == 'content_block_delta':
                    delta = data.get('delta') or {}
                    block = self.continuation.get(index, {})
                    if self._stream_sealed or index in self._closed_slots or index not in self.continuation:
                        raise AttachmentContextError('响应分片没有对应的活动内容块；未执行。')
                    if delta.get('type') == 'input_json_delta':
                        if index not in self.parts or self.parts[index].get('initial'):
                            raise AttachmentContextError('工具参数分片与内容块冲突；未执行。')
                        if not isinstance(delta.get('partial_json'), str):
                            raise AttachmentContextError('工具参数分片格式错误；未执行。')
                        self.parts[index]['raw'] += delta.get('partial_json', '')
                    for key in ('text', 'thinking', 'signature'):
                        if key in delta:
                            block[key] = block.get(key, '') + delta[key]
                elif event == 'message_delta':
                    self.reason = (data.get('delta') or {}).get('stop_reason') or self.reason
                    if (data.get('delta') or {}).get('stop_reason'):
                        self._stream_sealed = True
                elif event == 'content_block_stop':
                    if index not in self.continuation:
                        raise AttachmentContextError('结束事件没有对应内容块；未执行。')
                    self._closed_slots.add(index)
        if not stream:
            self.finished = True

    def finalize(self):
        try:
            self._finalize()
        except AttachmentContextError as exc:
            self.parse_state = 'failed'
            self.trace('tool_parse', stage='final_validation', status='failed', error=str(exc)[:2000])
            raise
        self.parse_state = 'validated'
        self.trace('tool_parse', stage='final_validation', status='validated', finish_reason=self.reason)

    def _finalize(self):
        self.calls = []
        if self.invalid_error is not None:
            raise self.invalid_error
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
            if not isinstance(part['id'], str) or not part['id'] or part['id'] in seen:
                raise AttachmentContextError('工具调用 ID 缺失或重复；未执行。')
            if not isinstance(part['name'], str):
                raise AttachmentContextError('工具函数名格式错误；未执行。')
            seen.add(part['id'])
            try:
                args = json.loads(part['raw']) if part['raw'] else part.get('initial', {})
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
                    part = self.parts[index]
                    block['input'] = json.loads(part['raw']) if part['raw'] else part.get('initial', {})
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
        self.trace_writer = None
        self.conversation_id = None
        self.current_outcome = {}
        self.response_policy = None

    def trace(self, event, **fields):
        if not callable(self.trace_writer):
            return
        payload = {'version': 1, 'conversation_id': self.conversation_id, 'run_id': self.run_id,
                   'provider': self.provider_name, 'provider_format': self.provider, 'model': self.model,
                   'agent_call_mode': self.mode, 'capture_id': getattr(self.reply, 'capture_id', None), **fields}
        try:
            self.trace_writer(event, payload)
        except Exception:
            pass  # Diagnostic delivery never changes an operation's result.

    def note_result(self, result):
        if not self.current or not isinstance(result, dict):
            return
        for field in ('success', 'stopped', 'timed_out', 'running'):
            if type(result.get(field)) is bool:
                self.current_outcome[field] = result[field]
        if type(result.get('return_code')) is int:
            self.current_outcome['return_code'] = result['return_code']
        if isinstance(result.get('state'), str) and result['state'] in {'success', 'failed', 'stopped', 'cancelled', 'waiting', 'unknown'}:
            self.current_outcome['state'] = result['state']
        if self.current_outcome:
            self.trace('tool_execution_result', response_id=self.current_response_id,
                       call_id=self.current, **self.current_outcome)

    def claim(self, block):
        cid = block.get('native_call_id')
        if not cid:
            return True
        key = (block.get('native_response_id'), cid)
        if key in self.executed:
            self.trace('tool_dispatch', response_id=block.get('native_response_id'), call_id=cid,
                       tool=TOOL_NAMES.get(block.get('type')), status='duplicate_skipped')
            return False
        self.executed.add(key)
        self.current = cid
        self.current_response_id = block.get('native_response_id')
        self.current_results = []
        self.current_outcome = {}
        self.trace('tool_dispatch', response_id=self.current_response_id, call_id=cid,
                   tool=TOOL_NAMES.get(block.get('type')), status='claimed')
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
                                        'response_id': self.current_response_id, **self.current_outcome}
        self.trace('tool_result_recorded', response_id=self.current_response_id, call_id=self.current,
                   result_messages=len(messages), **self.current_outcome)
        self.current = None
        self.current_response_id = None
        self.current_results = []
        self.current_outcome = {}


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
    return json.dumps({'name': call['name'], 'arguments': call['arguments']}, ensure_ascii=False)


def historical_content(message):
    content = message.get('content', '')
    calls = message.get('native_calls') or []
    if not calls:
        return content
    text = '[历史工具请求，仅供参考，非本次操作；执行情况以对应结果为准]\n' + '\n'.join(_plain_call(call) for call in calls)
    if isinstance(content, list):
        return [*content, {'type': 'text', 'text': text}]
    return (str(content) + '\n' + text).lstrip('\n')


def wire_history(history, session, convert):
    """Replay complete pairs as tools, never as examples of assistant prose.

    Provider continuation belongs only to its original run. Closed historical
    pairs can use the target API's ordinary call/result format without it.
    Incomplete records stay explicitly labelled data with no invented result.
    """
    provider = session.provider
    def key(call):
        return call_key(call)
    results = {key(m.get('native_result', {})) for m in history}

    def complete(message):
        calls, binding = message.get('native_calls'), message.get('native_binding')
        if not isinstance(calls, list) or not calls or not isinstance(binding, (list, tuple)) or len(binding) != 4:
            return False
        seen = set()
        for call in calls:
            if not isinstance(call, dict) or not all(isinstance(call.get(field), str) and call[field]
                    for field in ('run_id', 'response_id', 'id')):
                return False
            identity = key(call)
            if call['run_id'] != binding[-1] or identity in seen or identity not in results:
                return False
            normalized = normalize_history_call(call)
            if normalized.get('name') not in TOOLS or not isinstance(normalized.get('arguments'), dict):
                return False
            seen.add(identity)
        return True

    eligible = {key(c) for m in history if complete(m) for c in m['native_calls']}
    wire_ids = wire_call_ids(history, eligible, provider)
    groups = {}
    for msg in history:
        cid = key(msg.get('native_result', {}))
        if cid in eligible:
            content = msg.get('content', '')
            groups.setdefault(cid, []).extend(content if isinstance(content, list) else [{'type': 'text', 'text': content}])
    emitted, values = set(), []

    def plain_message(role, content):
        if not content:
            return
        role = 'assistant' if role == 'model' else role
        if provider in {'gemini', 'vertex'}:
            values.append({'role': 'model' if role == 'assistant' else 'user', 'parts': convert(content)})
        else:
            values.append({'role': 'user' if provider == 'claude' and role == 'system' else role, 'content': convert(content)})

    for msg in history:
        content = msg.get('content', '')
        calls = msg.get('native_calls') or []
        link = msg.get('native_result') or {}
        if key(link) in eligible:
            continue  # Results were emitted as one complete batch after their call.
        if complete(msg):
            signature = tuple(key(c) for c in calls)
            if signature in emitted:
                continue
            emitted.add(signature)
            calls = [normalize_history_call(c) for c in calls]
            continuation = copy.deepcopy(msg.get('_native_continuation')) if msg.get('native_binding') == session.binding else None
            if provider == 'claude':
                parts = continuation
                if not parts:
                    prose = convert(content) if content else []
                    parts = (prose if isinstance(prose, list) else [{'type': 'text', 'text': prose}]) + [
                        {'type': 'tool_use', 'id': wire_ids[key(c)], 'name': c['name'], 'input': c['arguments']} for c in calls]
                else:
                    ids = {c['id']: wire_ids[key(c)] for c in calls}
                    for part in parts:
                        if part.get('type') == 'tool_use' and part.get('id') in ids:
                            part['id'] = ids[part['id']]
                values.append({'role': 'assistant', 'content': parts})
            elif provider in {'gemini', 'vertex'}:
                parts = continuation or (convert(content) if content else []) + [
                    {'functionCall': {'id': wire_ids[key(c)], 'name': c['name'], 'args': c['arguments']}} for c in calls]
                if continuation:
                    ids = {c['id']: wire_ids[key(c)] for c in calls}
                    for part in parts:
                        function = part.get('functionCall') or {}
                        if function.get('id') in ids:
                            function['id'] = ids[function['id']]
                values.append({'role': 'model', 'parts': parts})
            else:
                values.append({'role': 'assistant', 'content': convert(content) if content else None,
                    'tool_calls': [{'id': wire_ids[key(c)], 'type': 'function', 'function': {
                        'name': c['name'], 'arguments': json.dumps(c['arguments'], ensure_ascii=False)}} for c in calls],
                    **(continuation or {})})
            native_results, assets = [], []
            for call in calls:
                converted = convert(groups[key(call)])
                if provider == 'claude':
                    native_results.append({'type': 'tool_result', 'tool_use_id': wire_ids[key(call)],
                        'content': converted if isinstance(converted, list) else [{'type': 'text', 'text': converted}]})
                elif provider in {'gemini', 'vertex'}:
                    text = '\n'.join(part.get('text', '') for part in converted if 'text' in part)
                    native_results.append({'functionResponse': {'name': call['name'], 'id': wire_ids[key(call)], 'response': {'output': text}}})
                    assets.extend(part for part in converted if 'text' not in part)
                else:
                    text = converted if isinstance(converted, str) else '\n'.join(
                        part.get('text', '') for part in converted if part.get('type') == 'text')
                    values.append({'role': 'tool', 'tool_call_id': wire_ids[key(call)], 'content': text})
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
                plain_message(msg.get('role', 'user'), content)
                plain_message('user', historical_content({'content': '', 'native_calls': calls}))
            else:
                plain_message(msg.get('role', 'user'), content)
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
    response.request_summary = {'defined_tools': len(TOOLS), 'tool_names': list(TOOLS),
                                'history_messages': len(messages), 'history_call_count': sum(
        len(m.get('tool_calls') or []) + sum(part.get('type') == 'tool_use' or bool(part.get('functionCall'))
            for part in (m.get('content') if isinstance(m.get('content'), list) else m.get('parts') or []))
        for m in messages), 'history_result_count': sum(
            (m.get('role') == 'tool') + sum(part.get('type') == 'tool_result' or bool(part.get('functionResponse'))
                for part in (m.get('content') if isinstance(m.get('content'), list) else m.get('parts') or []))
            for m in messages)}


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
            value = None
            try:
                value = await function(*args, **kwargs)
                return ModelReply(value, response) if value is not None else None
            except (asyncio.CancelledError, GeneratorExit):
                response.calls.clear()
                raise
            except Exception as exc:
                response.trace('tool_generation_error', error=str(exc)[:2000], error_type=type(exc).__name__)
                raise
            finally:
                response.trace('tool_response', finish_reason=response.reason, stream_finished=response.finished,
                               parse_state=response.parse_state, request_attempts=response.request_attempts,
                               prose_characters=len(str(value or '')), invalid_stream=response.invalid_error is not None)
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
        from .conversations import current_scope
        scope = current_scope(required=False)
        session.conversation_id = scope.conversation_id if scope else None
        session.trace_writer = ns.get('write_model_trace')
        with session_scope(session):
            turn = ns['current_turn']()
            if resume and session.presentation is not None and turn is not None:
                turn.replies = copy.deepcopy(session.presentation['replies'])
                turn.operations = copy.deepcopy(session.presentation['operations'])
                turn.started_at = session.presentation['started_at']
            return await function(*args, **kwargs)
    return wrapped
