"""Mode-specific native controls stay transient and keep the existing Stop target."""
import asyncio
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
from telegram.error import BadRequest

from tests.telegram_rich_probe import RichCapture
from tests.test_telegram_native import operation
from tests.test_thinking_params import run_in_app
from xgent_app.stop_targets import begin_phase, end_phase
from xgent_app.telegram_native import OP_NATIVE_CONTROL, OP_NATIVE_DRAFT, OP_NATIVE_RENDER
from xgent_app.web_bridge import deliver_op_to_bot


@pytest.mark.parametrize('mode,label', [('foreground', '前台流式'), ('background', '后台流式'),
                                       ('nonstream', '非流式')])
def test_waiting_progress_and_final_share_one_control_without_leaking_deferred_body(mode,label):
    async def exercise():
        native=RichCapture();ref=begin_phase('run','model')
        waiting=operation(OP_NATIVE_CONTROL,ref,durable=False)
        waiting.payload['telegram_native'].update(mode=mode,raw='')
        await deliver_op_to_bot(native,waiting,None)
        control_id=next(iter(native.messages))
        initial=label+'输出中… '+('等待完整回复' if mode=='nonstream' else '等待首段内容')
        assert native.messages[control_id]['text']==initial
        controls=native.messages[control_id]['reply_markup'].to_dict()
        raw='只有前台草稿可见的正文'
        progress=operation(OP_NATIVE_DRAFT if mode=='foreground' else OP_NATIVE_CONTROL,ref,durable=False)
        progress.payload['text']='WEB_PREVIEW_ONLY'
        progress.payload['telegram_native'].update(mode=mode,raw=raw,html=['<p>'+raw+'</p>'])
        with patch('xgent_app.telegram_native.asyncio.sleep',new=AsyncMock()):
            await deliver_op_to_bot(native,progress,None)
            assert set(native.messages)=={control_id}
            expected=initial if mode=='nonstream' else label+'输出中… 已生成 '+str(len(raw))+' 字'
            assert native.messages[control_id]['text']==expected
            assert raw not in native.messages[control_id]['text']
            assert 'WEB_PREVIEW_ONLY' not in native.messages[control_id]['text']
            assert native.messages[control_id]['reply_markup'].to_dict()==controls
            edits=sum(method=='editMessageText' for method,_ in native.api_calls)
            await deliver_op_to_bot(native,progress,None)
            assert sum(method=='editMessageText' for method,_ in native.api_calls)==edits
        end_phase('run',ref)
        calls=len(native.api_calls)
        await deliver_op_to_bot(native,waiting,None)
        assert len(native.api_calls)==calls
        final=operation(OP_NATIVE_RENDER,ref,html=['<p>'+raw+'</p>'])
        final.payload['telegram_native'].update(mode=mode,raw=raw,control_markup=None)
        mid=await deliver_op_to_bot(native,final,None)
        assert set(native.messages)=={mid} and control_id not in native.messages
        assert native.messages[mid]['text']=='<p>'+raw+'</p>'
        assert native.messages[mid]['reply_markup'] is None
    asyncio.run(exercise())


def test_first_foreground_preview_and_unsupported_drafts_keep_mode_and_complete_body():
    async def exercise():
        native=RichCapture();original=native._post;ref=begin_phase('run','model')
        async def older_api(method,data=None,**kwargs):
            if method=='sendRichMessageDraft':raise BadRequest('Method not found')
            return await original(method,data,**kwargs)
        native._post=older_api
        raw='完整预览正文\n'+'x'*3800
        preview=operation(OP_NATIVE_DRAFT,ref,durable=False)
        preview.payload.update(text='<b>'+raw+'</b>',parse_mode='HTML')
        preview.payload['telegram_native'].update(mode='foreground',raw=raw)
        await deliver_op_to_bot(native,preview,None)
        assert len(native.messages)==1
        value=next(iter(native.messages.values()))
        assert value['text']=='前台流式输出中… 已生成 '+str(len(raw))+' 字\n\n<b>'+raw+'</b>'
        assert len(value['text'].encode('utf-16-le'))//2<=4096
        assert value['reply_markup'].inline_keyboard[0][0].text=='❌ 停止回答'
        with patch('xgent_app.telegram_native.asyncio.sleep',new=AsyncMock()):
            calls=len(native.api_calls)
            await deliver_op_to_bot(native,preview,None)
            assert len(native.api_calls)==calls
        end_phase('run',ref)
        await deliver_op_to_bot(native,operation(OP_NATIVE_RENDER,ref,html=['<p>完整最终回复</p>']),None)
        assert len(native.messages)==1
        assert next(iter(native.messages.values()))['text']=='<p>完整最终回复</p>'
    asyncio.run(exercise())


def test_actual_conversation_modes_display_progress_and_preserve_model_history_and_web_frames():
    with tempfile.TemporaryDirectory(prefix='xgent-generation-') as root:
        result=run_in_app('import asyncio\nfrom tests.telegram_generation_probe import generation_modes\n'+
                          f'print(json.dumps(asyncio.run(generation_modes(bot,{root!r}))))')
    assert len(result['cases'])==3
    assert all(case['mode'] and case['history'] and case['controls_clean'] and case['web_unchanged']
               for case in result['cases'])
