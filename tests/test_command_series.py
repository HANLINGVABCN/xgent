from pathlib import Path

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.web_display import build_web_display, build_operation_display, stopped_web_display
from xgent_app.presentation import PresentationTurn, message_presentation, summary_line
from xgent_app.presentation_delivery import PresentationBot


def frames():
    values=[]
    for index, record in enumerate((901, 903, 906, 908)):
        call={'id': 'call-'+str(record), 'name': 'exec_command', 'arguments': {'command': 'echo line\n  echo '+str(record)}}
        calls=[call]
        operations=[{'sequence':index+1,'elapsed_seconds':10}]
        if index==0:
            calls.append({'id':'extra-call','name':'exec_command','arguments':{'command':'echo extra'}})
            operations.append({'sequence':5,'elapsed_seconds':10})
        values.append({'id':record,'record_id':record,'msg_type':'ai_reply','role':'assistant','text':'',
            'timestamp':record,'run_id':'series-run','reply_group_id':'series-group',
            'ai_generation':{'provider':'fixture-provider','model':'fixture-model','generated_at':record},
            'thinking':{'version':1,'capture_id':'thinking-'+str(record),'revision':1,
                'text':'思考原文 '+str(record)+'\n  思考缩进保持','status':'completed','elapsed_seconds':None},
            'execution_metrics':{'response_seconds':5,'operations':operations},
            'web_display':build_web_display('',presentation={'native_calls':calls,
                'usage':{'input_tokens':1000,'output_tokens':20,'cached_tokens':500},'elapsed_seconds':5})})
        values.append({'id':record*10,'record_id':record*10,'msg_type':'agent_result','role':'assistant',
            'timestamp':record+.5,'run_id':'series-run','reply_group_id':'series-group','text':'output '+str(record),
            'web_display':build_operation_display({'success':True,'output':'output '+str(record)+'\n  输出缩进保持'},'folded')})
        values.append({'id':record+1,'record_id':record+1,'msg_type':'agent_status','role':'assistant',
            'timestamp':record+1,'run_id':'series-run','reply_group_id':'series-group',
            'text':f'Agent 第 {index+1} 轮 · {len(calls)} 个操作'})
        if index==1:
            values.append({'id':905,'record_id':905,'msg_type':'ai_reply','role':'assistant','text':'中间说明',
                'timestamp':905,'run_id':'series-run','reply_group_id':'series-group'})
    values.append({'id':910,'record_id':910,'msg_type':'ai_reply','role':'assistant','text':'最后正文',
        'timestamp':910,'run_id':'series-run','reply_group_id':'series-group','reply_complete':True,
        'execution_summary':{'items':[{'sequence':i+1,'reply_record_id':record,'elapsed_seconds':10}
                                    for i,record in enumerate((901,903,906,908))]+
                                    [{'sequence':5,'reply_record_id':901,'elapsed_seconds':10}]}})
    return values


