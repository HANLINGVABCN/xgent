"""Real Agent and Telegram delivery use one saved page with no rasterizer."""
from pathlib import Path
from unittest.mock import patch

from tests.native_tool_probe import NativeHarness,call
from tests.telegram_rich_probe import RichCapture
from xgent_app.web_bridge import MirrorBot
from xgent_app.conversations import bind_conversation
from xgent_app.interaction import interaction
from xgent_app.presentation import metadata_dict
from xgent_app.visual_pages import read_visual
from xgent_app.web_history import build_history_message


async def exercise(bot,root,long_source):
    async with NativeHarness(bot,root,'vertex','nonstream') as h:
        native=RichCapture();bridge=MirrorBot(h.outbox,1,native);h.context.bot=bridge
        files=[]
        async def send_document(chat_id,document,filename=None,caption=None,**kwargs):
            files.append(document.read() if hasattr(document,'read') else document.input_file_content)
            message=native.message(caption or '',chat_id);native.save(message.message_id,caption or '',reply_markup=kwargs.get('reply_markup'));return message
        native.send_document=send_document
        source='<html><style>body{color:purple}</style><button onclick="this.textContent=\'已点击\'">点一下</button></html>'
        if long_source:source+='\n<!--'+('代码内容😀'*3000)+'-->'
        bot.UserDataManager.set('web_enabled',True);bot.UserDataManager.set('_web_has_password',True);bot.UserDataManager.set('web_public_url','https://xgent.example/')
        h.responses=[([call('render_visual','render-page',format='html',source=source,width=800,height=400,title='交互演示')],''),([], '页面已创建。')]
        with interaction('web'),patch.object(bot,'_web_real_bot',native),patch.object(bot,'get_web_outbox',return_value=h.outbox):
            with bind_conversation(await bot.get_conversations().resolve()):
                await h.turn('做一个可以点击的渲染页面')
                assert await bridge.flush_telegram(5)
        rows=await h.db.get_display_history(100)
        record=next(row for row in rows if metadata_dict(row['metadata']).get('visual_render'))
        visual=metadata_dict(record['metadata'])['visual_render'];assert visual['version']==2
        assert Path(visual['source_path']).read_text(encoding='utf-8')==source
        page=await read_visual(h.db,record['session_id'],record['id'],bot.ArtifactManager.ROOT_DIR)
        assert page['source']==source
        history=build_history_message(record,bot.ArtifactManager.ROOT_DIR,root)
        assert history['visual_page']['version']==2 and not history['media']
        messages=list(native.messages.values());texts=[item['text'] for item in messages]
        assert not any('tg://photo' in text for text in texts)
        folded=[text for text in texts if '<blockquote' in text and ('点一下' in text or '代码内容' in text)]
        assert len(folded)==1,texts
        assert ('源码节选' in folded[0])==long_source
        buttons=[button for message in messages for row in (message['reply_markup'].to_dict() if message.get('reply_markup') else {}).get('inline_keyboard',[]) for button in row]
        assert any('visual='+str(record['id']) in (button.get('web_app') or {}).get('url','') for button in buttons),messages
        assert len(files)==(1 if long_source else 0)
        if files:assert files[0].decode('utf-8')==source
        assert not any(frame.get('media') or frame.get('type')=='photo' for frame in h.drain_frames())
        assert '[render结果]' in str(h.requests[-1]) and '图片：' not in str(h.requests[-1])
        await bridge._tg_channel().aclose()
        return {'saved_once':True,'folded':True,'webapp':True,'full_source':True,'no_images':True}


async def http_read(bot,root):
    import asyncio,json,http.client
    from xgent_app.workbench import Workbench
    from xgent_app.web_server import WebChatConfig,WebChatServer
    from xgent_app.web_auth import hash_password
    from xgent_app.message_policy import stamp_record_metadata
    import hashlib
    async with NativeHarness(bot,root,'openai','nonstream') as h:
        source='<html><button>实际页面</button></html>'
        saved=bot.ArtifactManager.save_generated_media('page.html',source.encode(),'text/html')
        metadata=stamp_record_metadata('agent_result','system',{'visual_render':{'version':2,'format':'html','source_path':saved['abs_path'],
              'sha256':hashlib.sha256(source.encode()).hexdigest(),'width':800,'height':600,'title':'网页'}})
        row=await bot.GlobalRecorder.record('agent_result','system','创建页面',chat_id=1,metadata=metadata)
        cid=(await h.db.get_conversation_state())['current_chat_id']
        w=Workbench(vars(bot));config=WebChatConfig(host='127.0.0.1',port=0,password_hash=hash_password('test-only-password'),bot_token='',authorized_user_id=1,
            loop=asyncio.get_running_loop(),submit_message=lambda *a:None,read_history=bot._web_read_history,read_settings=bot._web_read_settings,
            write_setting=bot._web_write_setting,request_stop=bot._web_request_stop,is_busy=lambda:False,
            read_conversations=bot.get_conversations().state,workbench=w.handle)
        server=WebChatServer(config);server.start();port=server._httpd.server_address[1]
        def request(path,cookie='',login=False):
            conn=http.client.HTTPConnection('127.0.0.1',port)
            try:
                conn.request('POST' if login else 'GET',path,json.dumps({'password':'test-only-password'}) if login else None,
                    headers={'Content-Type':'application/json','Cookie':cookie})
                result=conn.getresponse();return result.status,dict(result.getheaders()),result.read()
            finally:conn.close()
        path=f'/api/workbench/visual?record_id={row}&conversation_id={cid}'
        try:
            assert (await asyncio.to_thread(request,path))[0]==401
            _,headers,_=await asyncio.to_thread(request,'/api/login',login=True);cookie=headers['Set-Cookie'].split(';')[0]
            code,headers,body=await asyncio.to_thread(request,path,cookie);assert code==200 and json.loads(body)['source']==source
            code,headers,body=await asyncio.to_thread(request,path.replace('/visual?','/visual/source?'),cookie)
            assert code==200 and body.decode()==source and 'attachment' in headers['Content-Disposition']
            assert (await asyncio.to_thread(request,path.replace(cid,'missing'),cookie))[0]!=200
            conn=await h.db._get_conn();await conn.execute('UPDATE global_messages SET withdrawn=1 WHERE id=?',(row,))
            assert (await asyncio.to_thread(request,path,cookie))[0]==404
        finally:await asyncio.to_thread(server.stop)
        return {'auth':True,'source':True,'download':True,'withdrawn':True}
