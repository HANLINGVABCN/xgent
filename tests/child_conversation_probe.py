"""Actual queue/Agent/trigger flows against mock providers only."""
import asyncio
import json
from pathlib import Path

from tests.native_tool_probe import NativeHarness, call
from xgent_app.child_conversations import poll_conversation_jobs
from xgent_app.conversations import bind_conversation


async def queue_and_callback(bot, root, mode='toolcall', style='nonstream'):
    async with NativeHarness(bot, root, 'openai_compatible', style) as h:
        manager = bot.get_conversations()
        manager.job_admission_enabled = True
        manager.code_root = Path(root)
        queue = bot.get_text_queue()
        await bot.UserDataManager.save_config('agent_call_mode', mode)
        await h.db.record_global_message(1, 1, 'user_text', 'user', 'PARENT_CONTEXT_ONLY')
        command = 'MOCK_CHILD_COMMAND'
        first = ([call(command=command)], '') if mode == 'toolcall' else (
            [], '```run-x\n<<BEGIN_run_child\n' + command + '\n<<END_run_child\n```')
        h.responses = [first, ([], 'CHILD_FINAL_RESULT'), ([], 'PARENT_AFTER_CHILD')]
        task = {'id': 'trg_child', 'chat_id': 1, 'conversation_id': 'global_memory', 'command': 'echo mocked',
                'summary': '核对独立任务', 'schedule_type': 'once', 'timezone': 'UTC',
                'status': 'pending', 'created_at': 1, 'updated_at': 1}
        job = await h.db.submit_conversation_job('global_memory', 'CHILD_CONTEXT_ONLY', request_id='native-child', callback=task)
        await poll_conversation_jobs(vars(bot))
        await queue.poll()
        await asyncio.wait_for(asyncio.gather(*queue._tasks.values()), 45)
        result = await h.db.conversation_job_result(job['id'])
        assert result['status'] == 'completed' and result['reply'] == 'CHILD_FINAL_RESULT', result
        assert h.executed == [command], h.executed
        assert 'PARENT_CONTEXT_ONLY' not in json.dumps(h.requests[0]), h.requests[0]
        assert 'CHILD_CONTEXT_ONLY' in json.dumps(h.requests[0]), h.requests[0]
        assert (await h.db.get_conversation_state())['current_chat_id'] == 'global_memory'
        run, _ = await h.db.create_trigger_run(task['id'], 123, 'process_exit')
        await h.db.finish_trigger_run(run['run_id'], finished_at=124, status='completed', exit_code=0,
                                      output=json.dumps(result, ensure_ascii=False))
        await bot.SelfTriggerManager._deliver_run(run['run_id'])
        await bot.SelfTriggerManager._deliver_run(run['run_id'])
        assert len(h.requests) == 3, h.requests
        parent_request = json.dumps(h.requests[-1])
        assert 'CHILD_FINAL_RESULT' in parent_request and 'PARENT_CONTEXT_ONLY' in parent_request
        if mode == 'toolcall':
            from xgent_app.tool_calls import TOOLS
            assert all(len(request['tools']) == len(TOOLS) for request in h.requests)
        parent_rows = await h.db.get_display_history(100)
        assert any(row['content'] == 'PARENT_AFTER_CHILD' for row in parent_rows)
        assert not any(row['content'] == 'CHILD_FINAL_RESULT' for row in parent_rows)
        with bind_conversation(await manager.resolve(job['conversation_id'])):
            child_rows = await h.db.get_display_history(100)
            assert any(row['content'] == 'CHILD_FINAL_RESULT' for row in child_rows)
            assert not any(row['content'] == 'PARENT_AFTER_CHILD' for row in child_rows)
        await manager.close()
        return {'isolated': True, 'ordered_tools': True, 'callback_once': True, 'mode': mode, 'style': style}