@pytest.mark.parametrize('mobile', [False, True])
@pytest.mark.parametrize('dark', [False, True])
def test_series_fold_only_after_completion_and_count_each_series_independently(full_output_server, mobile, dark, tmp_path):
    server, _, _, _ = full_output_server
    values=[]
    async def history(limit):
        return [{**value,'content':value['text']} for value in values]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        try:
            page=context.new_page()
            if mobile:page.set_viewport_size({'width':390,'height':844})
            else:page.set_viewport_size({'width':1871,'height':950})
            page.goto(base);page.wait_for_function('!document.getElementById("btn-send").disabled')
            page.evaluate('(dark)=>document.body.classList.toggle("dark",dark)',dark)
            server.outbox.put({'type':'chat_action','action':'typing','conversation_id':'global_memory','run_id':'series-run'})
            for value in frames():server.outbox.put({**value,'type':'record_snapshot','conversation_id':'global_memory'})
            page.locator('[data-record-id="910"]').wait_for()
            assert page.locator('.command-series-control').count()==0
            head=page.locator('[data-record-id="901"] .bubble-header')
            head.evaluate('node=>window.__seriesAuthor=node')
            body_left=page.locator('[data-record-id="901"] .body').bounding_box()['x']
            server.outbox.put({'type':'generation_end','conversation_id':'global_memory','run_id':'series-run',
                               'reply_group_id':'series-group','reply_complete':True})
            page.wait_for_function('document.querySelectorAll(".command-series-control").length===2')
            assert page.locator('.command-series-toggle:visible').count()==2
            assert page.locator('.command-series-toggle em').all_inner_texts()==[
                '共执行 2 轮，3 个操作 · 总耗时约 40 秒', '共执行 2 轮，2 个操作 · 总耗时约 30 秒']
            assert head.is_visible()
            assert head.inner_text()=='X\nXGent\nfixture-provider / fixture-model'
            assert page.locator('.msg-row.ai .bubble-header:visible').count()==1
            assert abs(page.locator('.command-series-toggle').first.bounding_box()['x']-body_left)<1
            assert page.locator('[data-record-id="901"] .thinking-block').is_hidden()
            assert page.locator('[data-record-id="901"] .body').is_hidden()
            assert page.locator('[data-record-id="901"] .message-footer').is_hidden()
            assert page.locator('[data-record-id="9010"]').is_hidden()
            assert page.locator('[data-record-id="903"]').is_hidden()
            assert page.locator('[data-record-id="9030"]').is_hidden()
            page.screenshot(path=str(tmp_path/'series-collapsed.png'))
            assert page.locator('[data-record-id="910"] .body').inner_text()=='最后正文'
            assert page.locator('[data-record-id="905"]').is_visible()
            page.locator('.command-series-toggle').first.click()
            assert head.evaluate('node=>window.__seriesAuthor===node')
            assert page.locator('[data-record-id="901"] .thinking-block').is_visible()
            assert page.locator('[data-record-id="9010"]').is_visible()
            assert page.locator('[data-record-id="903"] .thinking-block').is_visible()
            assert page.locator('[data-record-id="9030"]').is_visible()
            assert '↑ 1,000' in page.locator('[data-record-id="901"] .message-footer').inner_text()
            head.hover()
            page.locator('.command-series-close:visible').wait_for(state='hidden')
            page.locator('[data-record-id="901"] .execution-row').first.hover()
            close=page.locator('.command-series-close:visible')
            close.wait_for()
            close_box=close.bounding_box()
            log_right=page.locator('#log').evaluate('node=>node.getBoundingClientRect().left+node.clientLeft+node.clientWidth')
            assert abs(close_box['x']+close_box['width']-(log_right-8))<1
            if not mobile:
                first_bubble=page.locator('[data-record-id="901"] .bubble').bounding_box()
                assert close_box['x']>first_bubble['x']+first_bubble['width']
            assert close_box['y']>head.bounding_box()['y']+head.bounding_box()['height']
            page.screenshot(path=str(tmp_path/'series-expanded-hover.png'))
            page.locator('[data-record-id="905"] .body').hover()
            close.wait_for(state='hidden')
            assert page.locator('[data-record-id="902"] .body').inner_text()=='Agent 第 1 轮 · 2 个操作'
            assert page.locator('[data-record-id="904"] .body').inner_text()=='Agent 第 2 轮 · 1 个操作'
            block=page.locator('[data-record-id="901"] blockquote').first
            page.locator('[data-record-id="901"] .execution-row').first.click()
            page.wait_for_function(r'''document.querySelector('[data-record-id="901"] blockquote').classList.contains('expanded')''')
            assert page.locator('[data-record-id="901"] .execution-pre').first.text_content()=='echo line\n  echo 901'
            page.locator('[data-record-id="901"] .thinking-head').click()
            page.locator('[data-record-id="901"] .thinking-body').wait_for(state='visible')
            before=page.locator('[data-record-id="901"] .body').inner_html()
            page.locator('[data-record-id="9010"] .execution-row').hover()
            page.locator('.command-series-close:visible').first.click()
            page.locator('.command-series-toggle').first.click()
            assert 'expanded' in block.get_attribute('class')
            assert page.locator('[data-record-id="901"] .body').inner_html()==before
            assert page.locator('[data-record-id="901"] .thinking-body').is_visible()
            values.extend(frames())
            page.reload();page.locator('[data-record-id="910"]').wait_for()
            page.wait_for_function('document.querySelectorAll(".command-series-control").length===2')
            page.locator('#input').hover()
            page.locator('.command-series-close:visible').wait_for(state='hidden')
            assert head.is_visible()
            assert page.locator('.command-series-toggle:visible').count()==1
            page.locator('.command-series-toggle:visible').click()
            assert page.locator('[data-record-id="909"] .body').inner_text()=='Agent 第 4 轮 · 1 个操作'
        finally:browser.close()


