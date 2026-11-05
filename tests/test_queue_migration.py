"""Existing version-10 databases receive queue columns without losing pending input."""
import json
import unittest
from dataclasses import replace

from tests import test_conversations as support
from xgent_app.conversations import bind_conversation, SCHEMA_VERSION


class QueueUpgradeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=support.ConversationTests.asyncSetUp
    asyncTearDown=support.ConversationTests.asyncTearDown

    async def test_upgrade_old_queue_preserves_waiting_input_and_accepts_new_text_and_files(self):
        scope=replace(await self.manager.resolve(),origin='web',purpose='chat')
        first=await self.db.queue_enqueue(scope=scope,instance='a'*32,request_key='upgrade-before',text='旧待发消息',chat_id=1)
        async with self.db._transaction() as conn:
            await conn.execute('ALTER TABLE message_queue DROP COLUMN metadata')
            await conn.execute("UPDATE config SET value='10' WHERE key='conversation_schema_version'")
        await self.db.migrate_conversations()
        self.assertEqual(SCHEMA_VERSION,await self.db.get_config_fresh('conversation_schema_version'))
        saved=await self.db.queue_item(first['id'])
        self.assertEqual('旧待发消息',saved['text'])
        self.assertEqual('pending',saved['status'])
        self.assertEqual({},json.loads(saved['metadata']))
        text=await self.db.queue_enqueue(scope=scope,instance='a'*32,request_key='upgrade-text',text='升级后可以发送',chat_id=1)
        files=await self.db.queue_enqueue(scope=scope,instance='a'*32,request_key='upgrade-files',text='有附件',chat_id=1,
            metadata={'queue_file_message':True,'attachments':[{'name':'fixture.txt','path':'fixture.txt'}]})
        self.assertGreater(text['seq'],saved['seq'])
        self.assertGreater(files['seq'],text['seq'])
        self.assertEqual('fixture.txt',json.loads(files['metadata'])['attachments'][0]['name'])
        await self.db.migrate_conversations()
        self.assertEqual([saved['id'],text['id'],files['id']],[item['id'] for item in (await self.db.queue_snapshot(scope.conversation_id))['items']])

    async def test_current_schema_with_missing_queue_column_is_repaired_idempotently(self):
        scope=replace(await self.manager.resolve(),origin='web',purpose='chat')
        async with self.db._transaction() as conn:
            await conn.execute('ALTER TABLE message_queue DROP COLUMN metadata')
        await self.db.migrate_conversations()
        result=await self.db.queue_enqueue(scope=scope,instance='a'*32,request_key='repair-current',text='当前版本也能自动修复',chat_id=1)
        self.assertEqual({},json.loads(result['metadata']))
