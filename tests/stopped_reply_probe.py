"""Stop normal model generation and compare durable finalization with refresh."""
import asyncio
from unittest.mock import patch
from tests.attachment_request_probe import Harness
from xgent_app.web_history import build_history_message
from xgent_app.presentation import metadata_dict


async def exercise(bot,root,style):
    async with Harness(bot,root) as h:
        await bot._web_write_setting('response_mode',style)
        started=asyncio.Event();calls=[]
        async def complete(*args,**kwargs):
            calls.append(True);started.set();await asyncio.sleep(60);return '不会到达',None
        async def chunks(*args,**kwargs):
            calls.append(True);yield '已生成的回答。\n\n```python\nprint("保留代码")\n```\n'
            started.set();await asyncio.sleep(60)
        with patch.object(bot.ModelClient,'think_and_reply',complete),patch.object(bot.ModelClient,'think_and_reply_stream',chunks):
            task=asyncio.create_task(h.turn('停止验收输入'))
            await asyncio.wait_for(started.wait(),5);await asyncio.sleep(.15)
            running=(await bot.get_conversations().state())['runs']['global_memory']
            await bot.get_conversations().request_stop(running['run_id'],'global_memory')
            await asyncio.wait_for(task,8)
        frames=h.drain_frames();rows=await h.db.get_display_history(100)
        reply=next(row for row in rows if row['msg_type']=='ai_reply')
        meta=metadata_dict(reply['metadata']);live=meta.get('web_live') or {}
        assert live.get('message_ids'), '停止后保存的回复必须关联原流式气泡'
        history=[build_history_message(row,bot.ArtifactManager.ROOT_DIR,root) for row in rows]
        final=[frame for frame in frames if frame.get('type')=='record_snapshot' and frame.get('record_id')==reply['id']][-1]
        saved=next(message for message in history if message['id']==reply['id'])
        assert final['web_display']==saved['web_display']
        assert len(calls)==1
        return {'frames':frames,'history':history,'reply_id':reply['id'],'style':style,'raw':reply['content']}
