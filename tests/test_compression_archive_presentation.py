"""Old completed compressions retain their summary and get an independent archive row."""
import json
import time
import unittest

from tests import test_conversations as support
from xgent_app.conversations import bind_conversation
from xgent_app.web_history import display_media_reference


class CompressionArchivePresentationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = support.ConversationTests.asyncSetUp
    asyncTearDown = support.ConversationTests.asyncTearDown

    async def test_old_archive_moves_before_summary_once_without_changing_context_or_source(self):
        db = self.db
        scope = await self.manager.resolve()
        with bind_conversation(scope):
            async with db._transaction() as conn:
                summary = await db._insert_global_record(conn, 1, 0, 'ai_reply', 'assistant', '完整已保存摘要',
                    time.time(), scope.conversation_id, {'compression_job_id': 'a'*32, 'compression_complete': True})
            entry = {'job_id': 'a'*32, 'version': 3, 'conversation_id': scope.conversation_id,
                'context_epoch': 0, 'generation': scope.generation, 'sequence': 1, 'status': 'completed',
                'summary': '完整已保存摘要', 'created_at': 100, 'response_row_id': summary,
                'archive_path': '/unmodified/complete-archive.zip', 'text_dir': '/unmodified/records', 'chat_id': 1}
            original, metadata = db._compression_notice(entry)
            notice = await db.record_global_message(1, 0, 'system_op', 'system', original, metadata=metadata)
            entry['notice_row_id'] = notice
            async with db._transaction() as conn:
                await conn.execute('INSERT INTO context_compression_jobs(job_id,payload,session_id,context_epoch) VALUES(?,?,?,?)',
                    (entry['job_id'], json.dumps(entry), scope.conversation_id, 0))
                await conn.execute('INSERT INTO context_compressions(session_id,sequence,payload,context_epoch) VALUES(?,?,?,?)',
                    (scope.conversation_id, 1, json.dumps(entry), 0))
            before = await db.get_conversation_messages(100)
            self.assertEqual(1, await db.repair_compression_archive_presentations())
            self.assertEqual(0, await db.repair_compression_archive_presentations())
            after = await db.get_conversation_messages(100)
            self.assertEqual(before, after)
            saved = await db.get_latest_compression()
            self.assertEqual(entry['summary'], saved['summary'])
            self.assertEqual(entry['archive_path'], saved['archive_path'])
            archive = await db.get_display_message(saved['archive_row_id'])
            self.assertEqual(100, archive['timestamp'])
            archive_meta = json.loads(archive['metadata'])
            self.assertEqual([display_media_reference(entry['archive_path'], '系统记忆.zip')], archive_meta['display_media'])
            self.assertFalse(archive_meta['message_policy']['model_context'])
            notice_after = await db.get_display_message(notice)
            self.assertEqual(original, notice_after['content'])
            self.assertNotIn('display_media', json.loads(notice_after['metadata']))
            self.assertEqual(entry['summary'], (await db.get_display_message(summary))['content'])