def test_sent_files_stay_visible_between_collapsed_command_sequences(full_output_server):
    server, _, _, _=full_output_server
    values=frames()
    call={'id':'send-config','name':'send_file','arguments':{'path':'/workspace/config.yaml'}}
    first=next(value for value in values if value['id']==903)
    first['web_display']=build_web_display('',presentation={'native_calls':[call]})
    values=[value for value in values if value['id']!=905]
    values.insert(next(index for index,value in enumerate(values) if value['id']==906),{
        'id':905,'record_id':905,'msg_type':'agent_result','role':'assistant','text':'📄 config.yaml',
        'timestamp':905,'run_id':'series-run','reply_group_id':'series-group','file_message':True,
        'media':[{'kind':'file','filename':'config.yaml','download_url':'/api/media/config-fixture'}]})
    async def history(limit):return [{**value,'content':value['text']} for value in values]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        try:
            page=context.new_page();page.goto(base)
            page.wait_for_function('document.querySelectorAll(".command-series-toggle").length===2')
            card=page.locator('[data-record-id="905"] .file-card')
            assert card.is_visible()
            assert card.locator('.fc-name').inner_text()=='config.yaml'
            download=card.get_by_role('link',name='下载')
            assert download.is_visible() and download.get_attribute('href')=='/api/media/config-fixture'
            assert page.locator('[data-record-id="901"] .thinking-block').is_hidden()
            assert page.locator('[data-record-id="903"] .body').is_hidden()
            assert page.locator('[data-record-id="906"] .thinking-block').is_hidden()
            assert page.locator('.bubble-header:visible',has_text='XGent').count()==1
            page.reload();page.locator('[data-record-id="905"] .file-card').wait_for()
            assert download.is_visible()
            assert page.locator('[data-record-id="903"] .body').is_hidden()
        finally:browser.close()


def test_touch_and_keyboard_can_collapse_without_hover(full_output_server):
    server, _, _, _=full_output_server
    async def history(limit):return [{**value,'content':value['text']} for value in frames()]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        try:
            page=context.new_page();page.goto(base)
            page.locator('.command-series-toggle').first.wait_for()
            page.locator('.command-series-toggle').first.focus()
            page.keyboard.press('Enter')
            close=page.locator('.command-series-close:visible')
            close.wait_for();close.focus();page.keyboard.press('Enter')
            assert page.locator('[data-record-id="901"] .thinking-block').is_hidden()
            assert page.locator('[data-record-id="901"] .bubble-header').is_visible()
            touch=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            touch.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base) else route.abort())
            assert touch.request.post(base+'/api/login',data={'password':'temporary-test-only'}).ok
            phone=touch.new_page();phone.goto(base)
            phone.locator('.command-series-toggle').first.wait_for()
            assert phone.evaluate('matchMedia("(hover: none) and (pointer: coarse)").matches')
            phone.locator('.command-series-toggle').first.tap()
            phone.locator('.command-series-close:visible').first.wait_for()
            phone.locator('.command-series-close:visible').first.tap()
            assert phone.locator('[data-record-id="901"] .thinking-block').is_hidden()
            assert phone.locator('[data-record-id="901"] .bubble-header').is_visible()
            touch.close()
        finally:browser.close()


