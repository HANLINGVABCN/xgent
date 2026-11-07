from pathlib import Path
from copy import deepcopy
import pytest
from tests.test_full_output_web import full_output_server
from tests.test_web_presentation import browser_session
from tests.test_thinking_params import run_in_app

@pytest.mark.parametrize('mode',['toolcall','fence'])
@pytest.mark.parametrize('width',[320,390,1440])
def test_command_output_lazy_load_separate_folding_refresh_and_duplicate_commands(full_output_server,tmp_path,mode,width):
    case=run_in_app('import asyncio\nfrom tests.command_output_probe import exercise\n'+f'print(json.dumps(asyncio.run(exercise(bot,{str(tmp_path)!r},{mode!r}))))')
    server=full_output_server[0]
    async def history(limit):return case['history']
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p)
        loads=[]
        def output(route):
            from urllib.parse import parse_qs,urlsplit
            query=parse_qs(urlsplit(route.request.url).query);rid=int(query['record_id'][0]);offset=int(query['offset'][0]);loads.append((rid,offset))
            route.fulfill(json={'text':'OUTPUT_FOR_'+str(rid)+'_'+str(offset),'offset':offset,'next_offset':offset+100,'size':200,'eof':offset>0,'details':{'return_code':0}})
        context.route('**/api/workbench/command-output?*',output)
        page=context.new_page();page.set_viewport_size({'width':width,'height':950});page.goto(base+'/#/chat?conversation=global_memory')
        page.wait_for_function('!document.getElementById("btn-send").disabled')
        row=page.locator('[data-record-id="'+str(case['parent'])+'"]');cards=row.locator('.command-with-output')
        assert cards.count()==2
        assert page.locator('.command-result-attached').count()==2
        assert not loads and page.locator('.output-page-text').count()==0
        first=cards.nth(0);first.get_by_role('button',name='展开命令与输出',exact=True).click()
        assert first.locator('.command-input').is_visible()
        first.get_by_role('button',name='查看输出',exact=True).click()
        first.locator('.output-page-text').wait_for()
        assert loads==[(case['outputs'][0],0)]
        assert first.locator('.output-page-text').inner_text()=='OUTPUT_FOR_'+str(case['outputs'][0])+'_0'
        assert first.evaluate('''card=>Array.from(card.querySelectorAll('.command-text-button')).every(button=>{
            const range=document.createRange();range.selectNodeContents(button);
            const text=range.getBoundingClientRect(),box=button.getBoundingClientRect();
            return text.left>=box.left-1&&text.right<=box.right+1&&text.top>=box.top-1&&text.bottom<=box.bottom+1;
        })'''), '文字必须完整显示在按钮内，不能竖排溢出或与统计重叠'
        assert first.locator('.command-output-tools').evaluate('''tools=>{
            const label=tools.querySelector('.output-page-label').getBoundingClientRect();
            return Array.from(tools.querySelectorAll('button')).every(button=>{
                const box=button.getBoundingClientRect();
                return box.top>=label.bottom-1||box.bottom<=label.top+1||box.left>=label.right-1||box.right<=label.left+1;
            });
        }''')
        first.screenshot(path=str(tmp_path/f'lazy-output-expanded-{mode}-{width}.png'))
        # A late state snapshot from an older record can omit its result ID.
        # It must retain the existing card and its loaded output without refetch.
        live=deepcopy(next(message for message in case['history'] if message['id']==case['parent']))
        live.update(type='record_snapshot',record_id=case['parent'],conversation_id='global_memory')
        for segment in live['web_display']['segments']:
            if segment.get('command_info'):segment['command_info']['result_record_id']=None
        live['web_display']['segments'].insert(0,{'kind':'markdown','text':'状态同步完成。'})
        server.outbox.put(live)
        row.get_by_text('状态同步完成。',exact=True).wait_for()
        assert loads==[(case['outputs'][0],0)] and first.locator('.output-page-text').is_visible()
        first.get_by_role('button',name='收起命令正文',exact=True).click()
        assert not first.locator('.execution-pre').is_visible() and first.locator('.output-page-text').is_visible()
        first.get_by_role('button',name='展开命令正文',exact=True).click()
        first.locator('.execution-pre').click()
        page.wait_for_function('id=>document.querySelector(`[data-record-id="${id}"] .execution-pre`).hidden',arg=case['parent'])
        assert first.locator('.output-page-text').is_visible()
        first.get_by_role('button',name='收起命令与输出',exact=True).click()
        assert not first.locator('.command-input').is_visible() and not first.locator('.command-output-section').is_visible()
        first.get_by_role('button',name='展开命令与输出',exact=True).click()
        assert not first.locator('.execution-pre').is_visible() and first.locator('.output-page-text').is_visible()
        assert len(loads)==1
        first.get_by_role('button',name='下一页',exact=True).click()
        page.wait_for_function('id=>document.querySelector(`[data-record-id="${id}"] .output-page-text`)?.textContent.endsWith("_100")',arg=case['parent'])
        first.get_by_role('button',name='收起输出',exact=True).click()
        assert not first.locator('.command-output-body').is_visible()
        first.get_by_role('button',name='查看输出',exact=True).click()
        assert len(loads)==2
        first.locator('.output-page-text').click()
        page.wait_for_function('id=>document.querySelector(`[data-record-id="${id}"] .command-output-body`).hidden',arg=case['parent'])
        assert first.locator('.command-input').is_visible() and first.locator('.command-output-head').is_visible()
        first.get_by_role('button',name='展开输出正文',exact=True).click()
        assert first.locator('.output-page-text').is_visible() and len(loads)==2
        first.locator('.output-page-text').evaluate('''pre=>{
            const range=document.createRange();range.selectNodeContents(pre);
            getSelection().removeAllRanges();getSelection().addRange(range);pre.click();
        }''')
        page.wait_for_timeout(300)
        assert first.locator('.output-page-text').is_visible(), '选择文字复制不能触发收起'
        page.evaluate('getSelection().removeAllRanges()')
        first.get_by_role('button',name='展开命令正文',exact=True).click()
        first.locator('.execution-pre').evaluate('''pre=>{
            const range=document.createRange();range.selectNodeContents(pre);
            getSelection().removeAllRanges();getSelection().addRange(range);pre.click();
        }''')
        page.wait_for_timeout(300)
        assert first.locator('.execution-pre').is_visible()
        page.evaluate('getSelection().removeAllRanges()')
        second=cards.nth(1);second.get_by_role('button',name='查看输出',exact=True).click();second.locator('.output-page-text').wait_for()
        assert second.locator('.output-page-text').inner_text()=='OUTPUT_FOR_'+str(case['outputs'][1])+'_0'
        page.reload();page.wait_for_function('!document.getElementById("btn-send").disabled')
        assert cards.count()==2 and page.locator('.command-result-attached').count()==2
        assert len(loads)==3 and page.locator('.output-page-text').count()==0
        assert not first.locator('.command-output-body').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(tmp_path/f'lazy-output-{mode}-{width}.png'))
        browser.close()


