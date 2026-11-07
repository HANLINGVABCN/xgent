import pytest

from tests.test_thinking_params import run_in_app


@pytest.mark.parametrize('fmt', ['openai', 'openai_compatible', 'gemini', 'vertex', 'claude'])
@pytest.mark.parametrize('style', ['nonstream', 'foreground', 'background'])
def test_native_tool_call_round_trip_with_original_command_and_history(tmp_path, fmt, style):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import exercise\n' +
                        f'print(json.dumps(asyncio.run(exercise(bot,{str(tmp_path)!r},{fmt!r},{style!r}))))')
    assert result['requests'] == 2 and result['executions'] == 1


@pytest.mark.parametrize('fmt', ['openai', 'openai_compatible', 'gemini', 'vertex', 'claude'])
@pytest.mark.parametrize('style', ['nonstream', 'foreground', 'background'])
def test_next_user_turn_keeps_native_history_instead_of_assistant_command_prose(tmp_path, fmt, style):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import cross_turn_history\n' +
                        f'print(json.dumps(asyncio.run(cross_turn_history(bot,{str(tmp_path)!r},{fmt!r},{style!r}))))')
    assert result == {'requests': 4, 'executions': 2, 'native_history': True}


@pytest.mark.parametrize('fmt', ['openai', 'openai_compatible', 'gemini', 'vertex', 'claude'])
def test_diagnostics_count_real_protocol_calls_without_inspecting_prose(tmp_path, fmt):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import diagnostic_round_trip\n' +
        f'print(json.dumps(asyncio.run(diagnostic_round_trip(bot,{str(tmp_path)!r},{fmt!r},"nonstream"))))')
    assert result == {'defined_tools': 17, 'actual_calls': [1, 0, 0], 'no_prose_dispatch': True}


@pytest.mark.parametrize('fmt', ['openai', 'gemini', 'claude'])
@pytest.mark.parametrize('cancel', [False, True])
def test_form_keeps_call_mode_and_resumes_only_remaining_operations(tmp_path, fmt, cancel):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import form_sequence\n' +
                        f'print(json.dumps(asyncio.run(form_sequence(bot,{str(tmp_path)!r},{fmt!r},{cancel!r}))))')
    assert result['ordered'] and result['pinned']


@pytest.mark.parametrize('mode', ['over', 'fence', 'example', 'literal', 'unclosed-example', 'unclosed-fence'])
def test_exclusive_execution_entry_and_over_removes_only_next_request(tmp_path, mode):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import over_and_fence\n' +
                        f'print(json.dumps(asyncio.run(over_and_fence(bot,{str(tmp_path)!r},{mode!r}))))')
    assert result['mode'] == mode


def test_stop_between_native_calls_keeps_result_and_never_runs_remaining(tmp_path):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import stop_between_calls\n' +
                        f'print(json.dumps(asyncio.run(stop_between_calls(bot,{str(tmp_path)!r}))))')
    assert result['only_first'] and result['one_terminal']


def test_native_file_edit_and_binary_writes_preserve_original_bytes(tmp_path):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import native_file_bytes\n' +
                        f'print(json.dumps(asyncio.run(native_file_bytes(bot,{str(tmp_path)!r}))))')
    assert all(result.values())


def test_same_task_comparison_accounts_for_both_model_requests(tmp_path):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import compare_modes\n' +
                        f'print(json.dumps(asyncio.run(compare_modes(bot,{str(tmp_path)!r}))))')
    assert {item['mode'] for item in result} == {'toolcall', 'fence'}
    for item in result:
        assert item['requests'] == 2 and item['executed'] == ['inspect-memory']
        assert item['input_tokens'] == 246 and item['output_tokens'] == 38
        assert item['elapsed_seconds'] >= 0 and item['measurement'] == 'deterministic_mock_usage'


def test_new_round_over_still_works_after_resuming_remaining_form_batch(tmp_path):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import form_then_new_over\n' +
                        f'print(json.dumps(asyncio.run(form_then_new_over(bot,{str(tmp_path)!r}))))')
    assert result['requests'] == 2 and result['new_over']


@pytest.mark.parametrize('code', [400, 429])
def test_unsupported_or_rate_limited_model_preserves_error_without_switching_mode(tmp_path, code):
    result = run_in_app('import asyncio\nfrom tests.native_tool_probe import unsupported_mode\n' +
                        f'print(json.dumps(asyncio.run(unsupported_mode(bot,{str(tmp_path)!r},{code}))))')
    assert result['original_error'] and result['no_fallback']