def test_removed_command_sequence_removes_its_side_button(full_output_server):
    server, _, _, _=full_output_server
    values=frames()
    async def history(limit):return [{**value,'content':value['text']} for value in values]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        try:
            page=context.new_page();page.goto(base)
            page.locator('.command-series-toggle').first.wait_for()
            page.locator('.command-series-toggle').first.click()
            page.locator('[data-record-id="901"] .execution-row').first.hover()
            page.locator('.command-series-close:visible').wait_for()
            values.clear()
            page.evaluate('window.XGentChat.reload()')
            page.wait_for_function('!document.querySelector(".command-series-control")&&!document.querySelector(".command-series-close")')
            assert page.locator('.command-series-collapsed').count()==0
        finally:browser.close()


def test_stop_notice_is_single_live_and_after_refresh_without_hiding_raw_errors(full_output_server):
    server, _, _, _=full_output_server
    values=[
        {'id':701,'record_id':701,'msg_type':'ai_reply','role':'assistant','text':'已生成正文',
         'run_id':'stopped-run','reply_group_id':'stopped-group','web_display':stopped_web_display('已生成正文')},
        {'id':702,'record_id':702,'msg_type':'agent_status','role':'assistant','text':'⏹ 已停止，已有结果保留。',
         'run_id':'stopped-run','reply_group_id':'stopped-group','web_display':build_web_display('⏹ 已停止，已有结果保留。',
             presentation={'terminal_status':'stopped','terminal_only':True})},
        {'id':703,'record_id':703,'msg_type':'runtime_error','role':'assistant','text':'⚠️ 原始报错\npermission denied'},
    ]
    async def empty(limit):return []
    server.config.read_history=empty
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        try:
            page=context.new_page();page.goto(base);page.wait_for_function('!document.getElementById("btn-send").disabled')
            for value in values:server.outbox.put({**value,'type':'record_snapshot'})
            page.locator('[data-record-id="703"]').wait_for()
            page.wait_for_function('document.querySelector(".stop-notice").hidden')
            assert page.locator('#log').inner_text().count('已停止')==1
            assert 'permission denied' in page.locator('#log').inner_text()
            async def history(limit):return [{**value,'content':value['text']} for value in values]
            server.config.read_history=history
            page.reload();page.locator('[data-record-id="703"]').wait_for()
            assert page.locator('#log').inner_text().count('已停止')==1
            assert '原始报错' in page.locator('#log').inner_text()
        finally:browser.close()


def test_failed_operation_does_not_become_a_failed_task_or_failed_summary():
    from types import SimpleNamespace
    turn=PresentationTurn('folded')
    bot=PresentationBot(SimpleNamespace(),turn)
    with message_presentation({'kind':'agent_status'}):
        assert bot._prepare('⚠️ Agent 第 4 轮 · 处理失败，结果已保留','agent_status',None)
    assert turn.terminal_status=='completed' and turn.reason==''
    text=summary_line({'rounds':2,'operations':3,'elapsed_seconds':155,'reason':'⚠️ 本次处理失败，已有结果已保留。'})
    assert text=='共执行 2 轮，3 个操作 · 总耗时约 155 秒'


