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
    capture = envelope(ResponseCapture(session), [{'id': 'call-a', 'function': {'name': 'read_x',
        'arguments': '{"body":"/tmp/source.png"}'}}])
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
    capture = envelope(ResponseCapture(session), [{'id': value, 'function': {'name': 'run_x', 'arguments': '{"body":"pwd"}'}}
                                                 for value in ('call-a', 'call-b')])
    history = [capture.message(''), {'role': 'user', 'content': 'result', 'native_result': {'id': 'call-a', 'response_id': capture.response_id}}]
    wire = wire_history(history, session, lambda content: content)
    assert not any(item.get('tool_calls') or item.get('role') == 'tool' for item in wire)
    assert 'run_x' in wire[0]['content']
    history[0]['native_binding'][-1] = 'older-run'
    assert all(item['role'] != 'tool' for item in wire_history(history, session, lambda content: content))


def test_fragmented_unicode_arguments_only_execute_after_complete_valid_finish():
    session = ToolSession('openai', 'p', 'm', 'run')
    capture = ResponseCapture(session)
    raw = json.dumps({'body': 'echo 中文\n  printf "$HOME"\n'}, ensure_ascii=False)
    for index, fragment in enumerate([raw[:15], raw[15:24], raw[24:]]):
        capture.observe({'choices': [{'delta': {'tool_calls': [{'index': 0,
            **({'id': 'a'} if index == 0 else {}), 'function': {**({'name': 'run_x'} if index == 0 else {}),
                                                            'arguments': fragment}}]}}]}, stream=True)
    with pytest.raises(AttachmentContextError, match='未正常结束'):
        capture.finalize()
    capture.finished, capture.reason = True, 'tool_calls'
    capture.finalize()
    block = operation(capture.calls[0])
    assert block['body'] == 'echo 中文\n  printf "$HOME"\n'
    assert session.claim(block) and not session.claim(block)


@pytest.mark.parametrize('arguments, reason', [('{', 'tool_calls'), ('{}', 'tool_calls'), ('{"body":"pwd"}', 'length')])
def test_invalid_or_truncated_calls_never_become_operations(arguments, reason):
    capture = ResponseCapture(ToolSession('openai', 'p', 'm', 'r'))
    with pytest.raises(AttachmentContextError):
        envelope(capture, [{'id': 'a', 'function': {'name': 'run_x', 'arguments': arguments}}], finish=reason)
    assert capture.calls == []


def test_all_existing_tools_have_provider_definitions():
    expected = {'run_x', 'shell_x', 'stdin_x', 'shellkill_x', 'read_x', 'grep_x', 'intel_x', 'search_x', 'fetch_x',
                'sendfile_x', 'media_x', 'over_x', 'file_x', 'file_base64_x', 'edit_x', 'ask_x'}
    assert {item['function']['name'] for item in definitions('openai')} == expected
    assert {item['name'] for item in definitions('claude')} == expected
    assert {item['name'] for item in definitions('gemini')[0]['functionDeclarations']} == expected


def test_required_provider_continuation_is_not_persisted_or_reused_across_models():
    from xgent_app.tool_calls import metadata
    session = ToolSession('openai', 'p', 'm', 'run')
    capture = ResponseCapture(session)
    capture.observe({'choices': [{'message': {'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'opaque-provider-only'}],
        'tool_calls': [{'id': 'a', 'function': {'name': 'run_x', 'arguments': '{"body":"pwd"}'}}]},
        'finish_reason': 'tool_calls'}]})
    capture.finalize()
    message = capture.message('')
    result = {'role': 'user', 'content': 'output', 'native_result': {'id': 'a', 'response_id': capture.response_id}}
    assert 'opaque-provider-only' in json.dumps(wire_history([message, result], session, lambda content: content))
    assert 'opaque-provider-only' not in json.dumps(metadata(capture))
    other = ToolSession('openai', 'p', 'other-model', 'different-run')
    assert 'opaque-provider-only' not in json.dumps(wire_history([message, result], other, lambda content: content))


def test_mode_specific_prompt_keeps_custom_fence_rules():
    from pathlib import Path
    from xgent_app.tool_calls import select_prompt
    root = Path(__file__).resolve().parents[1]
    original = (root / 'prompts/agent_addon.txt').read_text(encoding='utf-8')
    native = (root / 'prompts/toolcall_addon.txt').read_text(encoding='utf-8')
    assert select_prompt(original, native) == native
    custom = original + '\nCUSTOM_USER_RULE'
    assert custom in select_prompt(custom, native)


def test_parallel_results_precede_native_assets_and_rich_fallback_is_legacy_html():
    from xgent_app.native_rendering import rich_calls
    session = ToolSession('openai', 'p', 'm', 'run')
    capture = envelope(ResponseCapture(session), [{'id': cid, 'function': {'name': 'read_x', 'arguments': '{"body":"a.png"}'}}
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
