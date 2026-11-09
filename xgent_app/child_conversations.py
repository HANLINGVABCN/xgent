"""Reusable child conversations and exact background-request results.

Children own their context and runs, but share files with their parent. Jobs are
admitted by the existing server queue; the CLI never runs a second model engine.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid

from .conversations import ConversationChanged, ConversationError
from .queue_store import one, rows


TERMINAL_STATUSES = {'completed', 'failed', 'stopped', 'interrupted', 'cancelled',
                     'invalidated', 'withdrawn', 'empty'}


def object_dict(value):
    if isinstance(value, dict):
        return value
    try:
        result = json.loads(value or '{}')
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


async def config(conn, key, default=None):
    row = await one(conn, 'SELECT value FROM config WHERE key=?', (key,))
    return json.loads(row['value']) if row else default


async def migrate_children(conn):
    columns = {row['name'] for row in await rows(conn, 'PRAGMA table_info(chat_sessions)')}
    if 'owner_conversation_id' not in columns:
        await conn.execute('ALTER TABLE chat_sessions ADD COLUMN owner_conversation_id TEXT')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_conversation_owner ON chat_sessions(owner_conversation_id)')
    await conn.execute('''CREATE TABLE IF NOT EXISTS conversation_jobs (
        id TEXT PRIMARY KEY,parent_conversation_id TEXT NOT NULL,parent_generation INTEGER NOT NULL,
        conversation_id TEXT NOT NULL,generation INTEGER NOT NULL,text TEXT NOT NULL,
        source_skill TEXT,status TEXT NOT NULL,queue_id TEXT,trigger_task_id TEXT UNIQUE,current_run_id TEXT,
        created_at REAL NOT NULL,updated_at REAL NOT NULL,error TEXT)''')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_conversation_jobs_pending ON conversation_jobs(status,created_at)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_conversation_jobs_owner ON conversation_jobs(parent_conversation_id,conversation_id)')
    job_columns = {row['name'] for row in await rows(conn, 'PRAGMA table_info(conversation_jobs)')}
    if 'current_run_id' not in job_columns:
        await conn.execute('ALTER TABLE conversation_jobs ADD COLUMN current_run_id TEXT')


async def descendant_ids(conn, cid):
    # UNION also terminates malformed cycles in restored data. Branch provenance
    # (parent_conversation_id) deliberately does not participate in ownership.
    return [row['id'] for row in await rows(conn, '''WITH RECURSIVE children(id) AS (
        SELECT id FROM chat_sessions WHERE owner_conversation_id=? AND id<>?
        UNION SELECT s.id FROM chat_sessions s JOIN children c ON s.owner_conversation_id=c.id WHERE s.id<>?
        ) SELECT id FROM children''', (cid, cid, cid))]


class ChildConversationStore:
    async def _child_parent(self, conn, parent_id, generation=None):
        parent = await one(conn, 'SELECT * FROM chat_sessions WHERE id=?', (parent_id,))
        if not parent or parent['deleting']:
            raise ConversationChanged('父对话不存在或已删除。')
        if generation is not None and generation != parent['generation']:
            raise ConversationChanged('父对话上下文已改变，本次任务未提交。')
        return parent

    async def _new_child(self, conn, parent, name):
        if parent['archived'] and name is None:
            count=await one(conn,'SELECT COUNT(*) n FROM chat_sessions WHERE owner_conversation_id=?',(parent['id'],))
            name='子对话 '+str(count['n']+1)
        cid = await self._new_conversation(conn, name)
        await conn.execute('UPDATE chat_sessions SET owner_conversation_id=?,group_id=? WHERE id=?',
                           (parent['id'], parent['group_id'], cid))
        if parent['archived']:
            from .archive_conversations import archive_origin, ARCHIVE_GROUP_ID
            await conn.execute('UPDATE chat_sessions SET archived=1,group_id=?,archive_origin=?,title_auto_pending=0 WHERE id=?',
                               (ARCHIVE_GROUP_ID,json.dumps({**archive_origin(parent),'pinned':False},ensure_ascii=False),cid))
        return cid

    async def create_child_conversation(self, parent_id, name=None, *, generation=None, request_id=None):
        if name is not None and (not str(name).strip() or len(str(name).strip()) > 80):
            raise ConversationError('会话名称需要 1–80 个字符。')
        name = str(name).strip() if name is not None else None
        async with self._transaction() as conn:
            parent = await self._child_parent(conn, parent_id, generation)
            if request_id:
                old = await one(conn, 'SELECT * FROM conversation_mutation_requests WHERE request_id=?', (request_id,))
                if old:
                    response = object_dict(old['response'])
                    if (old['operation'] != 'create_child' or old['conversation_id'] != parent_id
                            or response.get('requested_name') != name):
                        raise ConversationChanged('请求标识已用于另一项操作。')
                    child = await one(conn, 'SELECT id FROM chat_sessions WHERE id=? AND deleting=0', (response.get('conversation_id'),))
                    if not child:
                        raise ConversationChanged('该请求创建的子对话已删除，不会重新创建。')
                    return response
            cid = await self._new_child(conn, parent, name)
            response = {'ok': True, 'conversation_id': cid, 'parent_conversation_id': parent_id,
                        'requested_name': name}
            if request_id:
                await conn.execute('INSERT INTO conversation_mutation_requests VALUES(?,?,?,?,?)',
                    (request_id, 'create_child', parent_id, json.dumps(response, ensure_ascii=False), time.time()))
            await self._bump_conversation_revision(conn)
            return response

    async def submit_conversation_job(self, parent_id, text, *, request_id=None, conversation_id=None,
                                      name=None, generation=None, source_skill=None, callback=None):
        if not isinstance(text, str) or not text.strip():
            raise ConversationError('任务内容不能为空。')
        if name is not None and (not str(name).strip() or len(str(name).strip()) > 80):
            raise ConversationError('会话名称需要 1–80 个字符。')
        request_id = request_id or uuid.uuid4().hex
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request_id):
            raise ConversationError('请求标识格式无效。')
        async with self._transaction() as conn:
            old = await one(conn, 'SELECT * FROM conversation_jobs WHERE id=?', (request_id,))
            if old:
                if (old['parent_conversation_id'] != parent_id or old['text'] != text
                        or old['source_skill'] != source_skill
                        or conversation_id and old['conversation_id'] != conversation_id):
                    raise ConversationChanged('请求标识已用于另一条任务。')
                return old
            parent = await self._child_parent(conn, parent_id, generation)
            if source_skill and not await self._job_skill_enabled(conn, source_skill):
                raise ConversationError('该技能已关闭，未创建后台助手任务。')
            if conversation_id:
                child = await one(conn, 'SELECT * FROM chat_sessions WHERE id=?', (conversation_id,))
                if (not child or child['deleting']
                        or child['owner_conversation_id'] != parent_id):
                    raise ConversationChanged('目标不是这个父对话的可用子对话。')
            else:
                cid = await self._new_child(conn, parent, str(name).strip() if name is not None else None)
                child = await one(conn, 'SELECT * FROM chat_sessions WHERE id=?', (cid,))
            if callback:
                if callback['conversation_id'] != parent_id:
                    raise ConversationChanged('后台结果的目标父对话不匹配。')
                await self._insert_trigger_task(conn, callback)
            now = time.time()
            await conn.execute('''INSERT INTO conversation_jobs
                (id,parent_conversation_id,parent_generation,conversation_id,generation,text,source_skill,
                 status,trigger_task_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'pending',?,?,?)''',
                (request_id, parent_id, parent['generation'], child['id'], child['generation'], text,
                 source_skill, callback['id'] if callback else None, now, now))
            await self._bump_conversation_revision(conn)
            return await one(conn, 'SELECT * FROM conversation_jobs WHERE id=?', (request_id,))

    @staticmethod
    async def _job_skill_enabled(conn, skill):
        disabled = await config(conn, 'disabled_skills', [])
        hidden = await config(conn, 'hidden_skills', [])
        return skill not in (disabled if isinstance(disabled, list) else []) and skill not in (hidden if isinstance(hidden, list) else [])

    async def get_conversation_job(self, request_id, parent_id=None):
        job = await one(await self._get_conn(), 'SELECT * FROM conversation_jobs WHERE id=?', (request_id,))
        if job and parent_id is not None and job['parent_conversation_id'] != parent_id:
            raise ConversationChanged('该任务不属于这个父对话。')
        return job

    async def conversation_job_valid(self, job):
        conn = await self._get_conn()
        parent = await one(conn, 'SELECT generation,deleting FROM chat_sessions WHERE id=?', (job['parent_conversation_id'],))
        child = await one(conn, 'SELECT generation,deleting FROM chat_sessions WHERE id=?', (job['conversation_id'],))
        return bool(parent and child and not parent['deleting'] and not child['deleting']
                    and child['generation'] == job['generation']
                    and job['status'] not in {'cancelled', 'invalidated'}
                    and (not job['source_skill'] or await self._job_skill_enabled(conn, job['source_skill'])))

    async def conversation_job_for_trigger(self, task_id):
        return await one(await self._get_conn(), 'SELECT * FROM conversation_jobs WHERE trigger_task_id=?', (task_id,))

    async def conversation_job_for_form(self, pending):
        if not pending.reply_group_id:
            return None
        return await one(await self._get_conn(), '''SELECT j.* FROM conversation_jobs j
            JOIN message_queue q ON q.request_key='conversation-job:'||j.id
            WHERE j.conversation_id=? AND EXISTS (
                SELECT 1 FROM global_messages m WHERE m.session_id=j.conversation_id AND m.id>=q.record_id
                AND json_extract(CASE WHEN json_valid(m.metadata) THEN m.metadata ELSE '{}' END,'$.run_id')=q.run_id
                AND json_extract(CASE WHEN json_valid(m.metadata) THEN m.metadata ELSE '{}' END,'$.reply_group_id')=?)
            ORDER BY j.created_at DESC LIMIT 1''', (pending.conversation_id, pending.reply_group_id))

    async def bind_conversation_job_run(self, pending):
        job = await self.conversation_job_for_form(pending)
        if job is None:
            return
        from .conversations import current_scope
        scope = current_scope()
        async with self._transaction() as conn:
            fresh = await one(conn, 'SELECT status FROM conversation_jobs WHERE id=?', (job['id'],))
            if not fresh or fresh['status'] in {'cancelled', 'invalidated'}:
                raise ConversationChanged('后台任务已取消，表单不会继续执行。')
            if job['conversation_id'] != scope.conversation_id or job['generation'] != scope.generation:
                raise ConversationChanged('表单不属于当前后台任务。')
            await conn.execute('UPDATE conversation_jobs SET current_run_id=?,updated_at=? WHERE id=?',
                               (scope.run_id, time.time(), job['id']))

    async def pending_conversation_jobs(self):
        return await rows(await self._get_conn(), "SELECT * FROM conversation_jobs WHERE status IN ('pending','queued') ORDER BY created_at,id")

    async def bind_conversation_job_queue(self, request_id, queue_id):
        async with self._transaction() as conn:
            await conn.execute("UPDATE conversation_jobs SET queue_id=?,status='queued',updated_at=? WHERE id=? AND status='pending'",
                               (queue_id, time.time(), request_id))

    async def settle_conversation_job(self, request_id, status):
        if status not in TERMINAL_STATUSES:
            return
        async with self._transaction() as conn:
            await conn.execute("UPDATE conversation_jobs SET status=?,updated_at=? WHERE id=? AND status IN ('pending','queued')",
                               (status, time.time(), request_id))

    async def cancel_conversation_job(self, request_id, parent_id=None, *, reason='任务已取消'):
        result = await self.conversation_job_result(request_id, parent_id, include_content=False, _allow_invalid=True)
        async with self._transaction() as conn:
            job = await one(conn, 'SELECT * FROM conversation_jobs WHERE id=?', (request_id,))
            if not job or parent_id is not None and job['parent_conversation_id'] != parent_id:
                raise ConversationChanged('未找到这个父对话的任务。')
            await conn.execute("UPDATE conversation_jobs SET status='cancelled',error=?,updated_at=? WHERE id=?",
                               (reason, time.time(), request_id))
            if job['trigger_task_id']:
                await conn.execute("UPDATE trigger_tasks SET status='cancelled',next_run_at=NULL,updated_at=? WHERE id=?",
                                   (time.time(), job['trigger_task_id']))
            await conn.execute("UPDATE message_queue SET status='cancelled',revision=revision+1,updated_at=? "
                               "WHERE request_key=? AND status IN ('pending','paused','invalid')",
                               (time.time(), 'conversation-job:' + request_id))
            runs = await config(conn, 'conversation_runs', {})
            running = runs.get(job['conversation_id'])
            if running and result.get('run_id') == running['run_id']:
                running['stop_requested'] = True
                await conn.execute('UPDATE config SET value=? WHERE key=?',
                                   (json.dumps(runs, ensure_ascii=False), 'conversation_runs'))
            from .queue_store import bump
            await bump(conn)
        return {**job, 'status': 'cancelled', 'error': reason}

    async def conversation_job_result(self, request_id, parent_id=None, *, include_content=True, _allow_invalid=False):
        job = await self.get_conversation_job(request_id, parent_id)
        if not job:
            raise ConversationChanged('任务记录不存在；不会取其他回合的结果。')
        base = {'ok': True, 'request_id': job['id'], 'conversation_id': job['conversation_id'],
                'parent_conversation_id': job['parent_conversation_id'], 'trigger_task_id': job['trigger_task_id'],
                'status': job['status'], 'complete': False, 'reply': '', 'replies': [], 'tool_results': [], 'media': [], 'errors': []}
        if not _allow_invalid and not await self.conversation_job_valid(job):
            status = 'cancelled' if job['status'] == 'cancelled' else 'invalidated'
            return {**base, 'ok': False, 'status': status, 'complete': True,
                    'error': job['error'] or '所属对话或上下文已改变，任务结果不会改投其他回合。'}
        conn = await self._get_conn()
        item = await one(conn, 'SELECT * FROM message_queue WHERE request_key=?', ('conversation-job:' + request_id,))
        if not item:
            if job['status'] != 'pending':
                return {**base, 'ok': False, 'status': 'interrupted', 'complete': True,
                        'error': '任务接收记录未恢复，不会自动重复发送。'}
            return base
        base.update(queue_id=item['id'], queue_status=item['status'], run_id=item['run_id'], reason=item['reason'])
        if not item['run_id'] or not item['record_id']:
            status = 'invalidated' if item['status'] == 'invalid' else item['status']
            return {**base, 'status': status, 'complete': status in TERMINAL_STATUSES,
                    'ok': status not in TERMINAL_STATUSES}
        cid = job['conversation_id']
        source = await one(conn, 'SELECT id FROM global_messages WHERE id=? AND session_id=? AND withdrawn=0', (item['record_id'], cid))
        if not source:
            return {**base, 'ok': False, 'status': 'withdrawn', 'complete': True, 'error': '任务输入已撤回。'}
        turn = await one(conn, 'SELECT * FROM conversation_turns WHERE conversation_id=? AND run_id=?', (cid, item['run_id']))
        continuing = await one(conn, 'SELECT * FROM conversation_turns WHERE conversation_id=? AND run_id=?',
                               (cid, job.get('current_run_id'))) if job.get('current_run_id') else None
        fields = '*' if include_content else "id,turn_id,json_extract(CASE WHEN json_valid(metadata) THEN metadata ELSE '{}' END,'$.reply_group_id') reply_group_id"
        records = await rows(conn, f'''SELECT {fields} FROM global_messages WHERE session_id=? AND id>=? AND withdrawn=0
            AND (json_extract(CASE WHEN json_valid(metadata) THEN metadata ELSE '{{}}' END,'$.run_id') IN (?,?) OR turn_id IN (?,?)) ORDER BY id''',
            (cid, item['record_id'], item['run_id'], job.get('current_run_id'), turn['id'] if turn else None,
             continuing['id'] if continuing else None))
        group = next((value for row in records if (value := (
            object_dict(row['metadata']).get('reply_group_id') if include_content else row['reply_group_id']))), None)
        if group:
            records = await rows(conn, f'''SELECT {fields} FROM global_messages WHERE session_id=? AND id>=? AND withdrawn=0
                AND (json_extract(CASE WHEN json_valid(metadata) THEN metadata ELSE '{{}}' END,'$.reply_group_id')=?
                    OR json_extract(CASE WHEN json_valid(metadata) THEN metadata ELSE '{{}}' END,'$.run_id')=? OR turn_id=?) ORDER BY id''',
                (cid, item['record_id'], group, job.get('current_run_id'), continuing['id'] if continuing else None))
            related = await one(conn, '''SELECT t.* FROM conversation_turns t WHERE t.conversation_id=? AND EXISTS (
                SELECT 1 FROM global_messages m WHERE m.session_id=? AND m.turn_id=t.id AND m.id>=? AND m.withdrawn=0
                AND json_extract(CASE WHEN json_valid(m.metadata) THEN m.metadata ELSE '{}' END,'$.reply_group_id')=?)
                ORDER BY t.started_at DESC,t.id DESC LIMIT 1''', (cid, cid, item['record_id'], group))
            turn = related or turn
        turn = continuing or turn
        base.update(reply_group_id=group, run_id=job.get('current_run_id') or (turn['run_id'] if turn else item['run_id']))
        seen_media = set()
        for row in records if include_content else []:
            meta = object_dict(row['metadata'])
            if meta.get('ui_only') or meta.get('ui_audit'):
                continue
            if row['msg_type'] == 'ai_reply':
                base['replies'].append({'record_id': row['id'], 'text': row['content']})
            if row['msg_type'] == 'runtime_error':
                base['errors'].append({'record_id': row['id'], 'text': row['content']})
            elif row['msg_type'] == 'agent_result':
                operation = object_dict(meta.get('presentation')).get('operation') or {}
                base['tool_results'].append({'record_id': row['id'], 'text': row['content'],
                    **{key: operation[key] for key in ('kind', 'output_path') if key in operation}})
                if operation.get('success') is False:
                    base['errors'].append({'record_id': row['id'], 'text': row['content'], 'intermediate': True})
            for media in meta.get('attachments') or []:
                if not isinstance(media, dict):
                    continue
                path = media.get('artifact_path') or media.get('path')
                if path and path not in seen_media:
                    seen_media.add(path)
                    base['media'].append({key: media[key] for key in ('path', 'artifact_path', 'storage', 'filename', 'mime_type') if key in media})
        final_id = turn.get('final_record_id') if turn else None
        final = next((reply for reply in base['replies'] if reply['record_id'] == final_id), None)
        if final is None and base['replies']:
            final = base['replies'][-1]
        base['reply'] = final['text'] if final else ''
        status = turn['status'] if turn else item['status']
        active = (await config(conn, 'conversation_runs', {})).get(cid) or {}
        if active.get('run_id') == base['run_id'] or status in {'running', 'claimed'}:
            status = 'running'
        elif status == 'ask':
            status = 'waiting_form'
            control = await one(conn, 'SELECT state,reason FROM message_queue_controls WHERE conversation_id=?', (cid,))
            if control and control['state'] == 'paused' and control['reason'] == 'restart':
                status = 'interrupted'
        if item['status'] == 'interrupted' and status not in {'completed', 'failed', 'stopped'}:
            status = 'interrupted'
        base.update(status=status, complete=status in TERMINAL_STATUSES,
                    ok=status not in TERMINAL_STATUSES - {'completed'})
        if not base['ok']:
            base['error'] = (turn.get('error') if turn else None) or item['reason'] or '运行未正常完成'
        return base


async def poll_conversation_jobs(namespace):
    """Admit through the normal queue, including when Web/Telegram is disabled."""
    manager = namespace['get_conversations']()
    if not manager.job_admission_enabled:
        return
    lock = getattr(manager, '_child_admission_lock', None)
    if lock is None:
        lock = manager._child_admission_lock = asyncio.Lock()
    if lock.locked():
        return
    from .conversations import bind_conversation
    from .interaction import interaction
    async with lock:
        db = await manager.factory()
        for job in await db.pending_conversation_jobs():
            try:
                callback = await db.get_trigger_task(job['trigger_task_id']) if job['trigger_task_id'] else None
                invalid = not await db.conversation_job_valid(job)
                cancelled = bool(callback and callback['status'] == 'cancelled')
                if invalid or cancelled:
                    result = await db.conversation_job_result(job['id'], include_content=False, _allow_invalid=True)
                    await db.cancel_conversation_job(job['id'], reason='技能已关闭、任务已取消或所属上下文已改变')
                    if result.get('run_id'):
                        await manager.request_stop(result['run_id'], job['conversation_id'], reason='cancel_child_job')
                    continue
                if job['status'] == 'queued':
                    item = await db.queue_item(job['queue_id']) if job['queue_id'] else None
                    if not item or item['status'] in {'completed', 'interrupted', 'cancelled', 'invalid', 'edited'}:
                        result = await db.conversation_job_result(job['id'], include_content=False)
                        if result['complete']:
                            await db.settle_conversation_job(job['id'], result['status'])
                    continue
                session = await db.get_session(job['conversation_id'])
                # Only the serving process invokes this maintenance hook. Its
                # live queue instance owns admission; short-lived CLIs do not.
                with interaction('web', 'chat'), bind_conversation(None):
                    scope = await manager.resolve(job['conversation_id'])
                    with bind_conversation(scope):
                        item = await namespace['get_text_queue']().submit(job['text'],
                            chat_id=namespace['BotConfig'].AUTHORIZED_USER_ID,
                            request_key='conversation-job:' + job['id'])
                await db.bind_conversation_job_queue(job['id'], item['id'])
            except ConversationChanged:
                # A deletion/reset may win between checks and queue admission.
                continue
            except Exception:
                logging.getLogger(__name__).exception('子对话任务接纳待重试: %s', job['id'])
        from .agent_ask import PENDING_ASKS
        for pending in PENDING_ASKS.values():
            job = await db.conversation_job_for_form(pending)
            if job is None or await db.conversation_job_valid(job):
                continue
            try:
                scope = await manager.resolve(pending.conversation_id, allow_archived=True)
                with bind_conversation(scope):
                    async with pending.lock:
                        await reject_cancelled_job_form(namespace, pending)
            except ConversationChanged:
                pass  # Permanent deletion purges these forms in its own cleanup.


async def reject_cancelled_job_form(namespace, pending):
    if pending is None:
        return False
    db = await namespace['BotMemoryDB'].get_instance()
    job = await db.conversation_job_for_form(pending)
    if job is None or await db.conversation_job_valid(job):
        return False
    from .agent_ask import PENDING_ASKS
    from .web_ask import sync_ask
    PENDING_ASKS.pop(pending.ask_id)
    pending.status = 'cancelled'
    await sync_ask(namespace, pending, status='cancelled')
    queue = namespace['get_text_queue']()
    await queue.start()
    from .conversations import current_scope
    await db.queue_resume(current_scope(), queue.instance, ask=True, cancel_ask=True)
    return True