async def cancel_form_job(bot, root):
    async with NativeHarness(bot, root, 'openai', 'nonstream') as h:
        manager = bot.get_conversations()
        manager.job_admission_enabled = True
        manager.code_root = Path(root)
        queue = bot.get_text_queue()
        h.responses = [([call('ask_user', 'ask-child', questions=[{'label': 'Q1', 'type': 'text', 'prompt': 'Value?'}]),
                         call(cid='after-child-ask', command='MUST_NOT_EXECUTE')], 'FORM_PREVIEW')]
        job = await h.db.submit_conversation_job('global_memory', '需要确认', request_id='form-child')
        await poll_conversation_jobs(vars(bot))
        await queue.poll()
        await asyncio.wait_for(asyncio.gather(*queue._tasks.values()), 45)
        pending = next(iter(bot.PENDING_ASKS.values()))
        result = await h.db.conversation_job_result(job['id'])
        assert result['status'] == 'waiting_form' and not result['complete'], result
        await h.db.cancel_conversation_job(job['id'])
        with bind_conversation(await manager.resolve(job['conversation_id'])):
            pending.ensure_entry('0')['custom'] = 'CONFIRMED'
            await bot.resume_from_ask(pending.ask_id)
        assert h.executed == [], h.executed
        assert len(h.requests) == 1, h.requests
        assert bot.PENDING_ASKS.get(pending.ask_id) is None
        assert pending.status == 'cancelled'
        await manager.close()
        return {'waiting_not_done': True, 'cancel_prevents_resume': True, 'no_extra_model': True}


async def delete_running_tree(bot, root):
    from unittest.mock import patch
    async with NativeHarness(bot, root, 'openai', 'nonstream') as h:
        manager = bot.get_conversations()
        manager.job_admission_enabled = True
        manager.code_root = Path(root)
        manager.maintenance = bot._conversation_maintenance
        queue = bot.get_text_queue()
        entered = asyncio.Event()
        async def slow_command(command, stop_event=None):
            entered.set()
            await stop_event.wait()
            return {'success': False, 'stopped': True, 'return_code': -1, 'output': 'STOPPED_ACTUAL_RUN'}
        h.responses = [([call(command='mocked-running-only')], ''), ([], 'MUST_NOT_GENERATE')]
        task = {'id': 'trg_deleted_child', 'chat_id': 1, 'conversation_id': 'global_memory', 'command': 'echo mocked',
                'summary': '删除中的助手', 'schedule_type': 'once', 'timezone': 'UTC',
                'status': 'pending', 'created_at': 1, 'updated_at': 1}
        job = await h.db.submit_conversation_job('global_memory', '运行中的任务', request_id='deleted-running', callback=task)
        grandchild = (await h.db.create_child_conversation(job['conversation_id'], '更下层'))['conversation_id']
        other = (await h.db.manage_conversation('create', name='保留的对话', select=False))['conversation_id']
        late, _ = await h.db.create_trigger_run(task['id'], 456, 'process_exit')
        with patch.object(bot.AgentExecutor, 'run_command', slow_command):
            await poll_conversation_jobs(vars(bot))
            await queue.poll()
            await asyncio.wait_for(entered.wait(), 45)
            result = await bot.delete_conversation('global_memory')
            assert set(result['deleted_conversation_ids']) == {'global_memory', job['conversation_id'], grandchild}
            async def drained():
                while await h.db.get_session('global_memory'):
                    await manager.poll_once()
                    await asyncio.sleep(.05)
            await asyncio.wait_for(drained(), 45)
        assert await h.db.get_session(job['conversation_id']) is None
        assert await h.db.get_session(grandchild) is None
        assert await h.db.get_session(other) is not None
        await bot.SelfTriggerManager._deliver_run(late['run_id'])
        assert len(h.requests) == 1, h.requests
        assert await h.db.get_trigger_task(task['id']) is None
        assert (await h.db.get_conversation_state())['current_chat_id'] == other
        await manager.close()
        return {'cascade': True, 'running_stopped': True, 'late_ignored': True, 'other_survives': True}


async def finish_without_prose(bot, root):
    async with NativeHarness(bot, root, 'openai', 'nonstream') as h:
        manager = bot.get_conversations()
        manager.job_admission_enabled = True
        manager.code_root = Path(root)
        queue = bot.get_text_queue()
        h.responses = [([call(command='mocked-only'),
                         call('finish_task', 'finish-child', message='结果在工具输出中')], '')]
        job = await h.db.submit_conversation_job('global_memory', '检查后直接结束', request_id='finish-only')
        await poll_conversation_jobs(vars(bot))
        await queue.poll()
        await asyncio.wait_for(asyncio.gather(*queue._tasks.values()), 45)
        result = await h.db.conversation_job_result(job['id'])
        assert result['status'] == 'completed' and result['ok'], result
        assert any('ACTUAL_RESULT' in item['text'] for item in result['tool_results']), result
        assert len(h.requests) == 1 and h.executed == ['mocked-only']
        await manager.close()
        return {'completed': True, 'real_tool_result': True, 'no_extra_generation': True}
