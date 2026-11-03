"""Missing original media and read snapshots must not freeze ordinary chat."""
import base64
from copy import deepcopy
from pathlib import Path

import pytest

from tests.test_attachments import image_bytes
from xgent_app.attachments import create_generated_image_references, prepare_attachment_context
from xgent_app.tool_context import freeze_tool_message, messages_from_metadata, restore_tool_context


@pytest.mark.parametrize('change', ['delete', 'replace'])
def test_generated_original_becomes_explicitly_unavailable_and_recovers(tmp_path, change):
    uploads, generated = tmp_path / 'uploads', tmp_path / 'generated'
    uploads.mkdir(); generated.mkdir()
    path = generated / 'original.png'
    original = image_bytes('PNG')
    path.write_bytes(original)
    references = create_generated_image_references([{'path': str(path), 'mime_type': 'image/png'}], generated)
    records = [{'id': 1, 'role': 'assistant', 'msg_type': 'ai_reply', 'timestamp': 1,
                'metadata': {'attachments': references}}]
    before = deepcopy(records)
    if change == 'delete': path.unlink()
    else: path.write_bytes(image_bytes('PNG', (250, 30, 30)))
    parts, updates, errors = prepare_attachment_context(records, uploads, generated)
    assert not errors and not updates
    assert '附件暂不可用' in str(parts)
    assert not any(part['type'] == 'image' for part in parts)
    assert records == before
    assert prepare_attachment_context(records, uploads, generated, strict=True)[2]
    path.write_bytes(original)
    parts, _, errors = prepare_attachment_context(records, uploads, generated)
    assert not errors
    assert base64.b64decode(next(part['data'] for part in parts if part['type'] == 'image')) == original


@pytest.mark.parametrize('change', ['delete', 'replace'])
def test_read_snapshot_loss_keeps_call_result_and_other_text(tmp_path, change):
    original = image_bytes('PNG')
    def save(name, data):
        target = tmp_path / name
        target.write_bytes(data)
        return {'abs_path': str(target)}
    message = {'role': 'user', 'content': [
        {'type': 'text', 'text': 'ACTUAL_READ_RESULT'},
        {'type': 'image', 'mime_type': 'image/png', 'data': base64.b64encode(original).decode()}],
        'native_result': {'id': 'read-id', 'run_id': 'run', 'response_id': 'response'}}
    payload = freeze_tool_message(message, save)
    record = {'id': 2, 'metadata': {'model_context': payload}}
    history = messages_from_metadata(record['metadata'], 2)
    before = deepcopy(history)
    target = Path(payload['assets'][0]['path'])
    if change == 'delete': target.unlink()
    else: target.write_bytes(b'damaged snapshot')
    restored = restore_tool_context(history, [record], tmp_path)
    assert 'ACTUAL_READ_RESULT' in str(restored)
    assert '附件暂不可用' in str(restored)
    assert restored[0]['native_result'] == message['native_result']
    assert history == before
    with pytest.raises(ValueError):
        restore_tool_context(history, [record], tmp_path, strict=True)
    target.write_bytes(original)
    restored = restore_tool_context(history, [record], tmp_path)
    assert base64.b64decode(restored[0]['content'][1]['data']) == original
