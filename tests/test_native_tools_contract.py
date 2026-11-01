import copy
import json

import pytest

from xgent_app.attachments import AttachmentContextError
from xgent_app.tool_calls import ResponseCapture, ToolSession, definitions, operation, wire_history


def envelope(capture, calls, *, finish='tool_calls'):
    capture.observe({'choices': [{'message': {'tool_calls': calls}, 'finish_reason': finish}]})
    capture.finalize()
    return capture


def test_call_and_result_are_one_complete_pair_and_multimodal_parts_survive():
    session = ToolSession('openai', 'provider', 'model', 'run-1')
    capture = envelope(ResponseCapture(session), [{'id': 'call-a', 'function': {'name': 'read_file',
        'arguments': '{"path":"/tmp/source.png"}'}}])
    image = {'type': 'image', 'mime_type': 'image/png', 'data': 'abc'}
    result = {'id': 'call-a', 'response_id': capture.response_id}
    history = [capture.message(''), {'role': 'user', 'content': 'first', 'native_result': result},
        {'role': 'user', 'content': [{'type': 'text', 'text': 'second'}, image], 'native_result': result}]
    before = copy.deepcopy(history)
    wire = wire_history(history, session, lambda content: content)
    assert [item['role'] for item in wire] == ['assistant', 'tool', 'user']
    assert wire[1]['content'] == 'first\nsecond'
    assert wire[2]['content'] == [image]
    assert history == before


def test_incomplete_or_old_pairs_become_history_data_without_orphan_results():
    session = ToolSession('openai', 'provider', 'model', 'run-1')
    capture = envelope(ResponseCapture(session), [{'id': value, 'function': {'name': 'exec_command', 'arguments': '{"command":"pwd"}'}}
                                                 for value in ('call-a', 'call-b')])
    history = [capture.message(''), {'role': 'user', 'content': 'result', 'native_result': {'id': 'call-a', 'response_id': capture.response_id}}]
    wire = wire_history(history, session, lambda content: content)
    assert not any(item.get('tool_calls') or item.get('role') == 'tool' for item in wire)
    assert 'exec_command' in wire[0]['content']
    history[0]['native_binding'][-1] = 'older-run'
    assert all(item['role'] != 'tool' for item in wire_history(history, session, lambda content: content))


def test_fragmented_unicode_arguments_only_execute_after_complete_valid_finish():
    session = ToolSession('openai', 'p', 'm', 'run')
    capture = ResponseCapture(session)
    raw = json.dumps({'command': 'echo 中文\n  printf "$HOME"\n'}, ensure_ascii=False)
    for index, fragment in enumerate([raw[:15], raw[15:24], raw[24:]]):
        capture.observe({'choices': [{'delta': {'tool_calls': [{'index': 0,
            **({'id': 'a'} if index == 0 else {}), 'function': {**({'name': 'exec_command'} if index == 0 else {}),
                                                            'arguments': fragment}}]}}]}, stream=True)
    with pytest.raises(AttachmentContextError, match='未正常结束'):
        capture.finalize()
    capture.finished, capture.reason = True, 'tool_calls'
    capture.finalize()
    block = operation(capture.calls[0])
    assert block['body'] == 'echo 中文\n  printf "$HOME"\n'
    assert session.claim(block) and not session.claim(block)


@pytest.mark.parametrize('arguments, reason', [('{', 'tool_calls'), ('{}', 'tool_calls'), ('{"command":"pwd"}', 'length')])
def test_invalid_or_truncated_calls_never_become_operations(arguments, reason):
    capture = ResponseCapture(ToolSession('openai', 'p', 'm', 'r'))
    with pytest.raises(AttachmentContextError):
        envelope(capture, [{'id': 'a', 'function': {'name': 'exec_command', 'arguments': arguments}}], finish=reason)
    assert capture.calls == []


def test_all_existing_tools_have_provider_definitions():
    expected = {'exec_command', 'start_terminal', 'terminal_input', 'close_terminal', 'read_file', 'search_files', 'inspect_code', 'search_web', 'fetch_urls',
                'send_file', 'generate_media', 'finish_task', 'write_file', 'write_binary', 'edit_file', 'ask_user'}
    assert {item['function']['name'] for item in definitions('openai')} == expected
    assert {item['name'] for item in definitions('claude')} == expected
    assert {item['name'] for item in definitions('gemini')[0]['functionDeclarations']} == expected


def test_required_provider_continuation_is_not_persisted_or_reused_across_models():
    from xgent_app.tool_calls import metadata
    session = ToolSession('openai', 'p', 'm', 'run')
    capture = ResponseCapture(session)
    capture.observe({'choices': [{'message': {'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'opaque-provider-only'}],
        'tool_calls': [{'id': 'a', 'function': {'name': 'exec_command', 'arguments': '{"command":"pwd"}'}}]},
        'finish_reason': 'tool_calls'}]})
    capture.finalize()
    message = capture.message('')
    result = {'role': 'user', 'content': 'output', 'native_result': {'id': 'a', 'response_id': capture.response_id}}
    assert 'opaque-provider-only' in json.dumps(wire_history([message, result], session, lambda content: content))
    assert 'opaque-provider-only' not in json.dumps(metadata(capture))
    other = ToolSession('openai', 'p', 'other-model', 'different-run')
    assert 'opaque-provider-only' not in json.dumps(wire_history([message, result], other, lambda content: content))


