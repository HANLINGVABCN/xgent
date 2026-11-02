"""Reject conflicting transport metadata without modifying command arguments."""
import json

import pytest

from xgent_app.attachments import AttachmentContextError
from xgent_app.tool_calls import ResponseCapture, ToolSession


def delta(capture, index=0, *, cid=None, name=None, arguments='', response_id='response'):
    function = {'arguments': arguments}
    if name is not None:
        function['name'] = name
    call = {'index': index, 'function': function}
    if cid is not None:
        call['id'] = cid
    capture.observe({'id': response_id, 'choices': [{'delta': {'tool_calls': [call]}}]}, stream=True)


@pytest.mark.parametrize('conflict', ['id', 'name', 'response_id', 'index'])
def test_conflicting_identity_or_index_invalidates_entire_batch(conflict):
    capture = ResponseCapture(ToolSession('openai', 'p', 'm', 'run'))
    delta(capture, cid='first', name='exec_command', arguments='{"command":')
    values = {'arguments': '"synthetic-only"}'}
    values.update({'cid': 'different'} if conflict == 'id' else
                  {'name': 'write_file'} if conflict == 'name' else
                  {'response_id': 'different-response'} if conflict == 'response_id' else {'index': -1})
    with pytest.raises(AttachmentContextError, match='未执行'):
        delta(capture, **values)
    capture.finished, capture.reason = True, 'tool_calls'
    with pytest.raises(AttachmentContextError):
        capture.finalize()
    assert capture.calls == []


def test_fragmented_name_and_interleaved_arguments_keep_exact_order_and_bytes():
    capture = ResponseCapture(ToolSession('openai', 'p', 'm', 'run'))
    command = '  printf "中文"\n\tprintf "aaaa"\n'
    raw = json.dumps({'command': command}, ensure_ascii=False)
    delta(capture, 1, cid='second', name='exec_command', arguments='{"command":"two"}')
    delta(capture, 0, cid='first', name='exec_', arguments=raw[:13])
    delta(capture, 0, name='command', arguments=raw[13:])
    capture.finished, capture.reason = True, 'tool_calls'
    capture.finalize()
    assert [call['id'] for call in capture.calls] == ['first', 'second']
    assert capture.calls[0]['arguments']['command'] == command


def test_parameter_fragment_after_finished_event_cannot_create_a_new_call():
    capture = ResponseCapture(ToolSession('openai', 'p', 'm', 'run'))
    delta(capture, cid='one', name='exec_command', arguments='{"command":"synthetic-only"}')
    capture.observe({'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]}, stream=True)
    with pytest.raises(AttachmentContextError):
        delta(capture, index=1, cid='late', name='exec_command', arguments='{"command":"late"}')
    assert capture.calls == []


@pytest.mark.parametrize('conflict', ['duplicate_start', 'missing_start', 'after_stop'])
def test_claude_blocks_cannot_reset_or_misplace_partial_parameters(conflict):
    capture = ResponseCapture(ToolSession('claude', 'p', 'm', 'run'))
    start = {'type': 'content_block_start', 'index': 0, 'content_block': {
        'type': 'tool_use', 'id': 'one', 'name': 'exec_command', 'input': {}}}
    capture.observe(start, 'claude', stream=True)
    if conflict == 'after_stop':
        capture.observe({'type': 'content_block_stop', 'index': 0}, 'claude', stream=True)
    event = start if conflict == 'duplicate_start' else {'type': 'content_block_delta',
        'index': 1 if conflict == 'missing_start' else 0,
        'delta': {'type': 'input_json_delta', 'partial_json': '{"command":"synthetic-only"}'}}
    with pytest.raises(AttachmentContextError):
        capture.observe(event, 'claude', stream=True)
    assert capture.calls == []


def test_claude_full_initial_input_without_delta_remains_supported():
    capture = ResponseCapture(ToolSession('claude', 'p', 'm', 'run'))
    capture.observe({'type': 'content_block_start', 'index': 0, 'content_block': {
        'type': 'tool_use', 'id': 'one', 'name': 'exec_command', 'input': {'command': 'exact\n'}}}, 'claude', stream=True)
    capture.observe({'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}}, 'claude', stream=True)
    capture.finished = True
    capture.finalize()
    assert capture.calls[0]['arguments']['command'] == 'exact\n'


def test_gemini_duplicate_call_is_not_replayed_twice_and_missing_ids_link_results():
    from xgent_app.tool_calls import wire_history
    session = ToolSession('gemini', 'p', 'm', 'run')
    capture = ResponseCapture(session)
    part = {'functionCall': {'id': 'one', 'name': 'exec_command', 'args': {'command': 'synthetic-only'}},
            'thoughtSignature': 'same-provider-signature'}
    for _ in range(2):
        capture.observe({'candidates': [{'content': {'parts': [part]}}]}, 'gemini', stream=True)
    capture.finished, capture.reason = True, 'STOP'
    capture.finalize()
    assert len(capture.calls) == len(capture.continuation) == 1
    history = [capture.message(''), {'role': 'user', 'content': 'ACTUAL_RESULT', 'native_result': {
        'id': 'one', 'run_id': 'run', 'response_id': capture.response_id}}]
    wire = wire_history(history, session, lambda value: value)
    assert len(wire[0]['parts']) == 1 and wire[0]['parts'][0]['thoughtSignature'] == 'same-provider-signature'
    unsigned = ResponseCapture(session)
    unsigned.observe({'candidates': [{'content': {'parts': [{'functionCall': {
        'name': 'exec_command', 'args': {'command': 'synthetic-only'}}}]}, 'finishReason': 'STOP'}]}, 'gemini')
    unsigned.finalize()
    assert unsigned.continuation[0]['functionCall']['id'] == unsigned.calls[0]['id']


@pytest.mark.parametrize('field,value', [('id', ['invalid']), ('name', ['exec_command'])])
def test_invalid_claude_call_field_types_report_validation_error_without_execution(field, value):
    capture = ResponseCapture(ToolSession('claude', 'p', 'm', 'run'))
    block = {'type': 'tool_use', 'id': 'one', 'name': 'exec_command', 'input': {'command': 'synthetic-only'}, field: value}
    capture.observe({'content': [block], 'stop_reason': 'tool_use'}, 'claude')
    with pytest.raises(AttachmentContextError, match='未执行'):
        capture.finalize()
    assert capture.calls == []
