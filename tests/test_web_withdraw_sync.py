import asyncio
from collections import OrderedDict
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.test_thinking_params import run_in_app
from xgent_app import telegram_records
from xgent_app.fanout import OP_DELETE, Op
from xgent_app.web_bridge import deliver_op_to_bot


def test_web_management_withdraw_deletes_bot_original_and_all_following_types(tmp_path):
    result = run_in_app('import asyncio\nfrom tests.web_withdraw_sync_probe import withdraw\n' +
                        f'print(json.dumps(asyncio.run(withdraw(bot, {str(tmp_path)!r}))))')
    assert all(result.values())


def test_branch_history_detaches_source_delivery_ids_without_changing_content_references():
    metadata = {'telegram_delivery': {'ids': [4], 'conversation_id': 'source'},
        'telegram_native_parts': {'ids': [5]}, 'telegram_reply': {'message_ids': [6]},
        'telegram_logical_ids': [7], 'telegram_logical_instance': 'instance',
        'source_message_id': 8, 'source_message_ids': [8, 9], 'telegram_source_bot_id': 11,
        'web_live': {'epoch': 'same', 'message_ids': [7]},
        'attachments': [{'path': 'image.png', 'source_message_id': 10}],
        'native_calls': [{'name': 'read_file', 'arguments': {'path': 'original.txt'}}]}
    before = deepcopy(metadata)
    detached = telegram_records.detach_delivery_metadata(metadata)
    assert metadata == before
    assert detached == {'attachments': [{'path': 'image.png'}], 'native_calls': metadata['native_calls']}


def test_a_logical_id_of_another_conversation_cannot_be_rebound_or_withdrawn(monkeypatch):
    monkeypatch.setattr(telegram_records, '_records', OrderedDict({101: (1, 'A')}))
    monkeypatch.setattr(telegram_records, '_deliveries', OrderedDict({101: {
        'bot_id': 77, 'chat_id': 1, 'conversation_id': 'A', 'ids': [8]}}))
    db = SimpleNamespace(patch_display_metadata=AsyncMock())
    asyncio.run(telegram_records.bind_record(db, {'id': 2, 'session_id': 'B', 'metadata': {}}, [101]))
    assert not db.patch_display_metadata.call_args.args[1].get('telegram_delivery')
    assert telegram_records.logical_message_belongs_to(101, 'A')
    assert not telegram_records.logical_message_belongs_to(101, 'B')


def test_exact_withdrawal_does_not_require_recreating_a_topic_and_repeat_delete_is_successful():
    from telegram.error import BadRequest
    native = SimpleNamespace(delete_message=AsyncMock(side_effect=BadRequest('Message to delete not found')))
    op = Op(OP_DELETE, chat_id=1, payload={'native_id': 88, '_conversation_context': {
        'conversation_id': 'A', 'origin': 'web', 'purpose': 'management', 'telegram_delivery': True,
        'telegram_bot_id': 7001, 'telegram_chat_id': 1, 'telegram_thread_id': None}})
    assert asyncio.run(deliver_op_to_bot(native, op, 88)) is None
    native.delete_message.assert_awaited_once_with(chat_id=1, message_id=88)