@pytest.mark.parametrize('format', ['markdown', 'html'])
def test_replies_with_dialog_and_commands_never_enter_the_large_fold(full_output_server, format):
    server, _, _, _=full_output_server
    values=[value for value in frames() if value['id'] in {901,9010,902,903,9030,904,910}]
    for value in values:
        if value['id'] not in {901,903}:continue
        text='这轮有普通对话，不能整条隐藏。'
        value['text']=text
        if format=='markdown':
            value['web_display']['segments'].insert(0,{'kind':'markdown','text':text})
        else:
            value['web_display']['segments'][0]['text']='<p>'+text+'</p>'+value['web_display']['segments'][0]['text']
    async def history(limit):return [{**value,'content':value['text']} for value in values]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        try:
            page=context.new_page();page.goto(base)
            page.locator('[data-record-id="910"]').wait_for()
            assert page.locator('.command-series-control').count()==0
            assert page.locator('.command-series-collapsed').count()==0
            for record in (901,903):
                assert page.locator(f'[data-record-id="{record}"]').is_visible()
                assert '这轮有普通对话' in page.locator(f'[data-record-id="{record}"] .body').inner_text()
                assert page.locator(f'[data-record-id="{record}"] .execution-row').first.is_visible()
            assert page.locator('[data-record-id="910"] .body').inner_text()=='最后正文'
            page.reload();page.locator('[data-record-id="910"]').wait_for()
            assert page.locator('.command-series-control').count()==0
        finally:browser.close()


@pytest.mark.parametrize('command_rounds', [1,2,3])
def test_only_consecutive_command_replies_count_toward_the_two_round_threshold(full_output_server, command_rounds):
    server, _, _, _=full_output_server
    values=[]
    for index in range(command_rounds+1):
        record=801+index*3
        text='开场说明留在外面。' if index==0 else ''
        call={'id':'call-'+str(record),'name':'exec_command','arguments':{'command':'echo '+str(record)}}
        values.append({'id':record,'record_id':record,'timestamp':record,'msg_type':'ai_reply','role':'assistant','text':text,
            'run_id':'threshold-run','reply_group_id':'threshold-group',
            'execution_metrics':{'response_seconds':5,'operations':[{'sequence':index+1,'elapsed_seconds':10}]},
            'web_display':build_web_display(text,presentation={'native_calls':[call]})})
        values.append({'id':record+1,'record_id':record+1,'timestamp':record+1,'msg_type':'agent_status','role':'assistant',
            'run_id':'threshold-run','reply_group_id':'threshold-group','text':f'Agent 第 {index+1} 轮 · 1 个操作'})
    values.append({'id':899,'record_id':899,'timestamp':899,'msg_type':'ai_reply','role':'assistant','text':'最后说明也留在外面。',
        'run_id':'threshold-run','reply_group_id':'threshold-group','reply_complete':True})
    async def history(limit):return [{**value,'content':value['text']} for value in values]
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():pytest.skip('Chromium unavailable')
        browser,context,base=browser_session(server,p)
        try:
            page=context.new_page();page.goto(base)
            page.locator('[data-record-id="899"]').wait_for()
            assert page.locator('[data-record-id="801"] .body').is_visible()
            assert '开场说明留在外面' in page.locator('[data-record-id="801"] .body').inner_text()
            assert page.locator('[data-record-id="899"] .body').is_visible()
            if command_rounds<2:
                assert page.locator('.command-series-control').count()==0
                assert page.locator('[data-record-id="804"] .execution-row').is_visible()
            else:
                page.locator('.command-series-toggle').wait_for()
                assert page.locator('.command-series-control').count()==1
                assert page.locator('.command-series-toggle em').inner_text()==(
                    f'共执行 {command_rounds} 轮，{command_rounds} 个操作 · 总耗时约 {command_rounds*15} 秒')
                for index in range(1,command_rounds+1):
                    assert page.locator(f'[data-record-id="{801+index*3}"] .body').is_hidden()
                page.locator('.command-series-toggle').click()
                for index in range(1,command_rounds+1):
                    assert page.locator(f'[data-record-id="{802+index*3}"] .body').inner_text()==f'Agent 第 {index+1} 轮 · 1 个操作'
                assert '最后说明也留在外面' in page.locator('#log').inner_text()
        finally:browser.close()
