"""Actual application pipelines against deterministic provider transports."""
import json
from pathlib import Path
from unittest.mock import patch

import httpx

from tests.attachment_request_probe import Harness, MODEL, URL


class NativeHarness(Harness):
    def __init__(self, bot, root, fmt, style):
        super().__init__(bot, root)
        self.fmt, self.style = fmt, style
        self.responses = []
        self.executed = []

    async def __aenter__(self):
        await super().__aenter__()
        await self.db.save_provider('p', URL, 'test-key', [MODEL], api_format=self.fmt)
        await self.bot.UserDataManager.reload_providers()
        for name, value in [('agent_mode', True), ('agent_call_mode', 'toolcall'), ('global_depth', 30),
                            ('stream_mode', self.style != 'nonstream'),
                            ('stream_style', 'background' if self.style == 'background' else 'foreground')]:
            await self.bot.UserDataManager.save_config(name, value)

        async def run(command, stop_event=None):
            self.executed.append(command)
            return {'success': True, 'return_code': 0, 'output': 'ACTUAL_RESULT: 17 GiB free',
                    'output_path': str(self.root / 'output.txt')}
        self.stack.enter_context(patch.object(self.bot.AgentExecutor, 'run_command', side_effect=run))
        self.stack.enter_context(patch.object(self.bot, 'build_trigger_delivery_bot', return_value=self.context.bot))
        return self

    def respond(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        self.request_bytes.append(request.content)
        calls, text = self.responses.pop(0) if self.responses else ([], 'FINAL_ANSWER')
        stream = body.get('stream') or 'streamGenerateContent' in str(request.url)
        usage = {'prompt_tokens': 123, 'completion_tokens': 19, 'total_tokens': 142}
        if self.fmt in {'openai', 'openai_compatible'}:
            message = {'role': 'assistant', 'content': text or None}
            if calls:
                message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                    'name': c['name'], 'arguments': json.dumps(c['arguments'], ensure_ascii=False)}} for c in calls]
            reason = 'tool_calls' if calls else 'stop'
            if not stream:
                return httpx.Response(200, json={'id': f'resp-{len(self.requests)}', 'object': 'chat.completion', 'created': 1,
                    'model': MODEL, 'choices': [{'index': 0, 'message': message, 'finish_reason': reason}], 'usage': usage})
            events = []
            if text:
                events.append({'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': None}]})
            for index, c in enumerate(calls):
                raw = json.dumps(c['arguments'], ensure_ascii=False)
                for step, fragment in enumerate([raw[:7], raw[7:23], raw[23:]]):
                    function = {'arguments': fragment, **({'name': c['name']} if step == 0 else {})}
                    events.append({'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': index, 'type': 'function',
                        **({'id': c['id']} if step == 0 else {}), 'function': function}]}, 'finish_reason': None}]})
            events.append({'choices': [{'index': 0, 'delta': {}, 'finish_reason': reason}], 'usage': usage})
            for e in events:
                e.update(id=f'resp-{len(self.requests)}', object='chat.completion.chunk', created=1, model=MODEL)
        elif self.fmt in {'gemini', 'vertex'}:
            parts = ([{'text': text}] if text else []) + [{'functionCall': {
                'id': c['id'], 'name': c['name'], 'args': c['arguments']}, 'thoughtSignature': 'provider-signature'} for c in calls]
            value = {'candidates': [{'content': {'role': 'model', 'parts': parts}, 'finishReason': 'STOP'}],
                     'usageMetadata': {'promptTokenCount': 123, 'candidatesTokenCount': 19, 'totalTokenCount': 142}}
            if not stream:
                return httpx.Response(200, json=value)
            events = [value]
        else:
            content = ([{'type': 'text', 'text': text}] if text else []) + [
                {'type': 'tool_use', 'id': c['id'], 'name': c['name'], 'input': c['arguments']} for c in calls]
            reason = 'tool_use' if calls else 'end_turn'
            if not stream:
                return httpx.Response(200, json={'id': f'resp-{len(self.requests)}', 'type': 'message', 'role': 'assistant',
                    'model': MODEL, 'content': content, 'stop_reason': reason,
                    'usage': {'input_tokens': 123, 'output_tokens': 19}})
            events = [{'type': 'message_start', 'message': {'id': f'resp-{len(self.requests)}', 'role': 'assistant',
                       'usage': {'input_tokens': 123}}}]
            for index, block in enumerate(content):
                if block['type'] == 'text':
                    events.extend([{'type': 'content_block_start', 'index': index, 'content_block': {'type': 'text', 'text': ''}},
                        {'type': 'content_block_delta', 'index': index, 'delta': {'type': 'text_delta', 'text': text}}])
                else:
                    raw = json.dumps(block['input'], ensure_ascii=False)
                    events.append({'type': 'content_block_start', 'index': index, 'content_block': {**block, 'input': {}}})
                    events.extend({'type': 'content_block_delta', 'index': index, 'delta': {
                        'type': 'input_json_delta', 'partial_json': fragment}} for fragment in [raw[:11], raw[11:]])
                events.append({'type': 'content_block_stop', 'index': index})
            events.extend([{'type': 'message_delta', 'delta': {'stop_reason': reason}, 'usage': {'output_tokens': 19}},
                           {'type': 'message_stop'}])
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              content=''.join('data: ' + json.dumps(e) + '\n\n' for e in events) + 'data: [DONE]\n\n')


