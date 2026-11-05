"""Owned trees, durable admission and exact results, with no real model calls."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tests.test_database_write_lock import _load_db_class
from xgent_app.child_conversations import descendant_ids, poll_conversation_jobs
from xgent_app.conversations import ConversationChanged, ConversationError, ConversationManager, bind_conversation, current_scope
from xgent_app.message_queue import MessageQueue


class ChildConversationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'memory.db')
        cls = _load_db_class()
        core = (Path(__file__).resolve().parents[1] / 'xgent_app/sections/core.py').read_text(encoding='utf-8')
        exec(core[core.index('class MessageType:'):core.index('def _read_int_env(')], cls._init_db.__globals__)
        from xgent_app.web_history import display_media_reference
        cls._init_db.__globals__['display_media_reference'] = display_media_reference
        self.db = cls(self.path)
        await self.db._init_db()
        async def factory():
            return self.db
        self.manager = ConversationManager(factory, self.path, code_root=self.temp.name)
        self.manager.job_admission_enabled = True

    async def asyncTearDown(self):
        await self.manager.close()
        self.manager.lock.release()
        await self.db.close()
        self.temp.cleanup()

    async def write(self, text):
        return await self.db.record_global_message(1, 1, 'user_text', 'user', text)

    async def child(self, parent='global_memory', name='子对话'):
        return (await self.db.create_child_conversation(parent, name))['conversation_id']

    def callback(self, identifier='trg_test', parent='global_memory'):
        return {'id': identifier, 'chat_id': 1, 'conversation_id': parent, 'command': 'echo fixture',
                'summary': '助手结果', 'schedule_type': 'once', 'timezone': 'UTC', 'status': 'pending',
                'created_at': 1, 'updated_at': 1}

    async def run_job(self, job, *, reply='真实结果', outcome='completed', group='group-test'):
        scope = await self.manager.resolve(job['conversation_id'])
        async with self.manager.operation(scope, execution=True):
            scope = current_scope()
            item = await self.db.queue_enqueue(scope=scope, instance='0' * 32,
                request_key='conversation-job:' + job['id'], text=job['text'], chat_id=1)
            await self.db.bind_conversation_job_queue(job['id'], item['id'])
            await self.db.queue_claim(scope, first_id=item['id'], owner='0' * 32)
            record = await self.db.record_global_message(1, 1, 'ai_reply', 'assistant', reply,
                metadata={'reply_group_id': group, 'run_id': scope.run_id})
            self.manager._run_outcome = outcome
        return record

    async def test_create_keeps_selectors_and_context_independent(self):
        state = await self.db.get_conversation_state()
        with bind_conversation(await self.manager.resolve()):
            await self.write('父对话的内容')
        cid = await self.child()
        self.assertEqual(state, await self.db.get_conversation_state() | {'revision': state['revision']})
        child = await self.db.get_session(cid)
        self.assertEqual('global_memory', child['owner_conversation_id'])
        self.assertIsNone(child['parent_conversation_id'])
        self.assertIsNone(child['workspace_path'])
        with bind_conversation(await self.manager.resolve(cid)):
            self.assertEqual([], await self.db.get_conversation_messages())
            await self.write('子对话的内容')
        with bind_conversation(await self.manager.resolve('global_memory')):
            self.assertEqual(['父对话的内容'], [row['content'] for row in await self.db.get_conversation_messages()])

    async def test_create_retry_never_recreates_deleted_child(self):
        first = await self.db.create_child_conversation('global_memory', '检查', request_id='retry')
        self.assertEqual(first, await self.db.create_child_conversation('global_memory', '检查', request_id='retry'))
        with self.assertRaises(ConversationChanged):
            await self.db.create_child_conversation('global_memory', '另一个', request_id='retry')
        await self.db.begin_conversation_delete(first['conversation_id'])
        await self.db.finish_conversation_delete(first['conversation_id'])
        with self.assertRaises(ConversationChanged):
            await self.db.create_child_conversation('global_memory', '检查', request_id='retry')

    async def test_parent_delete_cascades_but_branch_and_other_roots_survive(self):
        child = await self.child()
        grandchild = await self.child(child, '孙对话')
        branch = (await self.db.manage_conversation('create', name='旧分支', select=False))['conversation_id']
        other = (await self.db.manage_conversation('create', name='其他对话', select=False))['conversation_id']
        async with self.db._transaction() as conn:
            await conn.execute('UPDATE chat_sessions SET parent_conversation_id=?,branch_mode=? WHERE id=?',
                               ('global_memory', 'context', branch))
        await self.manager.manage('switch', grandchild)
        info = await self.db.conversation_delete_info('global_memory')
        self.assertEqual(2, info['child_count'])
        await self.db.begin_conversation_delete('global_memory')
        self.assertNotIn((await self.db.get_conversation_state())['current_chat_id'], info['conversation_ids'])
        for cid in info['conversation_ids']:
            self.assertTrue((await self.db.get_session(cid))['deleting'])
            with self.assertRaises(ConversationChanged):
                await self.manager.resolve(cid)
        with self.assertRaises(ConversationError):
            await self.db.finish_conversation_delete('global_memory')
        for cid in (grandchild, child, 'global_memory'):
            await self.db.finish_conversation_delete(cid)
            self.assertIsNone(await self.db.get_session(cid))
        self.assertIsNotNone(await self.db.get_session(branch))
        self.assertIsNotNone(await self.db.get_session(other))

    async def test_child_delete_preserves_parent_sibling_and_shared_files(self):
        left, right = await self.child(name='左'), await self.child(name='右')
        file = Path(self.temp.name) / 'shared.txt'
        file.write_text('keep', encoding='utf-8')
        await self.db.begin_conversation_delete(left)
        await self.db.finish_conversation_delete(left)
        self.assertIsNotNone(await self.db.get_session('global_memory'))
        self.assertIsNotNone(await self.db.get_session(right))
        self.assertEqual('keep', file.read_text(encoding='utf-8'))

    async def test_imported_ownership_cycle_can_be_deleted_without_crossing_other_chats(self):
        child = await self.child()
        other = (await self.db.manage_conversation('create', name='保留', select=False))['conversation_id']
        async with self.db._transaction() as conn:
            await conn.execute('UPDATE chat_sessions SET owner_conversation_id=? WHERE id=?', (child, 'global_memory'))
        await self.db.begin_conversation_delete('global_memory')
        await self.db.finish_conversation_delete(child)
        await self.db.finish_conversation_delete('global_memory')
        self.assertIsNotNone(await self.db.get_session(other))

    async def test_child_uses_parent_workspace_without_owning_its_deletion(self):
        shared = str(Path(self.temp.name) / 'workspace')
        async with self.db._transaction() as conn:
            await conn.execute('UPDATE chat_sessions SET workspace_path=? WHERE id=?', (shared, 'global_memory'))
        child = await self.child()
        nested = await self.child(child)
        self.assertEqual(shared, (await self.manager.resolve(nested)).workspace_path)
        self.assertIsNone((await self.db.get_session(child))['workspace_path'])

    async def test_group_move_keeps_children_attached_and_does_not_reparent(self):
        child = await self.child()
        state = await self.db.get_conversation_state()
        result = await self.db.organize_conversations('create_group', {'name': '工作', 'revision': state['revision']})
        state = await self.db.get_conversation_state()
        await self.db.organize_conversations('move', {'id': 'global_memory', 'group_id': result, 'revision': state['revision']})
        self.assertEqual(result, (await self.db.get_session(child))['group_id'])
        with self.assertRaises(ConversationError):
            await self.db.organize_conversations('move', {'id': child, 'group_id': 'ungrouped', 'revision': (await self.db.get_conversation_state())['revision']})

    async def test_submit_atomically_registers_one_child_and_one_trigger(self):
        text = '保持逐字：\n  $x = "a|b"\n中文\\路径\n'
        job = await self.db.submit_conversation_job('global_memory', text, request_id='job', callback=self.callback())
        retry = await self.db.submit_conversation_job('global_memory', text, request_id='job', callback=self.callback('trg_other'))
        self.assertEqual(job, retry)
        self.assertEqual(2, len(await self.db.get_all_sessions()))
        self.assertEqual(1, len(await self.db.list_trigger_tasks(False)))
        self.assertEqual(text, job['text'])
        self.assertEqual('global_memory', (await self.db.get_conversation_state())['current_chat_id'])
        with self.assertRaises(ConversationChanged):
            await self.db.submit_conversation_job('global_memory', 'different', request_id='job')

    async def test_foreign_conversation_and_stale_parent_are_rejected(self):
        root = (await self.db.manage_conversation('create', name='B', select=False))['conversation_id']
        with self.assertRaises(ConversationChanged):
            await self.db.submit_conversation_job('global_memory', 'test', conversation_id=root)
        with self.assertRaises(ConversationChanged):
            await self.db.submit_conversation_job('global_memory', 'test', generation=-1)

    async def test_resetting_parent_context_keeps_an_already_registered_background_task(self):
        job = await self.db.submit_conversation_job('global_memory', '独立任务', request_id='keep-task')
        with bind_conversation(await self.manager.resolve('global_memory')):
            await self.db.clear_all_conversation_memory()
        self.assertTrue(await self.db.conversation_job_valid(job))
        await self.run_job(job, reply='任务继续完成')
        result = await self.db.conversation_job_result(job['id'])
        self.assertEqual('completed', result['status'])
        self.assertEqual('任务继续完成', result['reply'])

    async def test_exact_reply_survives_later_unrelated_round(self):
        job = await self.db.submit_conversation_job('global_memory', '任务', request_id='first')
        await self.run_job(job, reply='这次的真实结果')
        async with self.manager.operation(await self.manager.resolve(job['conversation_id']), execution=True):
            await self.db.record_global_message(1, 1, 'ai_reply', 'assistant', '后来的其他回答', metadata={'reply_group_id': 'different'})
        result = await self.db.conversation_job_result(job['id'])
        self.assertEqual('completed', result['status'])
        self.assertEqual('这次的真实结果', result['reply'])
        self.assertNotIn('其他回答', json.dumps(result, ensure_ascii=False))
        with self.assertRaises(ConversationChanged):
            await self.db.conversation_job_result(job['id'], 'other-parent')

    async def test_form_pause_is_not_completion_and_resume_keeps_request_link(self):
        job = await self.db.submit_conversation_job('global_memory', '需要表单', request_id='ask')
        await self.run_job(job, reply='填写表单', outcome='ask')
        first = await self.db.conversation_job_result(job['id'])
        self.assertEqual('waiting_form', first['status'])
        self.assertFalse(first['complete'])
        async with self.manager.operation(await self.manager.resolve(job['conversation_id']), execution=True):
            await self.db.bind_conversation_job_run(SimpleNamespace(conversation_id=job['conversation_id'], reply_group_id='group-test'))
            running = await self.db.conversation_job_result(job['id'], include_content=False)
            self.assertEqual('running', running['status'])
            self.assertFalse(running['complete'])
            await self.db.record_global_message(1, 1, 'ai_reply', 'assistant', '表单后的结果', metadata={'reply_group_id': 'group-test'})
        second = await self.db.conversation_job_result(job['id'])
        self.assertEqual('completed', second['status'])
        self.assertTrue(second['complete'])
        self.assertEqual('表单后的结果', second['reply'])
        self.assertNotEqual(first['run_id'], second['run_id'])

    async def test_deleted_child_cancels_callback_without_recreating_request(self):
        job = await self.db.submit_conversation_job('global_memory', '任务', request_id='deleted', callback=self.callback())
        await self.db.begin_conversation_delete(job['conversation_id'])
        await self.db.finish_conversation_delete(job['conversation_id'])
        result = await self.db.conversation_job_result(job['id'])
        self.assertEqual('cancelled', result['status'])
        self.assertFalse(result['ok'])
        self.assertIsNone(await self.db.get_trigger_task(job['trigger_task_id']))
        retry = await self.db.submit_conversation_job('global_memory', '任务', request_id='deleted')
        self.assertEqual(job['conversation_id'], retry['conversation_id'])
        self.assertIsNone(await self.db.get_session(job['conversation_id']))

    async def test_pending_job_dispatch_uses_server_queue_without_switching_or_blocking_parent(self):
        called = []
        async def dispatch(batch):
            called.append((current_scope().conversation_id, batch[0]['text']))
            await self.db.record_global_message(1, 1, 'ai_reply', 'assistant', '模拟模型结果', metadata={'reply_group_id': 'dispatch'})
        queue = self.manager.text_queue = MessageQueue(self.manager, dispatch)
        namespace = {'get_conversations': lambda: self.manager, 'get_text_queue': lambda: queue,
                     'BotConfig': SimpleNamespace(AUTHORIZED_USER_ID=1)}
        job = await self.db.submit_conversation_job('global_memory', '并行任务', request_id='dispatch')
        async with self.manager.operation(await self.manager.resolve('global_memory'), execution=True):
            await poll_conversation_jobs(namespace)
            await queue.poll()
            await asyncio.wait_for(asyncio.gather(*queue._tasks.values()), 15)
            self.assertEqual([(job['conversation_id'], '并行任务')], called)
            self.assertTrue(self.manager.busy('global_memory'))
        self.assertEqual('global_memory', (await self.db.get_conversation_state())['current_chat_id'])
        self.assertEqual('模拟模型结果', (await self.db.conversation_job_result(job['id']))['reply'])
        await poll_conversation_jobs(namespace)
        self.assertEqual([], await self.db.pending_conversation_jobs())

    async def test_disabled_skill_blocks_wrapper_but_common_commands_remain(self):
        await self.db.set_config('disabled_skills', ['background-assistant.md'])
        with self.assertRaises(ConversationError):
            await self.db.submit_conversation_job('global_memory', 'task', source_skill='background-assistant.md')
        self.assertEqual(1, len(await self.db.get_all_sessions()))
        job = await self.db.submit_conversation_job('global_memory', 'other skill')
        self.assertEqual('pending', job['status'])

    async def test_only_the_serving_process_admits_background_jobs(self):
        self.manager.job_admission_enabled = False
        job = await self.db.submit_conversation_job('global_memory', '等待服务接管')
        def forbidden_queue():
            raise AssertionError('a configuration or CLI process must not dispatch another conversation')
        await poll_conversation_jobs({'get_conversations': lambda: self.manager, 'get_text_queue': forbidden_queue})
        self.assertIsNone(self.manager.text_queue)
        self.assertEqual('pending', (await self.db.get_conversation_job(job['id']))['status'])

    async def test_cancel_requests_stop_only_for_the_exact_active_run(self):
        job = await self.db.submit_conversation_job('global_memory', '任务', request_id='cancel-active')
        async with self.manager.operation(await self.manager.resolve(job['conversation_id']), execution=True):
            scope = current_scope()
            item = await self.db.queue_enqueue(scope=scope, instance='1' * 32,
                request_key='conversation-job:' + job['id'], text=job['text'], chat_id=1)
            await self.db.bind_conversation_job_queue(job['id'], item['id'])
            await self.db.queue_claim(scope, first_id=item['id'], owner='1' * 32)
            await self.db.cancel_conversation_job(job['id'])
            self.assertTrue((await self.db.get_conversation_state())['runs'][job['conversation_id']]['stop_requested'])
        async with self.manager.operation(await self.manager.resolve(job['conversation_id']), execution=True):
            await self.db.cancel_conversation_job(job['id'])
            self.assertFalse((await self.db.get_conversation_state())['runs'][job['conversation_id']]['stop_requested'])

    async def test_intermediate_error_is_retained_without_failing_the_completed_reply(self):
        job = await self.db.submit_conversation_job('global_memory', '任务', request_id='intermediate-error')
        await self.run_job(job)
        async with self.db._transaction() as conn:
            turn = await (await conn.execute('SELECT id FROM conversation_turns WHERE conversation_id=?', (job['conversation_id'],))).fetchone()
            await conn.execute('''INSERT INTO global_messages(chat_id,user_id,msg_type,role,content,timestamp,session_id,turn_id,metadata)
                VALUES(1,1,'agent_result','assistant',?,1,?,?,?)''', ('RAW ORIGINAL ERROR', job['conversation_id'], turn['id'],
                    json.dumps({'reply_group_id': 'group-test', 'presentation': {'operation': {'success': False}}})))
        result = await self.db.conversation_job_result(job['id'])
        self.assertEqual('completed', result['status'])
        self.assertTrue(result['ok'])
        self.assertEqual('RAW ORIGINAL ERROR', result['errors'][0]['text'])
        self.assertTrue(result['errors'][0]['intermediate'])

    async def test_schema_9_migration_backs_up_and_keeps_old_branch_provenance(self):
        branch = (await self.db.manage_conversation('create', name='branch', select=False))['conversation_id']
        async with self.db._transaction() as conn:
            await conn.execute('UPDATE chat_sessions SET parent_conversation_id=? WHERE id=?', ('global_memory', branch))
            await conn.execute('DROP TABLE conversation_jobs')
            await conn.execute('DROP INDEX idx_conversation_owner')
            await conn.execute('ALTER TABLE chat_sessions DROP COLUMN owner_conversation_id')
        await self.db.set_config('conversation_schema_version', 9)
        await self.db.backup_legacy_conversations()
        await self.db.migrate_conversations()
        from xgent_app.conversations import SCHEMA_VERSION
        self.assertEqual(SCHEMA_VERSION, await self.db.get_config_fresh('conversation_schema_version'))
        self.assertTrue(Path(self.path + f'.pre-conversations-v{SCHEMA_VERSION}.sqlite3').is_file())
        self.assertEqual('global_memory', (await self.db.get_session(branch))['parent_conversation_id'])
        self.assertIsNone((await self.db.get_session(branch))['owner_conversation_id'])
        self.assertEqual([], await descendant_ids(await self.db._get_conn(), 'global_memory'))


if __name__ == '__main__':
    unittest.main()
