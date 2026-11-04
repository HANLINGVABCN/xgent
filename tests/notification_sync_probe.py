"""Actual recording and outbox boundaries against fake Telegram/model transports."""
import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.attachment_request_probe import Harness
from tests.telegram_chat_probe import TelegramCapture
from tests.test_channel_isolation import _FakeStore
from xgent_app.conversation_branching import ConversationBranchService
from xgent_app.conversations import bind_conversation, current_scope
from xgent_app.fanout import ChannelWorker, Op, get_channel_registry
from xgent_app.interaction import interaction
from xgent_app.presentation import metadata_dict
from xgent_app.web_bridge import deliver_op_to_bot, MirrorBot
from xgent_app.web_history import build_history_message


class Native(TelegramCapture):
    id = 7001

    async def send_document(self, chat_id, document, **kwargs):
        assert document.read() == b'FILE_BYTES'
        message = self.message('', chat_id)
        self.save(message.message_id, kwargs.get('caption', ''), chat_id=chat_id)
        return message


async def security_notice(bot, root, silent=False, selected=True, callback=False):
    async with Harness(bot, root) as h:
        manager = bot.get_conversations()
        other = (await manager.manage('create', name='Independent Web tab'))['conversation_id']
        if not selected:
            await h.db.set_config('telegram_conversation_id', None)
        bot.UserDataManager.set('silent_unauthorized', silent)
        native = Native()
        worker = ChannelWorker('telegram', lambda op, mid: deliver_op_to_bot(native, op, mid))
        get_channel_registry().register(worker)
        incoming = SimpleNamespace(text='/status <script>blocked</script>', document=None, sticker=None,
                                   photo=None, reply_text=AsyncMock())
        query = SimpleNamespace(data='cmd_status', answer=AsyncMock()) if callback else None
        update = SimpleNamespace(message=None if callback else incoming, callback_query=query,
            effective_user=SimpleNamespace(id=8883320224, username=None, full_name='Jonathan <Barrera>'),
            effective_chat=SimpleNamespace(id=8883320224))
        try:
            before = await manager.state()
            with patch.object(bot, 'get_web_outbox', return_value=h.outbox), \
                    patch.object(bot, '_web_real_bot', native), \
                    patch.dict('os.environ', {'XGENT_CLI_NO_TG_MIRROR': '1'}), \
                    bind_conversation(None), interaction('telegram', 'management'):
                assert not await bot.check_authorized_user_middleware(update, SimpleNamespace(bot=native))
            assert await worker.wait_idle(timeout=3)
            logs = await h.db.get_unauthorized_access_logs()
            assert len(logs) == 1 and logs[0]['user_id'] == 8883320224
            assert not h.requests and (await manager.state()) == before
            with bind_conversation(await manager.resolve(other)):
                assert not await h.db.get_display_history(100)
            with bind_conversation(await manager.resolve('global_memory')):
                rows = await h.db.get_display_history(100)
                history = await h.db.get_conversation_messages(100)
            frames = h.drain_frames()
            reports = [item for item in native.messages.values() if item.get('chat_id') == 1]
            assert len(reports) == 1, native.messages
            assert '&lt;Barrera&gt;' in reports[0]['text']
            if selected:
                assert len(rows) == 1 and rows[0]['msg_type'] == 'system_op'
                row = rows[0]
                assert '8883320224' in str(history) and ('cmd_status' if callback else '/status') in str(history)
                assert metadata_dict(row['metadata'])['message_policy']['model_context'] is True
                saved = build_history_message(row, bot.ArtifactManager.ROOT_DIR, root)
                visible = [f for f in frames if f.get('record_id') == row['id']]
                assert [f['type'] for f in visible] == ['message', 'record_snapshot'], visible
                assert visible[0]['text'] == visible[1]['text'] == saved['content']
                assert visible[0]['conversation_id'] == 'global_memory'
                assert metadata_dict(row['metadata'])['telegram_delivery']['ids']
            else:
                assert not rows and all(frame['type'] == 'access_notice' for frame in frames)
            assert any(frame['type'] == 'access_notice' and '来自电报端的未授权请求' in frame['text'] for frame in frames)
            if silent:
                incoming.reply_text.assert_not_called()
                if query: query.answer.assert_not_called()
            return {'scoped_notice': True, 'web_and_history': True, 'log_recorded': True,
                    'no_execution': True, 'selection_untouched': True}
        finally:
            await worker.aclose()


class PendingChannel:
    def __init__(self):
        self.operations = []

    def ensure_started(self):
        pass

    def offer(self, op):
        self.operations.append(op)