def call(name='exec_command', cid='call-a', **arguments):
    return {'name': name, 'id': cid, 'arguments': arguments}


async def exercise(bot, root, fmt, style):
    command = "printf 'one\\ntwo'\n  echo 中文\n"
    async with NativeHarness(bot, root, fmt, style) as h:
        h.responses = [([call(command=command)], ''), ([], 'FINAL_ANSWER')]
        await h.turn('inspect machine')
        assert h.executed == [command], h.executed
        assert len(h.requests) == 2, h.requests
        assert h.requests[0]['tools']
        encoded = json.dumps(h.requests[1], ensure_ascii=False)
        assert 'ACTUAL_RESULT' in encoded and ('tool_call_id' in encoded or 'functionResponse' in encoded or 'tool_result' in encoded)
        if fmt in {'gemini', 'vertex'}:
            assert 'provider-signature' in encoded
        rows = await h.db.get_display_history(100)
        native = [r for r in rows if r.get('msg_type') == 'ai_reply' and r.get('metadata', {}).get('native_calls')]
        assert len(native) == 1 and native[0]['content'] == '', native
        history = await h.db.get_conversation_messages(100)
        assert any(m.get('native_calls') for m in history)
        assert any(m.get('native_result') for m in history)
        assert not any(r.get('msg_type') == 'runtime_error' for r in rows), rows
        assert any(r.get('content') == 'FINAL_ANSWER' for r in rows)
        return {'format': fmt, 'style': style, 'requests': len(h.requests), 'executions': len(h.executed)}


async def form_sequence(bot, root, fmt, cancel=False):
    async with NativeHarness(bot, root, fmt, 'nonstream') as h:
        questions = [{'label': 'Q1', 'type': 'text', 'prompt': 'confirm label'}]
        h.responses = [([call(cid='before', command='before'), call('ask_user', 'form', questions=questions),
                         call(cid='after', command='after')], 'ASK_STAGE'), ([], 'AFTER_FORM')]
        await h.turn('form workflow')
        assert h.executed == ['before'] and len(h.requests) == 1
        pending = next(iter(bot.PENDING_ASKS._store.values()))
        pending.ensure_entry('0')['custom'] = 'MY_ANSWER'
        # Switching global mode during the form must not change its continuation.
        await bot.UserDataManager.save_config('agent_call_mode', 'fence')
        if cancel:
            await bot.cancel_ask(pending.ask_id)
            assert h.executed == ['before']
        else:
            await bot.resume_from_ask(pending.ask_id)
            assert h.executed == ['before', 'after']
        assert len(h.requests) == 2
        assert h.requests[-1]['tools']
        final = json.dumps(h.requests[-1], ensure_ascii=False)
        assert ('MY_ANSWER' if not cancel else '用户已取消') in final
        rows = await h.db.get_display_history(100)
        assert not any(r['msg_type'] == 'runtime_error' for r in rows), rows
        assert any(r['content'] == 'AFTER_FORM' for r in rows)
        return {'ordered': True, 'pinned': True, 'cancel': cancel}


async def over_and_fence(bot, root, mode):
    async with NativeHarness(bot, root, 'openai', 'nonstream') as h:
        if mode == 'over':
            h.responses = [([call(command='save'), call('finish_task', 'finish', message='See actual output.')], '')]
            await h.turn('save and end')
            assert len(h.requests) == 1 and h.executed == ['save']
            history = await h.db.get_conversation_messages(100)
            assert {m.get('native_result', {}).get('id') for m in history} >= {'call-a', 'finish'}
        elif mode == 'fence':
            await bot.UserDataManager.save_config('agent_call_mode', 'fence')
            h.responses = [([], '```run-x\n<<BEGIN_run_test000\nfence-command\n<<END_run_test000\n```'),
                           ([], 'FENCE_RESULT')]
            await h.turn('use fence')
            assert h.executed == ['fence-command'] and not h.requests[0].get('tools')
        else:
            h.responses = [([], '```run-x\n<<BEGIN_run_test000\nexample-only\n<<END_run_test000\n```')]
            await h.turn('explain')
            assert h.executed == [] and len(h.requests) == 1
        return {'mode': mode, 'executed': len(h.executed), 'requests': len(h.requests)}


