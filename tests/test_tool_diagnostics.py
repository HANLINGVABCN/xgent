"""Diagnostics describe transport and executor facts, never assistant claims."""
import json

from xgent_app.tool_calls import ResponseCapture, ToolSession, operation


def test_capture_and_dispatch_events_keep_id_link_and_omit_arguments():
    events = []
    session = ToolSession('openai', 'p', 'm', 'run')
    session.trace_writer = lambda event, payload: events.append((event, payload))
    session.conversation_id = 'conversation'
    capture = ResponseCapture(session)
    session.reply = capture
    capture.request_summary = {'defined_tools': 16}
    capture.request_attempt()
    capture.observe({'id': 'response', 'choices': [{'message': {'tool_calls': [{
        'id': 'call', 'function': {'name': 'exec_command', 'arguments': '{"command":"ARGUMENT_NOT_FOR_DIAGNOSTICS"}'}}]},
        'finish_reason': 'tool_calls'}]})
    capture.finalize()
    block = operation(capture.calls[0])
    assert session.claim(block)
    session.note_result({'success': False, 'return_code': 3, 'state': 'failed', 'output': 'OUTPUT_NOT_FOR_DIAGNOSTICS'})
    history = []
    session.finish(history, text='ORIGINAL_RESULT')
    assert history[0]['native_result']['return_code'] == 3
    assert history[0]['native_result']['success'] is False
    assert not session.claim(block)
    encoded = json.dumps(events)
    assert 'ARGUMENT_NOT_FOR_DIAGNOSTICS' not in encoded and 'OUTPUT_NOT_FOR_DIAGNOSTICS' not in encoded
    assert all(data['run_id'] == 'run' and data['conversation_id'] == 'conversation' for _, data in events)
    assert all(data['capture_id'] == capture.capture_id for _, data in events)
    assert [event for event, _ in events] == ['tool_request', 'tool_parse', 'tool_dispatch',
        'tool_execution_result', 'tool_result_recorded', 'tool_dispatch']
    assert events[-1][1]['status'] == 'duplicate_skipped'


def test_diagnostic_writer_failure_cannot_change_execution_or_results():
    session = ToolSession('openai', 'p', 'm', 'run')
    def fail(*args):
        raise OSError('log unavailable')
    session.trace_writer = fail
    block = {'type': 'run', 'native_call_id': 'call', 'native_response_id': 'response'}
    assert session.claim(block)
    session.note_result({'success': True, 'state': 'success'})
    history = []
    session.finish(history, text='ACTUAL_RESULT')
    assert history[0]['content'] == 'ACTUAL_RESULT' and history[0]['native_result']['success'] is True