@pytest.mark.parametrize('width',[390,1440])
def test_command_panels_stay_fixed_before_execution_and_output_loads_only_when_open(full_output_server,tmp_path,width):
    from xgent_app.web_display import web_block_html
    server=full_output_server[0]
    async def history(limit):return []
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p)
        loads=[];pending=[]
        def output(route):loads.append(route.request.url);pending.append(route)
        context.route('**/api/workbench/command-output?*',output)
        page=context.new_page();page.set_viewport_size({'width':width,'height':950})
        page.goto(base+'/#/chat?conversation=global_memory')
        page.wait_for_function('!document.getElementById("btn-send").disabled')
        def emit(state,commands,ids=(None,None)):
            parts=[]
            for index,command in enumerate(commands):
                key='fence:FIXED'+str(index)
                parts.append({'kind':'html','text':web_block_html(command,protocol='run-x',state=state,command_key=key,raw='<<BEGIN_FIXED'+str(index)+'\n'+command),
                    'command_info':{'version':1,'key':key,'state':state,'result_record_id':ids[index]}})
            server.outbox.put({'type':'record_snapshot','record_id':600,'conversation_id':'global_memory','msg_type':'ai_reply',
                'role':'assistant','text':'','web_display':{'version':1,'segments':parts}})
        emit('generating',('printf','echo'))
        cards=page.locator('[data-record-id="600"] .command-with-output');first=cards.nth(0);second=cards.nth(1)
        first.wait_for();page.evaluate('window.fixedCards=Array.from(document.querySelectorAll(".command-with-output"))')
        first.get_by_role('button',name='展开命令与输出',exact=True).click()
        assert first.locator('.command-input').is_visible() and first.locator('.command-output-head').is_visible()
        assert not loads and not first.locator('.command-output-body').is_visible()
        first.get_by_role('button',name='展开输出正文',exact=True).click()
        assert first.locator('.command-output-spinner').is_visible() and not loads
        emit('running',('printf "完整命令"','echo "另一个命令"'))
        first.locator('.execution-pre').get_by_text('printf "完整命令"',exact=True).wait_for()
        assert first.locator('.command-output-spinner').is_visible() and not loads
        assert page.evaluate('fixedCards.every((card,i)=>card===document.querySelectorAll(".command-with-output")[i])')
        # Closing a waiting output cancels interest: completion cannot preload it.
        first.get_by_role('button',name='收起输出正文',exact=True).click()
        emit('success',('printf "完整命令"','echo "另一个命令"'),(700,701))
        first.locator('.execution-label').get_by_text('run-x 已运行',exact=True).wait_for()
        assert not loads and not first.locator('.command-output-body').is_visible()
        first.get_by_role('button',name='展开输出正文',exact=True).click()
        first.locator('.command-output-spinner').wait_for()
        page.wait_for_timeout(100)
        assert len(loads)==1 and 'record_id=700&' in loads[0]
        pending.pop().fulfill(json={'text':'完整结果','offset':0,'next_offset':12,'size':12,'eof':True,'details':{}})
        first.locator('.output-page-text').get_by_text('完整结果',exact=True).wait_for()
        assert not first.locator('.command-output-spinner').count()
        assert not second.locator('.output-page-text').count() and len(loads)==1
        assert page.evaluate('fixedCards.every((card,i)=>card===document.querySelectorAll(".command-with-output")[i])')
        page.screenshot(path=str(tmp_path/f'fixed-command-panels-{width}.png'))
        browser.close()
