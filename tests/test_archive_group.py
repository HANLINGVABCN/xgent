"""Archived conversations are a hidden, writable group with reversible ownership trees."""
import json
import unittest
from pathlib import Path

from tests import test_conversations as support
from xgent_app.archive_conversations import ARCHIVE_GROUP_ID, archive_origin
from xgent_app.conversations import ConversationError, bind_conversation
from xgent_app.conversation_branching import ConversationBranchService, BranchingError
from xgent_app.queue_store import one


class ArchiveGroupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=support.ConversationTests.asyncSetUp
    asyncTearDown=support.ConversationTests.asyncTearDown
    write=support.ConversationTests.write

    async def organize(self,action,**data):
        state=await self.db.get_conversation_state()
        return await self.db.organize_conversations(action,{'revision':state['revision'],**data})

    async def test_archive_moves_tree_without_changing_context_and_restore_returns_groups_and_pins(self):
        group=await self.organize('create_group',name='项目资料')
        parent=(await self.manager.manage('create',name='可继续的归档对话'))['conversation_id']
        await self.organize('move',id=parent,group_id=group)
        await self.organize('pin',id=parent,group_id=group)
        child=(await self.db.create_child_conversation(parent,'已有子对话'))['conversation_id']
        nested=(await self.db.create_child_conversation(child,'孙对话'))['conversation_id']
        scope=await self.manager.resolve(parent)
        with bind_conversation(scope):
            before=await self.write('完整上下文保留')
        archived=await self.manager.manage('archive',parent)
        self.assertEqual({parent,child,nested},set(archived['archived_conversation_ids']))
        self.assertNotIn(ARCHIVE_GROUP_ID,{group['id'] for group in await self.db.get_conversation_groups()})
        for cid in (parent,child,nested):
            session=await self.db.get_session(cid)
            self.assertTrue(session['archived'])
            self.assertEqual(ARCHIVE_GROUP_ID,session['group_id'])
            self.assertEqual(group,archive_origin(session)['group_id'])
            self.assertEqual('项目资料',archive_origin(session)['group_name'])
        with bind_conversation(await self.manager.resolve(parent)):
            self.assertIn('完整上下文保留',str(await self.db.get_conversation_messages()))
            await self.write('归档后仍可正常记录对话')
        self.assertEqual(scope.generation,(await self.manager.resolve(parent)).generation)
        fresh=(await self.db.create_child_conversation(parent))['conversation_id']
        self.assertTrue((await self.db.get_session(fresh))['archived'])
        self.assertEqual(group,archive_origin(await self.db.get_session(fresh))['group_id'])
        with self.assertRaises(ConversationError):
            await self.manager.manage('rename',parent,name='不允许的改名')
        with self.assertRaises(ConversationError):
            await self.organize('move',id=parent,group_id='ungrouped')
        service=ConversationBranchService(self.db,code_root=self.temp.name,storage_root=Path(self.temp.name)/'storage')
        with self.assertRaises(BranchingError):
            await service.branch_preview(parent,before,'user')
        with self.assertRaises(BranchingError):
            await service.create_branch(parent,before,'user')
        restored=await self.manager.manage('restore',parent)
        self.assertEqual({parent,child,nested,fresh},set(restored['restored_conversation_ids']))
        for cid in (parent,child,nested,fresh):
            session=await self.db.get_session(cid)
            self.assertFalse(session['archived'])
            self.assertEqual(group,session['group_id'])
            self.assertIsNone(session['archive_origin'])
        self.assertTrue((await self.db.get_session(parent))['pinned'])
        self.assertFalse((await self.db.get_session(fresh))['pinned'])
        self.assertEqual(parent,(await self.db.get_session(child))['owner_conversation_id'])
        self.assertEqual(child,(await self.db.get_session(nested))['owner_conversation_id'])

    async def test_hidden_group_is_reserved_and_deleted_original_group_restores_to_default(self):
        group=await self.organize('create_group',name='原分组')
        parent=(await self.manager.manage('create',name='原分组被删除'))['conversation_id']
        await self.organize('move',id=parent,group_id=group)
        await self.organize('pin',id=parent,group_id=group)
        await self.manager.manage('archive',parent)
        for action in ('rename_group','delete_group'):
            with self.assertRaises(ConversationError):
                await self.organize(action,group_id=ARCHIVE_GROUP_ID,name='不能改名')
        with self.assertRaises(ConversationError):
            await self.organize('create_group',name='归档')
        await self.organize('delete_group',group_id=group)
        self.assertEqual('原分组',archive_origin(await self.db.get_session(parent))['group_name'])
        await self.manager.manage('restore',parent)
        self.assertEqual('ungrouped',(await self.db.get_session(parent))['group_id'])
        self.assertFalse((await self.db.get_session(parent))['pinned'])

    async def test_migration_preserves_old_group_and_only_releases_archive_pauses(self):
        group=await self.organize('create_group',name='旧版原分组')
        parent=(await self.manager.manage('create',name='旧版归档'))['conversation_id']
        child=(await self.db.create_child_conversation(parent,'旧版子对话'))['conversation_id']
        stopped=(await self.manager.manage('create',name='手动停止保持'))['conversation_id']
        async with self.db._transaction() as conn:
            await conn.execute('UPDATE chat_sessions SET archived=1,group_id=?,pinned=1,archive_origin=NULL WHERE id=?',(group,parent))
            await conn.execute('UPDATE chat_sessions SET group_id=? WHERE id=?',(group,child))
            await conn.execute("INSERT INTO message_queue_controls VALUES(?,?,'paused','archived',NULL)",(parent,(await self.db.get_session(parent))['generation']))
            await conn.execute("INSERT INTO message_queue_controls VALUES(?,?,'paused','stopped',NULL)",(stopped,(await self.db.get_session(stopped))['generation']))
            await conn.execute("UPDATE config SET value='10' WHERE key='conversation_schema_version'")
            await conn.execute("UPDATE config SET value=? WHERE key IN ('current_chat_id','telegram_conversation_id')", (json.dumps(child),))
        await self.db.migrate_conversations()
        for cid in (parent,child):
            self.assertTrue((await self.db.get_session(cid))['archived'])
            self.assertEqual(group,archive_origin(await self.db.get_session(cid))['group_id'])
        state = await self.db.get_conversation_state()
        self.assertNotIn(state['current_chat_id'], {parent, child})
        self.assertIsNone(state['telegram_conversation_id'])
        conn=await self.db._get_conn()
        self.assertEqual('ready',(await one(conn,'SELECT state FROM message_queue_controls WHERE conversation_id=?',(parent,)))['state'])
        self.assertEqual('stopped',(await one(conn,'SELECT reason FROM message_queue_controls WHERE conversation_id=?',(stopped,)))['reason'])
        first=archive_origin(await self.db.get_session(parent))
        await self.db.migrate_conversations()
        self.assertEqual(first,archive_origin(await self.db.get_session(parent)))
