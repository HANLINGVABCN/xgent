"""Withdraw real durable records through the Web management delivery gate."""
from dataclasses import replace
from unittest.mock import patch

from tests.attachment_request_probe import Harness
from tests.telegram_rich_probe import RichCapture
from xgent_app.conversation_branching import ConversationBranchService
from xgent_app.conversations import bind_conversation, current_scope
from xgent_app.interaction import interaction
from xgent_app.web_bridge import MirrorBot


async def withdraw(bot, root):
    async with Harness(bot, root) as h:
        native = RichCapture()
        bridge = MirrorBot(h.outbox, 1, native)
        a = current_scope().conversation_id
        other = (await bot.get_conversations().manage('create', name='B'))['conversation_id']
        with bind_conversation(await bot.get_conversations().resolve(a)):
            user = await bot.GlobalRecorder.record_user_message('original Bot message',  chat_id=1,
                metadata={'source_message_id': 10, 'source_message_ids': [10, 11], 'telegram_source_bot_id': native.id})
            for kind, ids in [('ai_reply', [12, 13]), ('agent_result', [14]), ('media_reply', [15, 16]), ('agent_result', [17])]:
                await bot.GlobalRecorder.record(kind, 'assistant', kind, chat_id=1,
                    metadata={'telegram_delivery': {'bot_id': native.id, 'chat_id': 1,
                        'conversation_id': a, 'ids': ids}})
            last = await bot.GlobalRecorder.record('ai_reply', 'assistant', 'foreign association', chat_id=1,
                metadata={'telegram_delivery': {'bot_id': native.id, 'chat_id': 1,
                    'conversation_id': other, 'ids': [90]}})
        with bind_conversation(await bot.get_conversations().resolve(other)):
            await bot.GlobalRecorder.record_user_message('B is untouched', chat_id=1)
        for mid in range(10, 18):
            native.messages[mid] = {'text': str(mid), 'reply_markup': None}
        native.messages[90] = {'text': 'B', 'reply_markup': None}
        scope = replace(await bot.get_conversations().resolve(a), origin='web', purpose='management', telegram_delivery=False)
        service = ConversationBranchService(h.db, code_root=h.root, storage_root=h.root/'storage')
        with interaction('web', 'management'), bind_conversation(scope), \
                patch.object(bot, '_web_real_bot', native), \
                patch.object(bot, 'telegram_channel', return_value=bridge._tg_channel()):
            preview = await service.withdraw_preview(a, user)
            result = await service.withdraw(a, user, {'confirm': True, 'turn_id': preview['turn_id'],
                'current_digest': preview['current_digest'], 'request_id': 'withdraw-fixture'})
            assert result['telegram_native_message_ids'] == list(range(10, 18)), result
            await bot._delete_withdrawn_telegram(result['telegram_native_message_ids'], [], 'withdraw-fixture')
            assert await bridge.flush_telegram(3)
            assert list(native.messages) == [90], native.messages
            assert not await h.db.get_display_history(100)
        with bind_conversation(await bot.get_conversations().resolve(other)):
            assert 'B is untouched' in str(await h.db.get_display_history(100))
        await bridge._tg_channel().aclose()
        return {'original_and_following_deleted': True, 'other_conversation_untouched': True}