def test_native_default_uses_only_function_names_and_matches_initializer():
    from pathlib import Path
    from xgent_app.prompt_defaults import DEFAULT_TOOLCALL_PROMPT, DEFAULT_GLOBAL_PROMPT
    root = Path(__file__).resolve().parents[1]
    native = (root / 'prompts/toolcall_addon.txt').read_text(encoding='utf-8')
    assert native == DEFAULT_TOOLCALL_PROMPT
    assert (root / 'prompts/global_addon.txt').read_text(encoding='utf-8') == DEFAULT_GLOBAL_PROMPT
    for old_instruction in ('本环境没有原生工具', '同一回复必须有对应块', 'OLD 块', 'run-x', 'read-x', 'file-x', '第 16 项'):
        assert old_instruction not in native


def test_parallel_results_precede_native_assets_and_rich_fallback_is_legacy_html():
    from xgent_app.native_rendering import rich_calls
    session = ToolSession('openai', 'p', 'm', 'run')
    capture = envelope(ResponseCapture(session), [{'id': cid, 'function': {'name': 'read_file', 'arguments': '{"path":"a.png"}'}}
                                                 for cid in ('a', 'b')])
    history = [capture.message('')]
    image = {'type': 'image', 'data': 'base64', 'mime_type': 'image/png'}
    history.extend({'role': 'user', 'content': [{'type': 'text', 'text': cid}, image],
        'native_result': {'id': cid, 'response_id': capture.response_id}} for cid in ('a', 'b'))
    wire = wire_history(history, session, lambda value: value)
    assert [item['role'] for item in wire] == ['assistant', 'tool', 'tool', 'user']
    assert wire[-1]['content'] == [image, image]
    rich, fallback = rich_calls('A short **answer**', capture.calls, details='<blockquote expandable>details</blockquote>')
    assert '<blockquote expandable>' in ''.join(rich)
    assert '<p>' not in ''.join(fallback) and '<br>' not in ''.join(fallback)


def test_native_names_and_parameters_cover_every_existing_execution_capability():
    cases = [
        ('exec_command', {'command': 'echo hi\n'}, 'run', 'echo hi\n'),
        ('start_terminal', {'command': 'bash'}, 'shell', 'bash'),
        ('terminal_input', {'session_id': 'actual-id', 'input': 'line: hello\nwait: 1'}, 'stdin', 'line: hello\nwait: 1'),
        ('close_terminal', {'session_id': 'actual-id'}, 'shellkill', ''),
        ('read_file', {'path': '/tmp/a:1-20'}, 'read', '/tmp/a:1-20'),
        ('search_files', {'query': 'needle\npath: src'}, 'grep', 'needle\npath: src'),
        ('inspect_code', {'request': 'context my_function'}, 'intel', 'context my_function'),
        ('search_web', {'query': 'topic\nmax: 3'}, 'search', 'topic\nmax: 3'),
        ('fetch_urls', {'urls': ['https://example.com', 'https://example.org']}, 'fetch', 'https://example.com\nhttps://example.org'),
        ('write_file', {'path': '/tmp/a', 'content': '  exact\n'}, 'file', '  exact\n'),
        ('write_binary', {'path': '/tmp/a', 'base64_data': 'AA=='}, 'file_base64', 'AA=='),
        ('send_file', {'path': '/tmp/a'}, 'sendfile', '/tmp/a'),
        ('generate_media', {'prompt': 'file: is ordinary prompt text\nnext line'}, 'media', 'prompt: file: is ordinary prompt text\nnext line'),
        ('finish_task', {'message': 'See output.'}, 'over', 'See output.'),
    ]
    for name, arguments, kind, body in cases:
        block = operation({'id': name, 'name': name, 'arguments': arguments})
        assert block['type'] == kind and block['body'] == body
    block = operation({'id': 'edit', 'name': 'edit_file', 'arguments': {'path': '/tmp/a', 'old': ' a\r\n', 'new': ' b\r\n'}})
    assert block['native_edit'] == (' a\r\n', ' b\r\n')
    block = operation({'id': 'ask', 'name': 'ask_user', 'arguments': {'questions': [{'label': 'Q1', 'type': 'text', 'prompt': 'value?'}]}})
    assert block['ask_form'].questions[0].prompt == 'value?'


def test_old_saved_call_is_displayable_but_cannot_be_executed_as_new_provider_input():
    from xgent_app.tool_calls import display_operation, historical_content
    old = {'id': 'old', 'name': 'run_x', 'arguments': {'body': 'old command'}}
    assert display_operation(old)['body'] == 'old command'
    assert 'exec_command' in historical_content({'content': '', 'native_calls': [old]})
    with pytest.raises(AttachmentContextError, match='未知工具'):
        operation(old)
    with pytest.raises(AttachmentContextError, match='网页地址'):
        operation({'id': 'bad', 'name': 'fetch_urls', 'arguments': {'urls': ['not-a-url']}})
