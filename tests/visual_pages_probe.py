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
