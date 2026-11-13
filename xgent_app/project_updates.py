"""Settings update jobs reuse the existing downloader and restart service."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
import uuid

from .conversations import get_conversations,ConversationBusy
from .data_bundles import write_json


class ProjectUpdates:
    def __init__(self, namespace, background):
        self.ns,self.background=namespace,background
        self.directory=namespace['DATA_PATHS'].storage/'update_backups'/'web-jobs'
        self.plans={}
        self.lock=asyncio.Lock()
        self.active=None

    def version(self):
        stamp=Path(self.ns['PROJECT_ROOT'])/'.xgent-version'
        if stamp.is_file():
            value=stamp.read_text(encoding='utf-8').strip()
            if re.fullmatch(r'[a-f0-9]{7,40}',value):return value
        return self.ns['runtime_code_version']()

    def sources(self):
        config=self.ns['BotConfig']
        return {'normal':config.NORMAL_UPDATE_ZIP_URL,'test':config.TEST_UPDATE_ZIP_URL}

    def status(self, identifier=None):
        result={'current_version':self.version(),'source':'test' if self.ns['BotConfig'].UPDATE_ZIP_URL==self.sources()['test'] else 'normal',
                'has_token':bool(self.ns['BotConfig'].UPDATE_GITHUB_TOKEN),'job':None}
        if identifier and not re.fullmatch(r'[a-f0-9]{32}',identifier):raise ValueError('更新任务标识无效。')
        path=self.directory/(identifier+'.json') if identifier else max(self.directory.glob('*.json'),key=lambda path:path.stat().st_mtime,default=None)
        if identifier and not path.is_file():raise ValueError('更新任务不存在。')
        if path and path.is_file():
            job=json.loads(path.read_text(encoding='utf-8'))
            if job['state']=='restarting' and job['pid']!=os.getpid():
                matched=job['revision'].startswith(self.version()) or self.version().startswith(job['revision'])
                job.update(state='complete' if matched else 'failed',phase='complete' if matched else 'failed',finished_at=time.time())
                if not matched:job['error']='服务已重启，但版本与更新目标不一致，请检查服务目录。'
                write_json(path,job)
            elif job['state']=='running' and job['pid']!=os.getpid():
                job.update(state='failed',phase='failed',error='更新进程已退出，请重新检查版本后重试。')
                write_json(path,job)
            result['job']=job
            result['job']['historical']=job['state'] in {'complete','failed'}
        return result

    async def check(self,data):
        source=data.get('source','normal')
        if source not in self.sources():raise ValueError('请选择主仓库或测试仓库。')
        token=str(data.get('token') or self.ns['BotConfig'].UPDATE_GITHUB_TOKEN or '').strip()
        if len(token)>1000 or any(char in token for char in '\r\n'):raise ValueError('GitHub Token 格式无效。')
        repo=self.sources()[source].split('/zipball/')[0]
        def read():
            request=self.ns['build_update_download_request'](repo+'/commits/main',token)
            try:
                with urllib.request.urlopen(request,timeout=25) as response:
                    return json.loads(response.read(1024*1024))
            except urllib.error.HTTPError as exc:
                if exc.code in {401,403,404}:raise ValueError('无法读取更新源，请检查 GitHub Token 和仓库访问权限。') from None
                raise ValueError('检查更新失败（HTTP '+str(exc.code)+'）。') from None
        release=await asyncio.to_thread(read)
        sha=release.get('sha','')
        if not re.fullmatch(r'[a-f0-9]{40}',sha):raise ValueError('更新源没有返回有效的代码版本。')
        now=time.time();self.plans={key:plan for key,plan in self.plans.items() if now-plan['created_at']<600}
        identifier=uuid.uuid4().hex
        self.plans[identifier]={'created_at':now,'sha':sha,'source':source,'token':token}
        commit=release.get('commit',{})
        return {'plan_id':identifier,'revision':sha,'current_version':self.version(),'up_to_date':sha.startswith(self.version()),
                'message':str(commit.get('message','')).split('\n')[0][:300],'published_at':commit.get('committer',{}).get('date'),
                'source':source}

    def save(self,job,**changes):
        job.update(changes);write_json(self.directory/(job['id']+'.json'),job)

    async def start(self,data):
        request=str(data.get('request_id',''))
        if not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',request):raise ValueError('缺少更新请求标识。')
        if data.get('confirm') is not True or type(data.get('overwrite_local_custom_files')) is not bool:
            raise ValueError('请确认更新范围及本地文件策略。')
        async with self.lock:
            self.directory.mkdir(parents=True,exist_ok=True)
            for path in self.directory.glob('*.json'):
                previous=json.loads(path.read_text(encoding='utf-8'))
                if previous.get('request_id')==request:
                    if previous.get('plan_id')!=data.get('plan_id') or previous['overwrite_local_custom_files']!=data['overwrite_local_custom_files']:
                        raise ValueError('更新请求标识已用于另一项更新。')
                    return {'ok':True,'id':previous['id'],**self.status(previous['id'])}
            if self.active:raise ValueError('更新正在进行，请等待完成。')
            plan=self.plans.get(data.get('plan_id'))
            if not plan or time.time()-plan['created_at']>600:raise ValueError('版本检查已过期，请重新检查更新。')
            if not data['overwrite_local_custom_files'] and plan['sha'].startswith(self.version()):
                return {'ok':True,'up_to_date':True,'id':None,'job':None,'current_version':self.version()}
            job={'id':uuid.uuid4().hex,'request_id':request,'plan_id':data['plan_id'],'revision':plan['sha'],'source':plan['source'],
                 'overwrite_local_custom_files':data['overwrite_local_custom_files'],'state':'running','phase':'pending',
                 'pid':os.getpid(),'created_at':time.time()}
            self.save(job);self.active=job['id']
            self.background(self.run(job,dict(plan)))
            return {'ok':True,'id':job['id'],**self.status(job['id'])}

    async def run(self,job,plan):
        try:
            async with get_conversations().file_maintenance_slot():
                self.save(job,phase='downloading')
                url=self.sources()[plan['source']].rsplit('/',1)[0]+'/'+plan['sha']
                result=await asyncio.to_thread(self.ns['download_and_apply_project_update'],job['overwrite_local_custom_files'],update_url=url,token=plan['token'])
                self.save(job,phase='saved',count=result.get('count',0),backup_path=result.get('backup_path'))
                if job['overwrite_local_custom_files']:await self.ns['reload_overwritten_custom_prompts']()
                self.save(job,state='restarting',phase='restarting')
                await asyncio.sleep(.8)
                await self.ns['restart_current_process'](self.ns['BotConfig'].AUTHORIZED_USER_ID)
        except Exception as exc:
            error='有对话或文件操作正在进行，请等待结束后重新更新；没有停止任务或改动文件。' if isinstance(exc,ConversationBusy) else str(exc)
            if plan['token']:error=error.replace(plan['token'],'[已隐藏]')
            self.save(job,state='failed',phase='failed',error=self.ns['redact_sensitive_text'](error)[:1000])
        finally:
            self.active=None
            self.plans={}
