"""Explicit tab targets retain generation and callback ownership checks."""
import unittest

from tests.test_external_sync import SectionsProbeMixin


class WebTabScopeTests(SectionsProbeMixin, unittest.TestCase):
    def test_creation_returns_its_own_id_when_another_tab_changes_default(self):
        result = self.run_probe(self.SECTIONS_PREAMBLE + r'''
import asyncio
from xgent_app.workbench import Workbench
async def main():
    await ns['UserDataManager'].init()
    manager=ns['get_conversations']();db=await ns['BotMemoryDB'].get_instance()
    w=Workbench(ns);read=w.conversations
    async def another_tab(data):
        await manager.manage('switch','global_memory')
        return await read(data)
    w.conversations=another_tab
    created=await w.handle('POST','conversations/create',{'name':'CREATED_BY_THIS_TAB'})
    row=await db.get_session(created['conversation_id'])
    print(json.dumps({'id':created['conversation_id'],'default':created['current_chat_id'],'name':row['name']}))
    await manager.close();await db.close()
asyncio.run(main())
''')
        self.assertNotEqual(result['default'], result['id'])
        self.assertEqual('CREATED_BY_THIS_TAB', result['name'])

    def test_explicit_targets_work_without_changing_default_or_accepting_stale_input(self):
        result = self.run_probe(self.SECTIONS_PREAMBLE + r'''
import asyncio
from xgent_app.conversations import current_scope, bind_conversation, ConversationError
async def main():
    await ns['UserDataManager'].init()
    manager=ns['get_conversations']();db=await ns['BotMemoryDB'].get_instance()
    a='global_memory';b=(await manager.manage('create',name='TAB B'))['conversation_id']
    outbox=ns['WebOutbox']();accepted=[]
    async def accept(text,**kwargs):
        accepted.append(current_scope().conversation_id)
        rid=await ns['GlobalRecorder'].record_user_message(text)
        return {'id':str(rid),'text':text,'conversation_id':current_scope().conversation_id}
    ns['submit_ordinary_text']=accept
    generation=(await manager.resolve(a)).generation
    await ns['_web_accept_text']('ONLY A',conversation_id=a,generation=generation)
    await ns['_web_accept_text']('ONLY B',conversation_id=b,generation=(await manager.resolve(b)).generation)
    rejected=[]
    for cid,version in ((a,generation+1),('missing-conversation',0)):
        try:await ns['_web_accept_text']('MUST NOT SAVE',conversation_id=cid,generation=version)
        except ConversationError:rejected.append(cid)
    async def command():
        await ns['GlobalRecorder'].record_user_message('COMMAND IN A')
    await ns['_web_scoped_call'](command(),a,outbox,execution=True,purpose='chat')
    with bind_conversation(await manager.resolve(a)):
        rows_a=await db.get_global_messages(100)
    with bind_conversation(await manager.resolve(b)):
        rows_b=await db.get_global_messages(100)
    print(json.dumps({'accepted':accepted,'rejected':len(rejected),'a':str(rows_a),'b':str(rows_b),
        'default':(await manager.state())['current_chat_id']}))
    await manager.close();await db.close()
asyncio.run(main())
''')
        self.assertEqual('global_memory', result['accepted'][0])
        self.assertEqual(result['default'], result['accepted'][1])
        self.assertEqual(2, result['rejected'])
        self.assertIn('ONLY A', result['a'])
        self.assertIn('COMMAND IN A', result['a'])
        self.assertNotIn('ONLY B', result['a'])
        self.assertNotIn('ONLY A', result['b'])
        self.assertNotIn('MUST NOT SAVE', result['a'] + result['b'])
