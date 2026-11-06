"""Inspect every settings panel and chat surface using an isolated browser fixture."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
PANELS = {
    'appearance':'.branding-form', 'conversation':'[name=global_depth]', 'agent':'[name=agent_max_iterations]',
    'web':'[name=web_public_url]', 'data':'.wb-backup-config-form', 'health':'.wb-diagnostics',
    'tasks':'.wb-task-stats', 'files':'form.wb-file-dates', 'models':'.wb-provider-list',
    'usage':'.wb-usage-stats', 'archive':'.settings-archive-panel',
}


def start_fixture():
    process = subprocess.Popen(
        [sys.executable,'-u',str(ROOT/'tools/workbench_fixture.py'),'--messages','120','--conversations','12','--workbench-demo'],
        cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
        env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHON_DOTENV_DISABLED':'1'})
    lines = queue.Queue()
    threading.Thread(target=lambda:[lines.put(line) for line in process.stdout],daemon=True).start()
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        try:line=lines.get(timeout=1)
        except queue.Empty:continue
        try:info=json.loads(line)
        except ValueError:continue
        if isinstance(info,dict) and 'url' in info:return process,info
    process.terminate();process.wait(10)
    raise RuntimeError('Isolated preview fixture did not start')


def main(default_output='workspace/frontend-rebuild/qa'):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default=default_output)
    parser.add_argument('--url')
    args=parser.parse_args()
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    process=None
    if args.url:fixture={'url':args.url,'password':'preview-only'}
    else:process,fixture=start_fixture()
    errors=[];layouts=[];input_ms=[];switch_ms=[];screens=0
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            try:
                for width,height in [(1440,960),(768,1024),(390,844),(320,640)]:
                    for theme in ['light','dark']:
                        context=browser.new_context(viewport={'width':width,'height':height},
                            timezone_id='Asia/Shanghai',is_mobile=width<768,has_touch=width<=768)
                        assert context.request.post(fixture['url']+'/api/login',data={'password':fixture['password']}).ok
                        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(fixture['url']) else route.abort())
                        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                        page.emulate_media(reduced_motion='reduce')
                        page.add_init_script("localStorage.setItem('xgent-theme', '"+theme+"')")
                        page.goto(fixture['url']+'/#/chat?conversation=global_memory');page.locator('#composer-model').wait_for();page.locator('#log .msg-row').first.wait_for()

                        def capture(name):
                            nonlocal screens
                            overflow=page.evaluate('document.documentElement.scrollWidth-innerWidth')
                            layouts.append({'viewport':width,'theme':theme,'surface':name,'overflow':overflow})
                            assert overflow<=1,(width,theme,name,overflow)
                            page.screenshot(path=str(output/f'{width}-{theme}-{name}.png'));screens+=1

                        def panel(name):
                            if page.evaluate('document.body.dataset.page')=='chat':
                                if page.locator('#workspace-settings').is_hidden():page.locator('#conversation-mobile-toggle').click()
                                page.locator('#workspace-settings').click();page.locator('.wb-settings-nav').wait_for()
                            page.locator('.wb-settings-nav [data-panel='+name+']').click()
                            page.locator(PANELS[name]).first.wait_for()
                            page.locator('#settings-content').evaluate('(node)=>node.scrollTop=0')
                            assert page.evaluate('document.body.dataset.page')=='settings'
                            assert page.url.endswith('#/settings')

                        page.locator('#log').evaluate('(node)=>node.scrollTop=0');capture('chat')
                        page.locator('#log').evaluate('(node)=>node.scrollTop=node.scrollHeight');capture('chat-status')
                        input_ms.append(page.evaluate('''()=>new Promise(resolve=>{
                            const start=performance.now(),input=document.querySelector('#input');
                            input.value='即时输入';input.dispatchEvent(new Event('input',{bubbles:true}));
                            requestAnimationFrame(()=>resolve(performance.now()-start));
                        })'''))
                        for kind in ['chat_model','generation']:
                            trigger='#composer-model' if kind=='chat_model' else '#composer-generation-options'
                            page.locator(trigger).click();page.locator('#composer-options-popover').wait_for();capture('composer-'+kind);page.keyboard.press('Escape')
                        page.locator('#btn-composer-menu').click();page.locator('#composer-commands').wait_for();capture('commands');page.keyboard.press('Escape')
                        for name in PANELS:
                            panel(name);capture(name)
                            if name=='appearance':
                                page.locator('.brand-code-details>summary').click();capture('appearance-code')
                            elif name=='tasks':
                                page.get_by_role('button',name='创建任务',exact=True).first.click();page.locator('#wb-dialog').wait_for();capture('task-form');page.keyboard.press('Escape')
                                page.get_by_role('button',name='详情',exact=True).first.click();page.locator('#wb-detail .wb-output-text').wait_for();capture('task-detail');page.locator('#wb-detail-close').click()
                            elif name=='files':
                                page.get_by_role('button',name='预览',exact=True).first.click();page.locator('.wb-document-preview').wait_for();capture('file-preview');page.locator('#wb-detail-close').click()
                                page.get_by_role('tab',name='命令输出',exact=True).click();page.get_by_role('button',name='查看完整输出',exact=True).first.wait_for();capture('files-output')
                            elif name=='models':
                                page.get_by_role('button',name='添加提供商',exact=True).first.click();page.locator('#wb-dialog [name=api_key]').wait_for();capture('provider-form');page.keyboard.press('Escape')
                                page.get_by_role('button',name='技能库',exact=True).click();page.locator('.wb-skill-grid').wait_for();capture('skills')
                        panel('tasks');panel('files')
                        elapsed=page.evaluate('''()=>new Promise(resolve=>{
                            const start=performance.now();document.querySelector('.wb-settings-nav [data-panel=tasks]').click();
                            const check=()=>{if(document.querySelector('#settings-content .wb-task-stats'))resolve(performance.now()-start);else requestAnimationFrame(check);};check();
                        })''');switch_ms.append(elapsed)
                        if page.locator('.wb-brand').is_hidden():page.locator('#conversation-mobile-toggle').click()
                        page.locator('.wb-brand').click();page.wait_for_function('document.body.dataset.page==="chat"')
                        for message_size,ui_size in [(12,12),(24,20)]:
                            page.evaluate('([message,ui])=>window.XGentAppearance.preview({web_message_font_size:message,web_ui_font_size:ui})',[message_size,ui_size])
                            capture('chat-font-'+str(message_size))
                        page.goto(fixture['url']+'/terminal');page.locator('#sessionBar').wait_for();page.wait_for_timeout(200);capture('terminal')
                        context.close()
                        print(json.dumps({'viewport':[width,height],'theme':theme,'screens':screens}),flush=True)
                for width,height in [(1440,960),(390,844)]:
                    context=browser.new_context(viewport={'width':width,'height':height})
                    page=context.new_page();page.goto(fixture['url']);page.locator('#login[open]').wait_for()
                    page.screenshot(path=str(output/f'{width}-login.png'));screens+=1;context.close()
            finally:browser.close()
        report={'page_errors':errors,'layouts':layouts,'screenshots':screens,'input_feedback_ms_max':round(max(input_ms),2),
                'cached_panel_ms_max':round(max(switch_ms),2),'fixture':'isolated','pages':['chat','settings']}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({key:value for key,value in report.items() if key!='layouts'},ensure_ascii=False),flush=True)
        if errors:raise AssertionError(errors)
    finally:
        if process:process.terminate();process.wait(10)


if __name__=='__main__':main()
