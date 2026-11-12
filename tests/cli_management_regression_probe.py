"""Actual CLI command/callback routing with an isolated instance and no updater execution."""
import asyncio
import json
import time
from unittest.mock import patch


async def exercise(cli, scenario):
    from xgent_app.cli_bridge import active_menu_message_id, get_last_menu_options, reset_menu_state, set_screen
    from xgent_app.cli_render import Palette
    from xgent_app.cli_tui import PtScreen
    from xgent_app.conversations import bind_conversation
    from xgent_app.interaction import interaction
    from xgent_app.terminal_workspace import TerminalWorkspace

    manager=cli.get_conversations()
    await cli.UserDataManager.init();await manager.enable_terminal(start_new=scenario=='home')
    scope=None if scenario=='home' else await manager.resolve(selector='terminal')
    screen=PtScreen(Palette(False),width=88)
    cli.SCREEN=screen;set_screen(screen)
    work=TerminalWorkspace(manager,screen,cli._history_row_lines,cli._ns)
    cli._terminal_workspace=work
    reset_menu_state()
    with interaction('cli','management'),bind_conversation(scope):
        await work.start()
        try:
            if scenario=='home':
                from unittest.mock import AsyncMock
                db=await cli.BotMemoryDB.get_instance()
                before=await db.get_conversation_state()
                count=len(await db.get_all_sessions())
                assert work.selected is None
                await cli._dispatch_submitted('/start')
                assert work.selected is None and get_last_menu_options()
                await cli._dispatch_submitted('/update')
                await cli._dispatch_submitted('1')
                assert cli.UserDataManager.get('temp_update_card')['phase']=='confirm'
                assert len(await db.get_all_sessions())==count
                queue=cli._ns['get_text_queue']()
                with patch.object(queue,'poll',AsyncMock()):
                    await cli._dispatch_submitted('新对话第一条正文')
                    cid=work.selected
                    assert cid and cid!=before['current_chat_id']
                    assert len(await db.get_all_sessions())==count+1
                    item=(await db.queue_snapshot(cid))['items'][0]
                    assert item['text']=='新对话第一条正文' and item['origin']=='cli'
                    assert (await db.get_conversation_state())['current_chat_id']==before['current_chat_id']
                    await cli._dispatch_submitted('/new 测试新对话')
                    assert work.selected is None
                    assert len(await db.get_all_sessions())==count+1
                    await cli._dispatch_submitted('第二个新对话正文')
                    assert work.selected!=cid
                    assert (await db.get_session(work.selected))['name']=='测试新对话'
                    assert len(await db.get_all_sessions())==count+2
            elif scenario=='mode_sync':
                await cli.UserDataManager.save_config('response_mode','nonstream')
                await cli._dispatch_submitted('/stream')
                assert cli.UserDataManager.get('stream_mode') is True
                assert cli.UserDataManager.get('web_response_mode')=='foreground'
                assert cli.UserDataManager.get('stream_style')=='background'
                await cli._dispatch_submitted('/start')
                options=get_last_menu_options()
                resolved=[cli._ns['CallbackDataStore']._store.get(value,value) for value in options]
                resolved=[value.split(':',2)[2] if value.startswith('cv:') else value for value in resolved]
                await cli._dispatch_submitted(str(resolved.index('toggle_stream_mode')+1))
                assert cli.UserDataManager.get('stream_mode') is False
                assert cli.UserDataManager.get('web_response_mode')=='nonstream'
            elif scenario=='native':
                from xgent_app.presentation import message_presentation
                from xgent_app.web_display import web_display_scope
                calls=[{'id':'call-one','name':'exec_command','arguments':{'command':'ls -la memory/'}},
                       {'id':'call-two','name':'read_file','arguments':{'path':'memory/新记忆.txt'}}]
                context=cli.build_cli_conversation_objects(cli.BotConfig.AUTHORIZED_USER_ID)[1]
                with message_presentation({'kind':'ai_reply','native_calls':calls,'telegram_content':{'raw':'','complete':True}}), web_display_scope({'version':1,'segments':[]}):
                    await context.bot.send_message(chat_id=cli.BotConfig.AUTHORIZED_USER_ID,text=' ')
                visible='\n'.join(line for line,_ in screen.model.render_rows())
                assert '执行命令' in visible and '读取文件' in visible,visible
                row_id=await cli.GlobalRecorder.record_ai_reply('',cli.BotConfig.AUTHORIZED_USER_ID,
                    metadata={'native_calls':calls,'agent_call_mode':'toolcall'},provider='fixture',model='fixture')
                db=await cli.BotMemoryDB.get_instance()
                replay=cli._history_row_lines(await db.get_display_message(row_id))
                assert '执行命令' in '\n'.join(replay) and '读取文件' in '\n'.join(replay),replay
                assert 'ls -la memory/' in '\n'.join(replay) and 'memory/新记忆.txt' in '\n'.join(replay)
            elif scenario=='update':
                for source in ('normal','test'):
                    await cli._dispatch_submitted('/update')
                    original=active_menu_message_id()
                    options=get_last_menu_options()
                    assert len(options)>=2 and original is not None
                    selected=options[0 if source=='normal' else 1]
                    # This is the user's numeric input path; never apply an update.
                    with patch.object(cli.BotConfig,'UPDATE_GITHUB_TOKEN','fixture-read-token'):
                        await cli._dispatch_submitted('1' if source=='normal' else '2')
                    visible='\n'.join(line for line,_ in screen.model.render_rows())
                    assert '更新卡片已失效' not in visible,visible
                    assert active_menu_message_id()==original,(original,active_menu_message_id(),visible)
                    assert '更新确认' in visible,visible
                    assert len([msg for msg in screen.model.messages if any('选择更新来源' in line for block in msg.blocks for line in block.lines)])==0,visible
                    assert cli.UserDataManager.get('temp_update_card')['phase']=='confirm'
            elif scenario=='token':
                await cli._dispatch_submitted('/update')
                original=active_menu_message_id()
                with patch.object(cli.BotConfig,'UPDATE_GITHUB_TOKEN',''):
                    await cli._dispatch_submitted('2')
                    assert cli.UserDataManager.get('temp_update_card')['phase']=='token'
                    persisted=[]
                    with patch.dict(cli._ns,{
                        'persist_update_github_token':lambda token,url:persisted.append((token,url)),
                        'verify_update_github_token':lambda token,url:{'ok':True},
                    }):
                        await cli._dispatch_submitted('fixture-read-token')
                    assert len(persisted)==1
                assert cli.UserDataManager.get('temp_update_card')['phase']=='confirm', (cli.UserDataManager.get('temp_update_card'), '\n'.join(line for line,_ in screen.model.render_rows()))
                assert active_menu_message_id()==original
                assert '卡片已失效' not in '\n'.join(line for line,_ in screen.model.render_rows())
            elif scenario=='navigation':
                await (await cli.BotMemoryDB.get_instance()).save_provider('fixture','http://localhost/v1','fixture-key',['fixture-model'],api_format='openai')
                await cli.UserDataManager.reload_providers()
                async def pick(action):
                    options=get_last_menu_options()
                    resolved=[cli._ns['CallbackDataStore']._store.get(value,value) for value in options]
                    resolved=[value.split(':',2)[2] if value.startswith('cv:') else value for value in resolved]
                    assert action in resolved,(action,resolved)
                    await cli._dispatch_submitted(str(resolved.index(action)+1))
                await cli._dispatch_submitted('/providers')
                original=active_menu_message_id()
                await pick('view_prov_fixture')
                await pick('prov_models_fixture')
                assert active_menu_message_id()==original
                await cli._dispatch_submitted('/models')
                await pick('target_chat_models')
                await pick('pick_model_provider_chat_fixture')
                await cli._dispatch_submitted('/prompts')
                await pick('view_prompt:assistant_prompt')
                await pick('menu_prompts')
                await pick('act_main_menu')
                assert get_last_menu_options()
                visible='\n'.join(line for line,_ in screen.model.render_rows())
                assert '卡片已失效' not in visible and '操作失败' not in visible,visible
            elif scenario=='ordering':
                await cli._dispatch_submitted('/start')
                menu=active_menu_message_id()
                assert menu is not None
                async with cli.conversation_operation(scope.conversation_id,execution=True):
                    cli._print_user_block('用户刚发的新消息')
                    await cli.GlobalRecorder.record_user_message('用户刚发的新消息',cli.MessageType.USER_TEXT,cli.BotConfig.AUTHORIZED_USER_ID)
                    context=cli.build_cli_conversation_objects(cli.BotConfig.AUTHORIZED_USER_ID)[1]
                    await context.bot.send_message(chat_id=cli.BotConfig.AUTHORIZED_USER_ID,text='随后真实回复')
                    await cli.GlobalRecorder.record_ai_reply('随后真实回复',cli.BotConfig.AUTHORIZED_USER_ID,provider='fixture',model='fixture')
                await work.refresh_history(force=True)
                keys=[msg.key for msg in screen.model.messages]
                texts=['\n'.join(line for block in msg.blocks for line in block.lines) for msg in screen.model.messages]
                user=next(i for i,t in enumerate(texts) if '用户刚发的新消息' in t)
                reply=next(i for i,t in enumerate(texts) if '随后真实回复' in t)
                assert keys.index(menu)<user<reply,(keys,texts)
                assert get_last_menu_options()
                await work.refresh_history(force=True)
                assert [msg.key for msg in screen.model.messages]==keys
        finally:
            await work.close();await manager.close();await (await cli.BotMemoryDB.get_instance()).close()
            cli._terminal_workspace=None;reset_menu_state();set_screen(None)
    return {'scenario':scenario,'passed':True}
