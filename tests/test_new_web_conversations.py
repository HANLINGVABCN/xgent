"""A blank browser draft is committed with its first message, never before it."""
import asyncio
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from tests import test_conversations as support
from tests.test_thinking_params import run_in_app
from xgent_app.conversations import ConversationError, bind_conversation, current_scope


class NewWebConversationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=support.ConversationTests.asyncSetUp
    asyncTearDown=support.ConversationTests.asyncTearDown
    write=support.ConversationTests.write

    async def submit(self,**fields):
        return await self.db.queue_enqueue_new_web(token='browser-draft-1',group_id='ungrouped',
            instance='a'*32,request_key='web:first-request',text='首次发送的正文',chat_id=1,**fields)

    async def test_first_admission_is_idempotent_and_keeps_original_history_and_bot_selection(self):
        before=await self.db.get_conversation_state()
        with bind_conversation(await self.manager.resolve()):
            await self.write('旧对话内容不能进入新对话')
        a,b=await asyncio.gather(self.submit(),self.submit())
        self.assertEqual(a['id'],b['id'])
        self.assertNotEqual(before['current_chat_id'],a['conversation_id'])
        self.assertEqual(2,len(await self.db.get_all_sessions()))
        self.assertEqual(before['telegram_conversation_id'],(await self.db.get_conversation_state())['telegram_conversation_id'])
        self.assertEqual(a['conversation_id'],await self.db.new_web_target('browser-draft-1'))
        with bind_conversation(await self.manager.resolve(a['conversation_id'])):
            self.assertEqual([],await self.db.get_conversation_messages())
            async with self.manager.operation(execution=True):
                batch=await self.db.queue_claim(current_scope())
                self.assertEqual(['首次发送的正文'],[entry['text'] for entry in batch])
            self.assertNotIn('旧对话内容',str(await self.db.get_conversation_messages()))
        retry=await self.submit()
        self.assertEqual(a['id'],retry['id'])
        self.assertEqual(2,len(await self.db.get_all_sessions()))

    async def test_invalid_empty_or_failed_admission_leaves_no_conversation_or_mapping(self):
        before=deepcopy(await self.db.get_conversation_state())
        for text,group in [('', 'ungrouped'),('正文','missing'),('正文','__archived__')]:
            with self.assertRaises(ConversationError):
                await self.db.queue_enqueue_new_web(token='bad-draft',group_id=group,instance='a'*32,
                    request_key='web:rejected',text=text,chat_id=1)
        with patch.object(self.db,'_queue_enqueue',AsyncMock(side_effect=OSError('fixture disk failure'))):
            with self.assertRaises(OSError):
                await self.submit()
        self.assertEqual(before,await self.db.get_conversation_state())
        self.assertEqual(1,len(await self.db.get_all_sessions()))
        self.assertIsNone(await self.db.new_web_target('browser-draft-1'))
        self.assertIsNone(await self.db.new_web_target('bad-draft'))

    async def test_original_group_and_attachment_generation_are_saved_with_first_queue_item(self):
        state=await self.db.get_conversation_state()
        group=await self.db.organize_conversations('create_group',{'revision':state['revision'],'name':'首次发送的分组'})
        item=await self.db.queue_enqueue_new_web(token='file-draft',group_id=group,instance='a'*32,
            request_key='web-file:first',text='附件说明',chat_id=1,
            metadata={'queue_file_message':True,'attachments':[{'name':'fixture.txt','path':'fixture.txt'}]})
        from xgent_app.queue_store import item_metadata
        self.assertEqual(group,(await self.db.get_session(item['conversation_id']))['group_id'])
        self.assertEqual(item['generation'],item_metadata(item)['attachment_generation'])
        self.assertNotEqual(0,item['generation'])


def test_actual_first_text_and_files_use_the_original_model_construction_and_retry_once():
    with tempfile.TemporaryDirectory(prefix='new-chat-') as root:
        result=run_in_app('import asyncio\nfrom tests.new_web_conversation_probe import first_admission\n'+
            f'print(json.dumps(asyncio.run(first_admission(bot,{root!r}))))')
    assert all(result.values()),result
