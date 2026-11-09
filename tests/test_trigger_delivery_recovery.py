import unittest

from tests.test_external_sync import ProbeMixin


class TriggerDeliveryRecoveryTests(ProbeMixin, unittest.TestCase):
    def test_failure_stop_restart_and_busy_wait_do_not_lose_or_reexecute_result(self):
        result = self.run_probe(r'''
import asyncio, json, tempfile, time
from unittest.mock import patch
import xgent_server as bot
from tests.native_tool_probe import NativeHarness
from xgent_app.presentation import metadata_dict
from xgent_app.conversations import conversation_operation

async def seed(h, suffix):
    task={'id':'trg_'+suffix,'chat_id':1,'conversation_id':'global_memory',
        'command':'NEVER_REPEAT_BACKGROUND_COMMAND','summary':'后台结果',
        'origin_user_text':'ORIGINAL','schedule_type':'once','timezone':'Asia/Shanghai',
        'status':'completed','created_at':time.time(),'updated_at':time.time()}
    await h.db.create_trigger_task(task)
    run,_=await h.db.create_trigger_run(task['id'],time.time(),'process_exit')
    await h.db.finish_trigger_run(run['run_id'],finished_at=time.time(),status='completed',
        exit_code=0,output='ORIGINAL_RESULT')
    return run['run_id']

async def main():
    with tempfile.TemporaryDirectory() as folder:
        async with NativeHarness(bot,folder,'openai_compatible','nonstream') as h:
            rid=await seed(h,'retry')
            async def fail(*args, **kwargs):
                bot.get_conversations().runtime().outcome='failed'
            with patch.object(bot,'process_conversation',side_effect=fail):
                await bot.SelfTriggerManager._deliver_run(rid)
            first=await h.db.get_trigger_run(rid)
            assert first['delivered_at'] is None and first['delivery_state']=='retry', first
            assert first['delivery_retry_at']>time.time()
            assert first['delivery_record_id'] is not None
            await h.db.finish_trigger_run(rid,delivery_retry_at=0)
            h.responses=[([], 'RECEIPT')]
            await bot.SelfTriggerManager._deliver_run(rid)
            await bot.SelfTriggerManager._deliver_run(rid)
            final=await h.db.get_trigger_run(rid)
            assert final['delivered_at'] and final['delivery_state']=='delivered'
            rows=await h.db.get_display_history(100)
            receipts=[r for r in rows if metadata_dict(r['metadata']).get('trigger_result',{}).get('run_id')==rid]
            assert len(receipts)==1 and len(h.requests)==1 and not h.executed

            stopped=await seed(h,'stop')
            async def stop(*args,**kwargs):
                bot.get_conversations().runtime().stop.set()
            with patch.object(bot,'process_conversation',side_effect=stop):
                await bot.SelfTriggerManager._deliver_run(stopped)
            saved=await h.db.get_trigger_run(stopped)
            assert saved['delivered_at'] is None and saved['delivery_state']=='paused'
            assert stopped in await bot.SelfTriggerManager.format_active_tasks()

            exhausted=await seed(h,'exhausted')
            await h.db.finish_trigger_run(exhausted,delivery_attempts=3,delivery_conversation_run_id='empty')
            await h.db.defer_trigger_delivery(exhausted,'反复失败')
            assert (await h.db.get_trigger_run(exhausted))['delivery_state']=='paused'

            restart=await seed(h,'restart')
            await h.db.finish_trigger_run(restart,delivery_started_at=1,
                delivery_conversation_run_id='empty_owner',delivery_attempts=1)
            await h.db.finalize_interrupted_trigger_deliveries()
            recovered=await h.db.get_trigger_run(restart)
            assert recovered['delivered_at'] is None and recovered['delivery_state']=='retry'

            progressed=await seed(h,'progress')
            await h.db.finish_trigger_run(progressed,delivery_started_at=1,
                delivery_conversation_run_id='progress_owner',delivery_attempts=1)
            await h.db.record_global_message(chat_id=1,user_id=0,msg_type='agent_result',role='system',
                content='EXECUTED_TOOL',session_id='global_memory',metadata={'run_id':'progress_owner'})
            await h.db.finalize_interrupted_trigger_deliveries()
            recovered=await h.db.get_trigger_run(progressed)
            assert recovered['delivered_at'] is None and recovered['delivery_state']=='paused'

            busy=await seed(h,'busy')
            started=asyncio.Event();released=asyncio.Event()
            async def hold():
                async with conversation_operation('global_memory',execution=True,fresh=True):
                    started.set();await released.wait()
            owner=asyncio.create_task(hold());await started.wait()
            delivery=asyncio.create_task(bot.SelfTriggerManager._deliver_run(busy))
            await asyncio.sleep(.15)
            assert len(h.requests)==1 and not delivery.done()
            released.set();await owner;await delivery
            assert len(h.requests)==2 and (await h.db.get_trigger_run(busy))['delivered_at']
            assert not h.executed
    print(json.dumps({'retry':True,'stop':True,'restart':True,'no_reexecute':True,'busy_wait':True}))
asyncio.run(main())
''')
        self.assertTrue(all(result.values()))

    def test_receipt_context_is_independent_and_new_input_does_not_stop_it(self):
        result = self.run_probe(r'''
import asyncio,contextvars,json,tempfile,time
from dataclasses import replace
from unittest.mock import patch
import xgent_server as bot
from tests.native_tool_probe import NativeHarness
from xgent_app.conversations import bind_conversation,conversation_operation,current_scope
from xgent_app.interaction import interaction

async def main():
    with tempfile.TemporaryDirectory() as folder:
        async with NativeHarness(bot,folder,'openai_compatible','nonstream') as h:
            manager=bot.get_conversations()
            marker=contextvars.ContextVar('old-turn-private-marker',default='independent')
            marker.set('old-turn')
            base=await manager.resolve('global_memory')
            with bind_conversation(replace(base,run_id='retired-turn')):
                bot.get_or_create_stop_event().set()
            with bind_conversation(replace(base,run_id='another-retired-turn')):
                assert not bot.get_or_create_stop_event().is_set()
                assert not bot.is_stop_requested()
            task={'id':'trg_independent','chat_id':1,'conversation_id':'global_memory',
                'command':'DO_NOT_RUN','summary':'独立回执','origin_user_text':'ORIGINAL',
                'schedule_type':'once','timezone':'Asia/Shanghai','status':'completed',
                'created_at':time.time(),'updated_at':time.time()}
            await h.db.create_trigger_task(task)
            run,_=await h.db.create_trigger_run(task['id'],time.time(),'process_exit')
            await h.db.finish_trigger_run(run['run_id'],finished_at=time.time(),status='completed',exit_code=0,output='RESULT')
            entered=asyncio.Event();release=asyncio.Event();captured={}
            async def answer(*args,**kwargs):
                captured.update(run_id=current_scope().run_id,marker=marker.get(),
                    stopped=bot.is_stop_requested(),purpose=current_scope().purpose)
                entered.set();await release.wait()
                assert not bot.is_stop_requested()
                return '独立回执完成',None
            with patch.object(bot.ModelClient,'think_and_reply',side_effect=answer):
                async with conversation_operation('global_memory',execution=True,fresh=True) as old:
                    manager.runtime().stop.set()
                    bot.SelfTriggerManager._schedule_delivery(run['run_id'],task['id'])
                    await asyncio.sleep(.1)
                    assert not entered.is_set()
                await asyncio.wait_for(entered.wait(),5)
                assert captured['run_id']!=old.run_id and captured['marker']=='independent'
                assert not captured['stopped'] and captured['purpose']=='notification'
                queue=bot.get_text_queue();await queue.start()
                async def dispatch(batch):
                    return None
                queue.dispatch=dispatch
                with interaction('telegram','chat'),bind_conversation(replace(base,origin='telegram')):
                    await queue.submit('普通新消息',chat_id=1,request_key='ordinary-new-message')
                other=(await h.db.manage_conversation('create',name='OTHER',select=False))['conversation_id']
                async with conversation_operation(other,execution=True,fresh=True) as foreign:
                    with interaction('web','notification'):
                        assert await manager.request_stop(foreign.run_id,other,reason='web_stop')
                        assert not await manager.request_stop(old.run_id,'global_memory',reason='stop_button')
                assert not manager.runtime(captured['run_id']).stop.is_set()
                release.set()
                pending=list(bot.SelfTriggerManager._delivery_tasks_by_task.get(task['id'],[]))
                await asyncio.gather(*pending)
                assert (await h.db.get_trigger_run(run['run_id']))['delivered_at']
                assert not h.executed
    print(json.dumps({'independent_context':True,'old_stop_ignored':True,'new_input_accepted':True,'other_stop_ignored':True}))
asyncio.run(main())
''')
        self.assertTrue(all(result.values()))
