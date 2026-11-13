"""Update API uses pinned sources, keeps data and never repeats confirmed requests."""
from tests.test_thinking_params import run_in_app


def test_runtime_version_matches_settings_stamp_after_archive_over_old_git():
    result=run_in_app(r'''
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
with tempfile.TemporaryDirectory() as root:
    stamp=Path(root)/'.xgent-version';stamp.write_text('b'*40)
    with patch.object(bot,'PROJECT_ROOT',root),patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='a'*40)) as git:
        assert bot.runtime_code_version()=='b'*40
        git.assert_not_called()
        stamp.write_bytes(b'\xff')
        assert bot.runtime_code_version()=='a'*10
print(json.dumps({'stamp_matches_settings':True,'invalid_stamp_falls_back':True}))
''')
    assert all(result.values())


def test_settings_update_plan_jobs_token_privacy_duplicate_and_failure():
    result=run_in_app(r'''
import asyncio,io,tempfile
from pathlib import Path
from unittest.mock import patch,AsyncMock
from xgent_app.workbench import Workbench,WorkbenchError
from xgent_app.data_paths import DataPaths
from tests.attachment_request_probe import Harness
async def main():
    with tempfile.TemporaryDirectory() as root:
        async with Harness(bot,root):
            namespace={**vars(bot),'PROJECT_ROOT':root,'DATA_PATHS':DataPaths(Path(root),Path(root)),
                'runtime_code_version':lambda:'oldversion'}
            calls=[]
            def apply(override,**options):
                calls.append((override,options));(Path(root)/'.xgent-version').write_text('a'*40)
                return {'count':7,'backup_path':None}
            namespace['download_and_apply_project_update']=apply
            namespace['restart_current_process']=AsyncMock()
            workbench=Workbench(namespace)
            release={'sha':'a'*40,'commit':{'message':'完整升级内容\nextra','committer':{'date':'2026-11-07T00:00:00Z'}}}
            urls=[]
            def read(request,**kwargs):
                urls.append((request.full_url,request.get_header('Authorization')))
                return io.BytesIO(json.dumps(release).encode())
            with patch('xgent_app.project_updates.urllib.request.urlopen',read):
                plan=await workbench.handle('POST','system/update/check',{'source':'test','token':'fixture-unsaved-token'})
                assert 'fixture-unsaved-token' not in json.dumps(plan)
                data={'plan_id':plan['plan_id'],'request_id':'request1234567890','overwrite_local_custom_files':False,'confirm':True}
                first,repeated=await asyncio.gather(*(workbench.handle('POST','system/update/start',data) for _ in range(2)))
                assert first['id']==repeated['id']
                await asyncio.gather(*workbench._background)
                assert len(calls)==1 and calls[0][0] is False
                assert calls[0][1]['update_url']==bot.BotConfig.TEST_UPDATE_ZIP_URL.rsplit('/',1)[0]+'/'+'a'*40
                assert urls[0][1]=='Bearer fixture-unsaved-token'
                assert 'fixture-unsaved-token' not in ''.join(path.read_text() for path in workbench._project_updates.directory.glob('*.json'))
                namespace['restart_current_process'].assert_awaited_once()
                try:await workbench.handle('POST','system/update/start',{**data,'overwrite_local_custom_files':True})
                except WorkbenchError:pass
                else:assert False,'request collision accepted'
                state=await workbench.handle('GET','system/update',{'id':first['id']});assert state['job']['state']=='restarting'
                state['job']['pid']=-1;workbench._project_updates.save(state['job'])
                state=await workbench.handle('GET','system/update',{'id':first['id']});assert state['job']['state']=='complete'
                plan=await workbench.handle('POST','system/update/check',{'source':'normal'})
                assert plan['up_to_date']
                unchanged=await workbench.handle('POST','system/update/start',{**data,'request_id':'already_current_12345','plan_id':plan['plan_id']})
                assert unchanged['up_to_date'] and unchanged['id'] is None and unchanged['job'] is None
                assert len(calls)==1
                namespace['restart_current_process'].assert_awaited_once()
                release['sha']='b'*40
                plan=await workbench.handle('POST','system/update/check',{'source':'normal'})
                namespace['download_and_apply_project_update']=lambda *a,**k:(_ for _ in ()).throw(OSError('disk fixture failure'))
                failed=await workbench.handle('POST','system/update/start',{**data,'request_id':'request2234567890','plan_id':plan['plan_id']})
                await asyncio.gather(*workbench._background)
                state=await workbench.handle('GET','system/update',{'id':failed['id']})
                assert state['job']['state']=='failed' and 'disk fixture failure' in state['job']['error']
                namespace['restart_current_process'].assert_awaited_once()
                plan=await workbench.handle('POST','system/update/check',{'source':'normal'})
                namespace['download_and_apply_project_update']=apply
                async with bot.get_conversations().operation(execution=True):
                    blocked=await workbench.handle('POST','system/update/start',{**data,'request_id':'request3234567890','plan_id':plan['plan_id']})
                    await asyncio.gather(*workbench._background)
                    state=await workbench.handle('GET','system/update',{'id':blocked['id']})
                    assert state['job']['state']=='failed' and '没有停止任务' in state['job']['error']
                assert len(calls)==1
                return {'pinned':True,'idempotent':True,'token_private':True,'restarted':True,'failure_safe':True}
print(json.dumps(asyncio.run(main())))
''')
    assert all(result.values())


