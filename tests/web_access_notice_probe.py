from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from tests.native_tool_probe import NativeHarness
from tests.telegram_rich_probe import RichCapture
from xgent_app.presentation import metadata_dict
from xgent_app.web_access import WebAccess
from xgent_app.web_history import build_history_message

async def exercise(bot,root):
    async with NativeHarness(bot,root,'openai','nonstream') as h:
        native=RichCapture();incident={'id':'a'*32,'ip':'198.51.100.77','device':'b'*32,'agent':'模拟安全测试浏览器',
                                    'failures':8,'created_at':1700000000,'resolved':0}
        access=WebAccess(lambda:bot.BotMemoryDB.get_instance());await access.initialize()
        async with h.db._transaction() as conn:
            await conn.execute('INSERT INTO web_access_incidents VALUES(?,?,?,?,?,?,?)',tuple(incident.values()))
        with patch.object(bot,'_web_real_bot',native),patch.object(bot,'get_web_outbox',return_value=h.outbox):
            await bot.notify_web_access_incident(incident)
        records=await h.db.get_display_history(100)
        notes=[r for r in records if metadata_dict(r['metadata']).get('security_notice',{}).get('origin')=='web']
        assert len(notes)==1
        note=notes[0];assert metadata_dict(note['metadata'])['message_policy']['model_context']
        history=build_history_message(note,bot.ArtifactManager.ROOT_DIR,root)
        assert history['reply_markup'][0][0]['callback_data']=='webban:'+incident['id']
        frames=h.drain_frames();assert any(f['type']=='access_notice' for f in frames)
        assert not any(f.get('ui_message_id') for f in frames)
        answers=[]
        async def answer(text,**kwargs):answers.append(text)
        query=SimpleNamespace(data='webban:'+incident['id'],answer=answer,message=SimpleNamespace(edit_reply_markup=AsyncMock()))
        update=SimpleNamespace(callback_query=query,message=None,effective_chat=SimpleNamespace(id=1),effective_user=SimpleNamespace(id=1))
        with patch.object(bot,'_web_access_control',access,create=True),patch.object(bot,'check_authorized_user_middleware',AsyncMock(return_value=True)):
            await bot.handle_button_click(update,h.context)
        assert answers and '已解除' in answers[0]
        saved=await h.db.get_display_message(note['id'])
        assert metadata_dict(saved['metadata'])['security_notice']['resolved']
        assert not build_history_message(saved,bot.ArtifactManager.ROOT_DIR,root).get('reply_markup')
        assert not h.requests
        return {'notice_context':True,'one_card':True,'web_notice':True,'unblock_callback':True,'no_model_call':True}