async def withdraw_mirrored_user(bot, root, phase='delivered', queued=True):
    async with Harness(bot, root) as h:
        native = Native()
        pending = PendingChannel()
        other = (await bot.get_conversations().manage('create', name='B untouched'))['conversation_id']
        store = _FakeStore()
        release, started = asyncio.Event(), asyncio.Event()
        reconnected = False

        async def send(**kwargs):
            if phase == 'inflight':
                started.set()
                await release.wait()
            if phase == 'reconnect' and not reconnected:
                from telegram.error import TimedOut
                raise TimedOut('simulated disconnect')
            return await Native.send_message(native, **kwargs)

        native.send_message = send
        worker = ChannelWorker('mirror-withdraw', lambda op, mid: deliver_op_to_bot(native, op, mid), store=store)
        try:
            native.messages[99999] = {'text': 'B message', 'chat_id': 1}
            with bind_conversation(await bot.get_conversations().resolve(other)):
                await bot.GlobalRecorder.record_user_message('B must survive')
            scope = replace(await bot.get_conversations().resolve('global_memory'), origin='web', purpose='chat', telegram_delivery=True)
            text = ('WEB_USER_MIRROR\n' * 500 if phase in {'delivered', 'reconnect'} else 'WEB_USER_MIRROR')
            with interaction('web', 'chat'), bind_conversation(scope), \
                    patch.object(bot, '_web_real_bot', native), patch.object(bot, 'telegram_channel', return_value=pending):
                row_id = await bot.GlobalRecorder.record_user_message(text)
                if queued:
                    await bot.publish_queued_users(h.context, [{'record_id': row_id, 'id': 'queue-fixture', 'origin': 'web', 'text': text}])
                else:
                    bot.mirror_user_line_to_telegram('💬 [网页]\n' + text, record_id=row_id)
                operations = list(pending.operations)
                assert operations and all(op.payload['_record_id'] == row_id for op in operations)
                assert all(type(op.logical_id) is int for op in operations)
                assert not native.calls  # No Telegram API await in the user submission path.
                delivery_task = None
                if phase in {'delivered', 'reconnect'}:
                    for op in operations:
                        await worker._handle(op)
                    if phase == 'reconnect':
                        assert store.rows
                        assert all(Op.from_row(row).payload['_record_id'] == row_id for row in store.rows)
                        reconnected = True
                        worker._breaker.record_success()
                        await worker._drain_store(0)
                        assert not store.rows
                    row = await h.db.get_display_message(row_id)
                    metadata = metadata_dict(row['metadata'])
                    assert metadata['telegram_delivery']['bot_id'] == native.id
                    assert len(metadata['telegram_delivery']['ids']) == len(operations)
                elif phase == 'inflight':
                    delivery_task = asyncio.create_task(worker._handle(operations[0]))
                    await asyncio.wait_for(started.wait(), 3)
                service = ConversationBranchService(h.db, code_root=Path(root), storage_root=Path(root)/'storage')
                with interaction('web', 'management'), bind_conversation(replace(scope, purpose='management', telegram_delivery=False)):
                    preview = await service.withdraw_preview('global_memory', row_id)
                    result = await service.withdraw('global_memory', row_id, {'confirm': True,
                        'turn_id': preview['turn_id'], 'current_digest': preview['current_digest'], 'request_id': 'mirror-withdraw-fixture'})
                    if phase in {'delivered', 'reconnect'}:
                        assert len(result['telegram_native_message_ids']) == len(operations)
                        pending.operations.clear()
                        await bot._delete_withdrawn_telegram(result['telegram_native_message_ids'], [], 'mirror-withdraw-fixture')
                        for op in pending.operations:
                            await worker._handle(op)
                if phase == 'pending':
                    for op in operations:
                        await worker._handle(op)
                    assert not native.calls
                if delivery_task is not None:
                    release.set()
                    await asyncio.wait_for(delivery_task, 3)
                assert list(native.messages) == [99999], native.messages
                assert not await h.db.get_display_history(100)
            with bind_conversation(await bot.get_conversations().resolve(other)):
                assert 'B must survive' in str(await h.db.get_display_history(100))
            return {'associated': True, 'withdrawn': True, 'other_untouched': True, 'nonblocking': True}
        finally:
            release.set()
            await worker.aclose()


async def direct_file_association(bot, root):
    async with Harness(bot, root) as h:
        native = Native()
        path = Path(root) / 'file.txt'
        path.write_bytes(b'FILE_BYTES')
        record_id = await bot.GlobalRecorder.record_user_message('File caption', bot.MessageType.USER_FILE)
        channel = SimpleNamespace(is_open=lambda: False)
        with patch.object(bot, '_web_real_bot', native), patch.object(bot, 'telegram_channel', return_value=channel):
            await bot.sync_web_attachment_to_telegram(str(path), 'file.txt', 'long caption ' * 200, record_id=record_id)
        row = await h.db.get_display_message(record_id)
        delivery = metadata_dict(row['metadata'])['telegram_delivery']
        assert set(delivery['ids']) == set(native.messages)
        assert len(delivery['ids']) >= 2 and delivery['conversation_id'] == current_scope().conversation_id
        assert delivery['record_id'] == record_id
        assert path.read_bytes() == b'FILE_BYTES' and not h.requests
        return {'file_and_caption_ids_saved': True, 'original_bytes_unchanged': True}
