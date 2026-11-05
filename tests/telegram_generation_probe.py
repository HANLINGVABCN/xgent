"""Pause the real conversation pipeline at native waiting and progress stages."""
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.attachment_request_probe import Harness
from tests.telegram_rich_probe import RichCapture
from xgent_app.conversations import bind_conversation
from xgent_app.fanout import ChannelWorker
from xgent_app.interaction import interaction
from xgent_app.web_bridge import build_telegram_conversation_objects, deliver_op_to_bot


async def generation_modes(bot,root):
    cases=[]
    for mode,label in [('foreground','前台流式'),('background','后台流式'),('nonstream','非流式')]:
        async with Harness(bot,Path(root)/mode) as h:
            bot.UserDataManager.set('agent_mode',False)
            bot.UserDataManager.set('stream_mode',mode!='nonstream')
            bot.UserDataManager.set('stream_style','background' if mode=='background' else 'foreground')
            bot.UserDataManager.set('web_response_mode','foreground')
            native=RichCapture()
            async def deliver(op,mid):
                return await deliver_op_to_bot(native,op,mid,markup_builder=bot._relay_markup_to_telegram)
            channel=ChannelWorker('generation-status-'+mode,deliver,is_configured=lambda:True)
            requested,first,finish=asyncio.Event(),asyncio.Event(),asyncio.Event()
            requests=[];raw='第一段正文\n';tail='最后一段完整回复'
            def remember(args,kwargs):
                requests.append({'model':args[3],'system':args[4],'history':deepcopy(args[5])})
                kwargs['usage_sink'].append({'input_tokens':10,'output_tokens':5})
                requested.set()
            async def complete(*args,**kwargs):
                remember(args,kwargs);await finish.wait();return raw+tail,None
            async def chunks(*args,**kwargs):
                remember(args,kwargs);await first.wait();yield raw
                await finish.wait();yield tail
            task=None
            try:
                with patch.object(bot.ModelClient,'think_and_reply',complete),patch.object(bot.ModelClient,'think_and_reply_stream',chunks):
                    with interaction('telegram','chat'):
                        scope=await bot.get_conversations().resolve(selector='telegram')
                        with bind_conversation(scope):
                            update=SimpleNamespace(message=native.message('状态验收消息'),callback_query=None,
                                effective_chat=SimpleNamespace(id=31),effective_user=SimpleNamespace(id=1))
                            update,context,_=build_telegram_conversation_objects(update,SimpleNamespace(bot=native),h.outbox,channel)
                            await bot.GlobalRecorder.record_user_message('状态验收消息',chat_id=31)
                            task=asyncio.create_task(bot.process_conversation(update,context,'状态验收消息'))
                            await asyncio.wait_for(requested.wait(),5)
                            assert await channel.wait_idle(5)
                            controls=[(mid,item) for mid,item in native.messages.items() if item['text'].startswith(label+'输出中…')]
                            assert len(controls)==1,native.messages
                            control_id,waiting=controls[0]
                            assert ('等待完整回复' if mode=='nonstream' else '等待首段内容') in waiting['text']
                            if mode!='nonstream':
                                first.set()
                                async def progress():
                                    while '已生成 '+str(len(raw))+' 字' not in native.messages[control_id]['text']:
                                        await asyncio.sleep(.05)
                                await asyncio.wait_for(progress(),8)
                                assert native.messages[control_id]['text'].startswith(label+'输出中…')
                                assert raw not in native.messages[control_id]['text']
                            finish.set()
                            await asyncio.wait_for(task,12)
                            assert await channel.wait_idle(5)
                            history=await h.db.get_display_history(0)
                            assert [row['content'] for row in history if row['msg_type']=='ai_reply']==[raw+tail]
                            assert len(requests)==1 and requests[0]['history'][-1]['content']=='状态验收消息'
                            assert all(label+'输出中' not in str(request) for request in requests)
                            assert control_id not in native.messages
                            assert not any(item.get('reply_markup') for item in native.messages.values())
                            frames=h.drain_frames()
                            assert not any('等待首段内容' in str(frame.get('text','')) or '等待完整回复' in str(frame.get('text','')) for frame in frames)
                            cases.append({'mode':True,'history':True,'controls_clean':True,'web_unchanged':True})
            finally:
                first.set();finish.set()
                if task is not None and not task.done():
                    await asyncio.gather(task,return_exceptions=True)
                await channel.aclose()
    return {'cases':cases}