def test_original_downloader_preserves_runtime_and_custom_modes_and_uses_request_source():
    result=run_in_app(r'''
import io,tempfile,zipfile
from pathlib import Path
from unittest.mock import patch
def archive():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as file:
        file.comment=b'a'*40
        for path,body in {'app.py':'new code','prompts/main.txt':'new prompt','skill-public/one.md':'new skill','.env':'never copy',
                          'xgent_memory.db':'never copy','skill-private/private.md':'never copy','workspace/file.txt':'never copy'}.items():
            file.writestr('release-a/'+path,body)
    return stream.getvalue()
with tempfile.TemporaryDirectory() as root:
    path=Path(root);(path/'prompts').mkdir();(path/'prompts/main.txt').write_text('custom prompt')
    (path/'skill-public').mkdir();(path/'skill-public/one.md').write_text('custom skill')
    (path/'.env').write_text('private settings');(path/'xgent_memory.db').write_text('database bytes')
    source='https://api.github.com/repos/HANLINGVABCN/xgent/zipball/'+'a'*40
    requests=[]
    def read(request,**kwargs):requests.append(request);return io.BytesIO(archive())
    with patch.object(bot,'PROJECT_ROOT',root),patch.object(bot,'UPDATE_BACKUP_DIR',str(path/'backup')),patch.object(bot.urllib.request,'urlopen',read):
        kept=bot.download_and_apply_project_update(False,update_url=source,token='fixture-token')
        assert (path/'app.py').read_text()=='new code'
        assert (path/'prompts/main.txt').read_text()=='custom prompt'
        assert (path/'skill-public/one.md').read_text()=='custom skill'
        assert (path/'.env').read_text()=='private settings' and (path/'xgent_memory.db').read_text()=='database bytes'
        assert not (path/'skill-private/private.md').exists() and not (path/'workspace/file.txt').exists()
        applied=bot.download_and_apply_project_update(True,update_url=source,token='fixture-token')
        assert (path/'prompts/main.txt').read_text()=='new prompt'
        assert (path/'skill-public/one.md').read_text()=='new skill'
        assert applied['backup_path'] and (path/'backup').exists()
        assert (path/'.xgent-version').read_text()=='a'*40
        assert requests[0].full_url==source and requests[0].get_header('Authorization')=='Bearer fixture-token'
        assert kept['source']==source
print(json.dumps({'runtime_preserved':True,'custom_preserved':True,'backup':True,'pinned_source':True}))
''')
    assert all(result.values())
