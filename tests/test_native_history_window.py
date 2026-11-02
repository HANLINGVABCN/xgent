"""History depth keeps structured calls and their results as one response."""
import json
import unittest

from tests import test_conversations as support
from xgent_app.conversations import bind_conversation
from xgent_app.tool_calls import ResponseCapture, ToolSession, wire_history


class NativeHistoryWindowTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = support.ConversationTests.asyncSetUp
    asyncTearDown = support.ConversationTests.asyncTearDown
    write = support.ConversationTests.write

    async def seed(self):
        session = ToolSession('openai', 'p', 'm', 'historical-run')
        capture = ResponseCapture(session)
        capture.observe({'id': 'historical-response', 'choices': [{'message': {'tool_calls': [
            {'id': cid, 'function': {'name': 'exec_command', 'arguments': json.dumps({'command': cid})}}
            for cid in ('first', 'second')]}, 'finish_reason': 'tool_calls'}]})
        capture.finalize()
        await self.write('ORIGINAL_QUESTION')
        call_row = await self.write('', 'ai_reply', {'model_context': {
            'version': 1, 'messages': [capture.message('')], 'assets': []}})
        rows = []
        for cid, text in [('first', 'FIRST_RESULT'), ('first', 'FIRST_FRAGMENT'), ('second', 'SECOND_RESULT')]:
            result = {'role': 'user', 'content': text, 'native_result': {
                'id': cid, 'run_id': session.run_id, 'response_id': capture.response_id}}
            rows.append(await self.write(text, 'agent_result', {'model_context': {
                'version': 1, 'messages': [result], 'assets': []}}))
        return session, call_row, rows

    async def test_result_at_depth_boundary_restores_call_batch_and_all_fragments(self):
        with bind_conversation(await self.manager.resolve()):
            session, _, _ = await self.seed()
            await self.write('AI_FINAL', 'ai_reply')
            await self.write('NEW_QUESTION')
            history = await self.db.get_conversation_messages(3)
            self.assertEqual(['', 'FIRST_RESULT', 'FIRST_FRAGMENT', 'SECOND_RESULT', 'AI_FINAL', 'NEW_QUESTION'],
                             [m['content'] for m in history])
            self.assertNotIn('ORIGINAL_QUESTION', str(history))
            wire = wire_history(history, session, lambda content: content)
            self.assertEqual(['FIRST_RESULT\nFIRST_FRAGMENT', 'SECOND_RESULT'],
                             [m['content'] for m in wire if m['role'] == 'tool'])
            short = await self.db.get_conversation_messages(2)
            self.assertEqual(['AI_FINAL', 'NEW_QUESTION'], [m['content'] for m in short])

    async def test_cutoff_never_reads_results_from_after_requested_snapshot(self):
        with bind_conversation(await self.manager.resolve()):
            session, call_row, rows = await self.seed()
            history = await self.db.get_conversation_messages(1, before_record_id=rows[1])
            self.assertEqual(['', 'FIRST_RESULT'], [m['content'] for m in history])
            self.assertFalse(any(m.get('tool_calls') or m['role'] == 'tool'
                                 for m in wire_history(history, session, lambda content: content)))
            conn = await self.db._get_conn()
            await conn.execute('UPDATE global_messages SET withdrawn=1 WHERE id=?', (call_row,))
            missing = await self.db.get_conversation_messages(1)
            self.assertFalse(any(m.get('native_calls') for m in missing))

    async def test_identical_links_in_other_chats_or_cleared_contexts_are_excluded(self):
        first = await self.manager.resolve()
        with bind_conversation(first):
            await self.seed()
            second = (await self.manager.manage('create', name='other'))['conversation_id']
        with bind_conversation(await self.manager.resolve(second)):
            await self.seed()
            await self.write('OTHER_CHAT')
        with bind_conversation(await self.manager.resolve(first.conversation_id)):
            history = await self.db.get_conversation_messages(1)
            self.assertNotIn('OTHER_CHAT', str(history))
            self.assertEqual(4, len(history))
            await self.db.clear_all_conversation_memory()
            await self.write('AFTER_CLEAR')
            self.assertEqual(['AFTER_CLEAR'], [m['content'] for m in await self.db.get_conversation_messages(1)])
