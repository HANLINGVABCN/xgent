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

    async def test_select_blank_bot_draft_does_not_create_a_conversation_until_web_send(self):
        before=await self.db.get_conversation_state()
        changed=await self.db.set_bot_new_conversation('browser-draft-1','ungrouped',before['telegram_conversation_id'])
        self.assertTrue(changed)
        self.assertEqual(1,len(await self.db.get_all_sessions()))
        self.assertIsNone(await self.db.new_web_target('browser-draft-1'))
        self.assertIsNone((await self.db.get_conversation_state())['telegram_conversation_id'])
        a,b=await asyncio.gather(self.submit(),self.submit())
        self.assertEqual(a['id'],b['id'])
        state=await self.db.get_conversation_state()
        self.assertEqual(a['conversation_id'],state['telegram_conversation_id'])
        self.assertEqual(a['conversation_id'],state['telegram_new_conversation']['conversation_id'])
        self.assertEqual(2,len(await self.db.get_all_sessions()))
        from xgent_app.interaction import interaction
        with interaction('web', 'chat'):
            self.assertTrue((await self.manager.resolve(a['conversation_id'])).telegram_delivery)

    async def test_bot_first_input_and_web_first_input_share_the_same_draft(self):
        before=await self.db.get_conversation_state()
        await self.db.set_bot_new_conversation('browser-draft-1','ungrouped',before['telegram_conversation_id'])
        cid=await self.db.materialize_bot_new_conversation('browser-draft-1')
        self.assertEqual(cid,await self.db.materialize_bot_new_conversation('browser-draft-1'))
        item=await self.submit()
        self.assertEqual(cid,item['conversation_id'])
        self.assertEqual(2,len(await self.db.get_all_sessions()))

    async def test_old_draft_send_does_not_override_new_bot_selection(self):
        before=await self.db.get_conversation_state()
        await self.db.set_bot_new_conversation('browser-draft-1','ungrouped',before['telegram_conversation_id'])
        with self.assertRaises(ConversationError):
            await self.db.set_bot_new_conversation('other-draft','ungrouped',None)
        await self.db.set_bot_new_conversation('other-draft','ungrouped',None,'browser-draft-1')
        await self.submit()
        state=await self.db.get_conversation_state()
        self.assertIsNone(state['telegram_conversation_id'])
        self.assertEqual('other-draft',state['telegram_new_conversation']['token'])

    async def test_failed_first_send_keeps_selected_draft_and_creates_no_session(self):
        before=await self.db.get_conversation_state()
        await self.db.set_bot_new_conversation('browser-draft-1','ungrouped',before['telegram_conversation_id'])
        selected=await self.db.get_conversation_state()
        with patch.object(self.db,'_queue_enqueue',AsyncMock(side_effect=OSError('fixture disk failure'))):
            with self.assertRaises(OSError):
                await self.submit()
        self.assertEqual(selected,await self.db.get_conversation_state())
        self.assertEqual(1,len(await self.db.get_all_sessions()))

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


def test_native_first_text_and_file_bind_the_selected_blank_draft_before_the_handler():
    result=run_in_app('''
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from xgent_app.conversations import current_scope
async def check():
    await bot.UserDataManager.init()
    db=await bot.BotMemoryDB.get_instance();manager=bot.get_conversations();seen=[]
    async def handler(update,context):seen.append(current_scope().conversation_id)
    wrapped=bot.telegram_entry(handler)
    with patch.dict(bot.telegram_entry.__globals__,{'authorize_before_conversation':AsyncMock(return_value=True)}), patch('xgent_app.web_bridge.install_tg_to_web_mirror',return_value=lambda:None):
        for kind in ('text','file'):
            state=await db.get_conversation_state();token='native-first-'+kind
            await db.set_bot_new_conversation(token,'ungrouped',state['telegram_conversation_id'],(state.get('telegram_new_conversation') or {}).get('token'))
            message=SimpleNamespace(text='原生首条正文' if kind=='text' else None,document=object() if kind=='file' else None)
            update=SimpleNamespace(message=message,effective_message=message,callback_query=None,effective_chat=SimpleNamespace(id=1))
            await wrapped(update,SimpleNamespace(bot=SimpleNamespace()))
            assert seen[-1]==await db.new_web_target(token)
            assert (await db.get_conversation_state())['telegram_conversation_id']==seen[-1]
    assert len(set(seen))==2
    await manager.close();await db.close()
    return {'native_text':True,'native_file':True,'shared_draft_identity':True}
print(json.dumps(asyncio.run(check())))
''')
    assert all(result.values()),result
