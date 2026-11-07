"""Actual pipeline with one mock model reply carrying an ordinary page fence."""
from pathlib import Path
from unittest.mock import patch

from tests.native_tool_probe import NativeHarness
from tests.telegram_rich_probe import RichCapture
from xgent_app.web_bridge import MirrorBot
from xgent_app.conversations import bind_conversation
from xgent_app.interaction import interaction
from xgent_app.presentation import metadata_dict
from xgent_app.web_history import build_history_message


async def exercise(bot,root,provider,style,long_source=False,agent_mode=True,mode='toolcall',capture=False):
    async with NativeHarness(bot,root,provider,style) as h:
        native=RichCapture();bridge=MirrorBot(h.outbox,1,native);h.context.bot=bridge
        files=[]
        async def document(chat_id,document,filename=None,caption=None,**kwargs):
            files.append(document.read() if hasattr(document,'read') else document.input_file_content)
            message=native.message(caption or '',chat_id);native.save(message.message_id,caption or '',reply_markup=kwargs.get('reply_markup'));return message
        native.send_document=document
        source='<html><button onclick="this.textContent=\'已点击\'">试一下</button></html>\n'
        if long_source:source+='<!--'+('完整源码😀 '*900)+'-->\n'
        raw='这里是页面。\n```xgent-html 演示标题\n'+source+'```\n你可以点击按钮。'
        h.responses=[([],raw)]
        if mode=='fence':h.replies=[raw]
        bot.UserDataManager.set('agent_mode',agent_mode);bot.UserDataManager.set('agent_call_mode',mode)
        bot.UserDataManager.set('web_enabled',True);bot.UserDataManager.set('_web_has_password',True);bot.UserDataManager.set('web_public_url','https://xgent.example/')
        with interaction('web'),patch.object(bot,'_web_real_bot',native),patch.object(bot,'get_web_outbox',return_value=h.outbox):
            with bind_conversation(await bot.get_conversations().resolve()):
                await h.turn('给我看页面')
                assert await bridge.flush_telegram(5)
        assert len(h.requests)==1,h.requests
        assert not h.executed
        rows=await h.db.get_display_history(100)
        replies=[row for row in rows if row['msg_type']=='ai_reply'];assert len(replies)==1
        reply=replies[0];meta=metadata_dict(reply['metadata']);pages=meta['rendered_pages']
        assert len(pages)==1 and Path(pages[0]['source_path']).read_text(encoding='utf-8')==source
        from xgent_app.visual_pages import read_visual
        assert (await read_visual(h.db,reply['session_id'],reply['id'],bot.ArtifactManager.ROOT_DIR))['source']==source
        assert reply['content']==raw
        assert not meta.get('native_calls')
        assert not any(row['msg_type'] in {'agent_result','agent_status','agent_cmd'} for row in rows),rows
        history=build_history_message(reply,bot.ArtifactManager.ROOT_DIR,root)
        assert len(history['visual_pages'])==1 and not history['media']
        assert any(segment.get('visual_index')==0 for segment in history['web_display']['segments'])
        texts=[message['text'] for message in native.messages.values()]
        assert any('blockquote' in text and ('试一下' in text or '源码节选' in text) for text in texts),texts
        assert not any('Agent 第' in text or '[render结果]' in text or 'tg://photo' in text for text in texts)
        frames=h.drain_frames()
        leaked=[frame['type'] for frame in frames if frame['type'] in {'document','edit_markup'} and ('完整源码' in str(frame.get('caption')) or 'visual=' in str(frame.get('reply_markup')))]
        assert not leaked,leaked
        assert len(files)==(1 if long_source else 0)
        if files:assert files[0].decode('utf-8')==source
        buttons=[button for message in native.messages.values() for row in (message['reply_markup'].to_dict() if message.get('reply_markup') else {}).get('inline_keyboard',[]) for button in row]
        assert any('visual='+str(reply['id']) in (button.get('web_app') or {}).get('url','') for button in buttons),native.messages
        await bridge._tg_channel().aclose()
        if capture:return {'frames':frames,'history':history,'source':source,'raw':raw}
        return {'one_request':True,'no_operations':True,'original_reply':True,'folded_source':True,'webapp':True,'full_source':True}


async def progressive(bot,root):
    import asyncio
    async with NativeHarness(bot,root,'openai','foreground') as h:
        native=RichCapture();bridge=MirrorBot(h.outbox,1,native);h.context.bot=bridge
        bot.UserDataManager.set('agent_mode',False)
        bot.UserDataManager.set('agent_call_mode','fence')
        svg='```xgent-svg 第一幅\n<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="20"'
        pieces=[svg,' fill="red"/></svg>\n```\n```xgent-html 第二幅\n<h1>第一行</h1>', '\n<p>第二行</p>', '\n```']
        calls=[]
        async def stream(*args,**kwargs):
            calls.append(1)
            for text in pieces:
                yield text
                await asyncio.sleep(.5)
        with interaction('web'),patch.object(bot,'_web_real_bot',native),patch.object(bot,'get_web_outbox',return_value=h.outbox),patch.object(bot.ModelClient,'think_and_reply_stream',stream):
            with bind_conversation(await bot.get_conversations().resolve()):await h.turn('逐步画出来')
        frames=h.drain_frames()
        pages=[[s for s in (f.get('web_display') or {}).get('segments',[]) if 'visual_index' in s] for f in frames]
        assert any(len(p)==1 and p[0]['visual_pending'] and 'r="20"' in p[0]['visual_source'] for p in pages)
        assert any(len(p)==2 and not p[0]['visual_pending'] and p[1]['visual_pending'] for p in pages)
        assert any(len(p)==2 and p[1]['visual_pending'] and '<p>第二行</p>' in p[1]['visual_source'] for p in pages)
        rows=await h.db.get_display_history(100);reply=next(r for r in rows if r['msg_type']=='ai_reply')
        assert reply['content']==''.join(pieces) and len(metadata_dict(reply['metadata'])['rendered_pages'])==2
        assert len(calls)==1 and not h.executed
        await bridge._tg_channel().aclose()
        return {'progressive_svg':True,'independent_complete':True,'progressive_html':True,'one_request':True}