async def stop_between_calls(bot, root):
    async with NativeHarness(bot, root, 'openai', 'nonstream') as h:
        async def stopped(command, stop_event):
            h.executed.append(command)
            stop_event.set()
            return {'success': False, 'stopped': True, 'return_code': -1, 'output': 'PARTIAL_OUTPUT'}
        with patch.object(bot.AgentExecutor, 'run_command', side_effect=stopped):
            h.responses = [([call(cid='first', command='first'), call(cid='second', command='second')], '')]
            await h.turn('stop workflow')
        assert h.executed == ['first'] and len(h.requests) == 1
        rows = await h.db.get_display_history(100)
        terminal = [r for r in rows if r['msg_type'] == 'agent_status' and '已停止' in r['content']]
        assert len(terminal) == 1, terminal
        assert any('PARTIAL_OUTPUT' in r['content'] for r in rows)
        return {'only_first': True, 'one_terminal': True}


async def native_file_bytes(bot, root):
    from xgent_app.agent_files import write_text_protocol_file, write_base64_protocol_file
    from xgent_app.agent_dispatch import dispatch_standard_protocol
    from xgent_app.tool_calls import operation
    import base64
    async with NativeHarness(bot, root, 'openai', 'nonstream') as h:
        path = h.root / 'raw.txt'
        original = '  leading\r\n中文\n\ttrailing  \n'
        block = operation(call('write_file', path=str(path), content=original))
        await write_text_protocol_file(block, executor=bot.AgentExecutor)
        assert path.read_bytes() == original.encode('utf-8')
        changed = 'REPLACED\r\n'
        block = operation(call('edit_file', path=str(path), old='中文\n', new=changed))
        result = await dispatch_standard_protocol(block, executor=bot.AgentExecutor, provider_api_format='openai',
            stop_event_factory=bot.asyncio.Event, logger=bot.logger)
        assert result['success'] and path.read_bytes() == original.replace('中文\n', changed).encode('utf-8')
        binary = h.root / 'binary.bin'
        raw = b'\x00\xff\x01binary\x00'
        await write_base64_protocol_file(operation(call('write_binary', path=str(binary),
            base64_data=base64.b64encode(raw).decode())), executor=bot.AgentExecutor)
        assert binary.read_bytes() == raw
        return {'file_bytes': True, 'edit_bytes': True, 'binary_bytes': True}


async def compare_modes(bot, root):
    import time
    from xgent_app.presentation import metadata_dict
    values = []
    for mode in ('toolcall', 'fence'):
        async with NativeHarness(bot, Path(root) / mode, 'openai', 'nonstream') as h:
            await bot.UserDataManager.save_config('agent_call_mode', mode)
            command = 'inspect-memory'
            h.responses = [([call(command=command)], '') if mode == 'toolcall' else
                ([], '```run-x\n<<BEGIN_run_compare\n' + command + '\n<<END_run_compare\n```'),
                ([], 'SAME_FINAL_ANSWER')]
            began = time.monotonic()
            await h.turn('Check available memory and summarize.')
            elapsed = time.monotonic() - began
            rows = await h.db.get_display_history(100)
            usage = [metadata_dict(r['metadata'])['usage'] for r in rows if r['msg_type'] == 'token_usage']
            values.append({'mode': mode, 'requests': len(h.requests), 'executed': list(h.executed),
                'input_tokens': sum(item['input_tokens'] for item in usage),
                'output_tokens': sum(item['output_tokens'] for item in usage), 'elapsed_seconds': elapsed,
                'measurement': 'deterministic_mock_usage'})
    return values


async def form_then_new_over(bot, root):
    async with NativeHarness(bot, root, 'openai', 'nonstream') as h:
        h.responses = [([call('ask_user', 'ask', questions=[{'label': 'Q1', 'type': 'text', 'prompt': 'Value?'}]),
                         call(cid='after-ask', command='after-ask')], 'FORM'),
                        ([call(cid='new-round', command='new-round'),
                          call('finish_task', 'finish', message='See actual results.')], 'LAST_REPLY')]
        await h.turn('ask then finish')
        pending = next(iter(bot.PENDING_ASKS._store.values()))
        pending.ensure_entry('0')['custom'] = 'CONFIRMED'
        await bot.resume_from_ask(pending.ask_id)
        assert len(h.requests) == 2, h.requests
        assert h.executed == ['after-ask', 'new-round']
        return {'requests': len(h.requests), 'new_over': True}


async def unsupported_mode(bot, root, code):
    async with NativeHarness(bot, root, 'openai_compatible', 'nonstream') as h:
        def respond(request):
            h.requests.append(json.loads(request.content))
            message = 'tools is not supported by this model' if code == 400 else 'rate limit exceeded: original upstream error'
            return httpx.Response(code, json={'error': {'message': message}})
        h.http._transport = httpx.MockTransport(respond)
        await h.turn('unsupported tool call')
        assert len(h.requests) == 1 and h.requests[0].get('tools')
        assert not h.executed
        rows = await h.db.get_display_history(100)
        errors = [r for r in rows if r['msg_type'] == 'runtime_error']
        assert len(errors) == 1, rows
        assert ('tools is not supported' if code == 400 else 'rate limit exceeded') in errors[0]['content']
        assert ('切换“正则围栏”' in errors[0]['content']) == (code == 400)
        assert await h.db.get_config_fresh('agent_call_mode') == 'toolcall'
        return {'original_error': True, 'no_fallback': True}
