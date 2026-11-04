"""Withdraw and resend attachment references using existing server bytes only."""
import asyncio
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

from tests.attachment_request_probe import Harness
from tests.test_attachments import image_bytes
from xgent_app.conversation_branching import ConversationBranchService, BranchingError
from xgent_app.conversations import bind_conversation, current_scope
from xgent_app.presentation import metadata_dict
from xgent_app.web_history import build_history_message


async def restore(bot, root):
    async with Harness(bot, root) as h:
        files = Path(bot.ArtifactManager.UPLOAD_DIR)
        files.mkdir(parents=True, exist_ok=True)
        original = {'photo.png': image_bytes(), 'video.mp4': b'mocked-video-bytes', 'notes.txt': b'UPLOAD_PATH_ONLY'}
        refs = []
        for index, (name, data) in enumerate(original.items()):
            (files / name).write_bytes(data)
            refs.append({'version': 1, 'path': name, 'name': name, 'storage': 'uploads',
                         'mime_type': {'photo.png': 'image/png', 'video.mp4': 'video/mp4', 'notes.txt': 'text/plain'}[name],
                         'order': index, 'size': len(data)})
        cid = current_scope().conversation_id
        metadata = {'attachments': refs[:2], 'server_uploads': refs[2:], 'web_file_message': {'version': 1, 'text': '原始说明'},
                    'file_ingress_mode': 'attachment', 'telegram_delivery': {'ids': [11], 'conversation_id': cid}}
        row_id = await bot.GlobalRecorder.record_user_message('原始说明\nFILE_INDEX', bot.MessageType.USER_FILE, metadata=metadata)
        await bot.GlobalRecorder.record_ai_reply('old answer')
        service = ConversationBranchService(h.db, code_root=root, storage_root=bot.ArtifactManager.ROOT_DIR)
        preview = await service.withdraw_preview(cid, row_id)
        result = await service.withdraw(cid, row_id, {'confirm': True, 'turn_id': preview['turn_id'],
            'current_digest': preview['current_digest'], 'request_id': 'attachment-restore-fixture'})
        draft = result['draft']
        assert draft['text'] == '原始说明'
        assert [item['kind'] for item in draft['media']] == ['photo', 'video', 'file']
        assert all(item.get('download_url', '').startswith('/api/media/') for item in draft['media'])
        assert 'telegram_delivery' not in draft['metadata']
        assert not any('source_message_id' in ref for ref in draft['metadata']['attachments'])
        assert not await h.db.get_display_history(100)
        refreshed = (await service.lineage(cid))['draft']
        assert refreshed['metadata'] == draft['metadata']
        assert refreshed['source_record_id'] == row_id
        other = (await bot.get_conversations().manage('create', name='Other'))['conversation_id']
        try:
            await service.update_draft(other, {'source_record_id': row_id, 'revision': draft['revision'], 'keep': ['server_uploads:0']})
        except BranchingError:
            pass
        else:
            raise AssertionError('Cross conversation draft was accepted')
        updated = (await service.update_draft(cid, {'source_record_id': row_id, 'revision': draft['revision'], 'keep': ['attachments:0', 'server_uploads:0']}))['draft']
        assert [item['filename'] for item in updated['media']] == ['photo.png', 'notes.txt']
        scope = replace(await bot.get_conversations().resolve(cid), origin='web', purpose='chat')
        with bind_conversation(scope):
            await h.db.queue_register('draft-test-instance')
            await h.db.queue_enqueue(scope=scope, instance='draft-test-instance', request_key='resend-draft-test', text='重新说明', chat_id=1)
            async with bot.get_conversations().operation(cid, execution=True, fresh=True) as running:
                batch = await h.db.queue_claim(running)
            assert len(batch) == 1
            saved = await h.db.get_display_message(batch[0]['record_id'])
            reused = metadata_dict(saved['metadata'])
            assert reused['attachments'] == [refs[0]] and reused['server_uploads'] == [refs[2]]
            assert reused['web_file_message']['text'] == '重新说明'
            assert 'telegram_delivery' not in reused
            message = build_history_message(saved, bot.ArtifactManager.ROOT_DIR, root)
            assert message['conversation_actions']['withdraw'] is True
            assert message['conversation_actions']['branch_mode'] == 'user'
            assert (await service.lineage(cid))['draft'] is None
        assert all((files / name).read_bytes() == data for name, data in original.items())
        assert not h.requests
        return {'server_paths_reused': True, 'modes_preserved': True, 'draft_refresh': True, 'cross_conversation_rejected': True}
