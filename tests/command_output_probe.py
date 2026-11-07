"""Real pipeline with repeated commands and large saved output; no extra execution."""
from pathlib import Path
from unittest.mock import patch
from tests.native_tool_probe import NativeHarness,call
from xgent_app.command_output import load_command_output,project_web_frame
from xgent_app.web_history import build_history_message
from xgent_app.presentation import metadata_dict

async def exercise(bot,root,mode='toolcall'):
    async with NativeHarness(bot,root,'openai','nonstream') as h:
        await bot.UserDataManager.save_config('agent_call_mode',mode)
        cmd="printf 'duplicate command'\n"+('\n'.join('# 长命令 '+str(i) for i in range(120)))+'\n';executions=[]
        async def run(command,stop_event=None):
            executions.append(command);body=('OUTPUT_'+str(len(executions))+'_ONLY\n')+('原文😀 '*18000)
            path=Path(bot.ArtifactManager.ROOT_DIR)/'command_outputs'/('result'+str(len(executions))+'.txt');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body.encode())
            return {'success':True,'return_code':0,'output':body,'output_path':str(path)}
        if mode=='toolcall':h.responses=[([call(cid='first',command=cmd),call(cid='second',command=cmd)],'执行两个命令。'),([], '已经完成。')]
        else:h.responses=[([], '执行两个命令。\n'+''.join('```run-x\n<<BEGIN_'+nonce+'\n'+cmd+'<<END_'+nonce+'\n```\n' for nonce in ('firstnonce','secondnonce'))),([], '已经完成。')]
        with patch.object(bot.AgentExecutor,'run_command',run):await h.turn('执行')
        assert len(executions)==2
        assert len(h.requests)==2
        frames=h.drain_frames();serialized=__import__('json').dumps(frames,ensure_ascii=False)
        assert 'OUTPUT_1_ONLY' not in serialized and 'OUTPUT_2_ONLY' not in serialized
        assert not any('原文😀' in str(frame) for frame in frames)
        rows=await h.db.get_display_history(100)
        replies=[r for r in rows if r['msg_type']=='ai_reply'];parent=replies[0]
        result_rows=[r for r in rows if r['msg_type']=='agent_result' and (metadata_dict(r['metadata']).get('presentation',{}).get('operation') or {}).get('kind')=='run']
        assert len(result_rows)==2
        history=[project_web_frame(build_history_message(r,bot.ArtifactManager.ROOT_DIR,root)) for r in rows]
        assert 'OUTPUT_1_ONLY' not in str(history) and '原文😀' not in str(history)
        links=[item['command_result'] for item in history if item.get('command_result')]
        assert len(set(link['key'] for link in links))==2 and all(link['reply_record_id']==parent['id'] for link in links)
        for i,row in enumerate(result_rows):
            first=await load_command_output(h.db,row['session_id'],row['id'],0,bot.ArtifactManager.ROOT_DIR)
            assert first['text'].startswith('OUTPUT_'+str(i+1)+'_ONLY') and not first['eof'] and len(first['text'].encode())<=65536
            tail=await load_command_output(h.db,row['session_id'],row['id'],first['next_offset'],bot.ArtifactManager.ROOT_DIR)
            assert tail['text'] and len(executions)==2
        return {'frames':frames,'history':history,'parent':parent['id'],'outputs':[r['id'] for r in result_rows],
                'executions':len(executions),'no_preload':True,'two_unique_links':True}
