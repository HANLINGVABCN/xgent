"""Readable companions retain originals and never become model context."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

from xgent_app.history_export import history_archive_files
from xgent_app.readable_export import readable_files


def records():
    call = {'id': 'original|foreign', 'run_id': 'run', 'response_id': 'response', 'name': 'exec_command',
            'arguments': {'command': '  printf "中文"\n\tprintf end\n'}}
    return [
        {'id': 1, 'timestamp': 1, 'role': 'assistant', 'msg_type': 'ai_reply', 'content': '', 'metadata': {
            'native_calls': [call], 'model_context': {'version': 1, 'messages': [{'role': 'assistant', 'content': '',
                'native_calls': [call], 'native_binding': ['openai', 'p', 'm', 'run']}], 'assets': []},
            'thinking': {'version': 1, 'text': 'VISIBLE_THINKING\nexact next line', 'status': 'stopped', 'elapsed_seconds': 1.25}}},
        {'id': 2, 'timestamp': 2, 'role': 'system', 'msg_type': 'agent_result', 'content': 'UI_RESULT', 'metadata': {
            'model_context': {'version': 1, 'messages': [{'role': 'user', 'content': 'ACTUAL_RESULT\n  exact output',
                'native_result': {'id': call['id'], 'run_id': 'run', 'response_id': 'response', 'success': False,
                                  'return_code': 3, 'state': 'failed'}}], 'assets': []}}},
        {'id': 3, 'timestamp': 3, 'role': 'assistant', 'msg_type': 'ai_reply', 'content': 'NORMAL_REPLY', 'metadata': {}},
    ]


def test_readable_tool_and_thinking_files_preserve_raw_structure_and_command_bytes():
    source = records()
    before = copy.deepcopy(source)
    snapshot = {'conversation_id': 'conversation', 'context_epoch': 0, 'records': source, 'compressions': []}
    with patch.object(Path, 'read_bytes', side_effect=AssertionError('export opened a referenced file')):
        files, _ = history_archive_files(snapshot, system_prompt='SYSTEM', compression_prompt='MANUAL',
                                         access_logs=[], storage_root='.')
    readable = files['工具调用记录.txt'].decode('utf-8')
    assert readable.count('--- 工具调用') == 1
    assert '工具：exec_command' in readable and '调用 ID：original|foreign' in readable
    assert '  printf "中文"\n\tprintf end\n' in readable
    assert 'ACTUAL_RESULT\n  exact output' in readable and '状态：失败' in readable
    thinking = files['思考记录.txt'].decode('utf-8')
    assert 'VISIBLE_THINKING\nexact next line' in thinking and '记录耗时：1.25s' in thinking
    assert '状态：已停止' in thinking and 'NORMAL_REPLY' not in thinking
    raw = files['001-当前-001a全局记忆.txt'].decode('utf-8')
    assert 'model_context:' in raw and 'original|foreign' in raw and 'NORMAL_REPLY' in raw
    assert 'VISIBLE_THINKING' not in raw
    assert source == before


def test_missing_results_and_durations_are_not_reconstructed_from_text_or_tokens():
    source = records()[:1]
    source[0]['content'] = 'I already executed this successfully'
    source[0]['metadata']['thinking']['elapsed_seconds'] = None
    files = readable_files(source)
    assert '未找到已保存的对应结果' in files['工具调用记录.txt'].decode('utf-8')
    assert '记录耗时：耗时未记录' in files['思考记录.txt'].decode('utf-8')
    source[0]['metadata'].pop('thinking')
    source[0]['metadata']['usage'] = {'reasoning_tokens': 1000}
    assert '思考记录.txt' not in readable_files(source)
    assert readable_files([{'content': 'exec_command fake', 'metadata': {}}]) == {}


def test_original_call_ids_do_not_merge_results_from_different_runs():
    first = records()
    second = copy.deepcopy(first[:2])
    second[0]['id'] = 4
    second[1]['id'] = 5
    second[0]['metadata']['model_context']['messages'][0]['native_calls'][0]['run_id'] = 'different'
    second[1]['metadata']['model_context']['messages'][0]['native_result']['run_id'] = 'different'
    second[1]['metadata']['model_context']['messages'][0]['content'] = 'OTHER_RESULT'
    readable = readable_files(first + second)['工具调用记录.txt'].decode('utf-8')
    assert readable.count('--- 工具调用') == 2
    assert readable.count('OTHER_RESULT') == 1 and readable.count('ACTUAL_RESULT') == 1


def test_binary_data_is_not_duplicated_in_readable_file_and_original_json_survives():
    source = records()
    call = source[0]['metadata']['model_context']['messages'][0]['native_calls'][0]
    call['name'] = 'write_binary'
    call['arguments'] = {'path': '/tmp/sample.bin', 'base64_data': 'A' * 256}
    files = readable_files(source)
    assert 'A' * 256 not in files['工具调用记录.txt'].decode('utf-8')
    assert 'A' * 256 in json.dumps(source)


def test_base64_examples_in_commands_results_and_thinking_stay_literal_text():
    source = records()
    example = 'data:image/png;base64,' + 'A' * 256
    source[0]['metadata']['model_context']['messages'][0]['native_calls'][0]['arguments']['command'] = 'printf ' + example
    source[0]['metadata']['thinking']['text'] = 'A literal example: ' + example
    source[1]['metadata']['model_context']['messages'][0]['content'] = 'SOURCE_CODE_EXAMPLE ' + example
    files = readable_files(source)
    assert files['工具调用记录.txt'].decode('utf-8').count(example) == 2
    assert example in files['思考记录.txt'].decode('utf-8')
