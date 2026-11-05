import tempfile
from tests.test_thinking_params import run_in_app


def test_attachment_batch_queues_while_busy_and_reaches_model_once():
    with tempfile.TemporaryDirectory(prefix='xgq-') as root:
        result=run_in_app('import asyncio\nfrom tests.attachment_queue_probe import queued_files\n'+
            f'print(json.dumps(asyncio.run(queued_files(bot,{root!r}))))')
    assert result['originals'] and result['pending_hidden'] and result['model_received_once']


def test_attachment_queue_recovery_keeps_original_files_modes_and_order():
    with tempfile.TemporaryDirectory(prefix='xgq-') as root:
        result=run_in_app('import asyncio\nfrom tests.attachment_queue_probe import queued_files\n'+
            f'print(json.dumps(asyncio.run(queued_files(bot,{root!r},recover=True))))')
    assert all(result.values())


def test_archived_chat_uses_the_same_attachment_queue_and_model_context():
    with tempfile.TemporaryDirectory(prefix='xgq-') as root:
        result=run_in_app('import asyncio\nfrom tests.attachment_queue_probe import queued_files\n'+
            f'print(json.dumps(asyncio.run(queued_files(bot,{root!r},archived=True))))')
    assert result['originals'] and result['pending_hidden'] and result['model_received_once']
