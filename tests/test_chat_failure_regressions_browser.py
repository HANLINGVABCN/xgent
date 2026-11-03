"""Failure completion and folded-history paging over isolated Chromium."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_attachments import image_bytes
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.web_display import build_web_display, build_operation_display


@pytest.fixture
def chat_browser(full_output_server):
    playwright = pytest.importorskip('playwright.sync_api')
    server = full_output_server[0]
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists(): pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        page = context.new_page()
        yield server, page, base
        browser.close()


def commands(start=1, count=4, *, run='failed-run', group=None):
    rows = []
    for index in range(count):
        identifier = start + index * 3
        base = {'run_id': run, 'conversation_id': 'global_memory', **({'reply_group_id': group} if group else {})}
        call = {'id': str(identifier), 'name': 'exec_command', 'arguments': {'command': 'echo actual-' + str(identifier)}}
        rows.extend([
            {**base, 'id': identifier, 'record_id': identifier, 'timestamp': identifier, 'msg_type': 'ai_reply',
             'role': 'assistant', 'content': '', 'text': '', 'history_cursor': str(identifier),
             'web_display': build_web_display('', presentation={'native_calls': [call]})},
            {**base, 'id': identifier + 1, 'record_id': identifier + 1, 'timestamp': identifier + 1,
             'role': 'assistant', 'msg_type': 'agent_result', 'content': 'ACTUAL_OUTPUT', 'text': 'ACTUAL_OUTPUT',
             'history_cursor': str(identifier + 1), 'web_display': build_operation_display({'success': True, 'output': 'ACTUAL_OUTPUT'}, 'folded')},
            {**base, 'id': identifier + 2, 'record_id': identifier + 2, 'timestamp': identifier + 2,
             'role': 'assistant', 'msg_type': 'agent_status', 'content': f'Agent 第 {index+1} 轮 · 1 个操作',
             'text': f'Agent 第 {index+1} 轮 · 1 个操作', 'history_cursor': str(identifier + 2)},
        ])
    return rows


def test_terminal_error_folds_commands_even_when_live_rows_only_have_run_id(chat_browser):
    server, page, base = chat_browser
    async def history(limit): return []
    server.config.read_history = history
    page.goto(base);page.wait_for_function('!document.getElementById("btn-send").disabled')
    server.outbox.put({'type': 'chat_action', 'action': 'typing', 'conversation_id': 'global_memory', 'run_id': 'failed-run'})
    for message in commands(): server.outbox.put({**message, 'type': 'record_snapshot'})
    server.outbox.put({'type': 'record_snapshot', 'conversation_id': 'global_memory', 'run_id': 'failed-run',
        'id': 20, 'record_id': 20, 'role': 'assistant', 'msg_type': 'runtime_error', 'text': '⚠️ ORIGINAL_CONNECT_ERROR'})
    server.outbox.put({'type': 'generation_end', 'conversation_id': 'global_memory', 'run_id': 'failed-run',
                      'reply_group_id': 'final-response-group', 'reply_complete': True})
    page.locator('[data-record-id="20"]').wait_for()
    page.locator('.command-series-toggle').wait_for()
    assert page.locator('[data-record-id="1"] .body').is_hidden()
    assert page.locator('[data-record-id="20"] .body').is_visible()
    assert 'ORIGINAL_CONNECT_ERROR' in page.locator('[data-record-id="20"]').inner_text()


def test_failure_collapse_keeps_the_latest_error_visible(chat_browser):
    server,page,base=chat_browser
    async def history(limit):return [{'id':i,'role':'assistant','msg_type':'agent_status',
        'content':f'Agent 第 {i} 轮 · 1 个操作','timestamp':i} for i in range(1,31)]
    server.config.read_history=history
    page.goto(base);page.wait_for_function('!document.getElementById("btn-send").disabled')
    server.outbox.put({'type':'chat_action','action':'typing','conversation_id':'global_memory','run_id':'failed-run'})
    for message in commands(100,32):server.outbox.put({**message,'type':'record_snapshot'})
    server.outbox.put({'type':'record_snapshot','id':200,'record_id':200,'role':'assistant','msg_type':'runtime_error',
        'conversation_id':'global_memory','run_id':'failed-run','text':'LATEST_VISIBLE_FAILURE'})
    server.outbox.put({'type':'generation_end','conversation_id':'global_memory','run_id':'failed-run',
        'reply_group_id':'real-group','reply_complete':True})
    page.locator('.command-series-toggle').wait_for()
    error=page.locator('[data-record-id="200"]')
    page.wait_for_timeout(100)
    viewport=page.locator('#log').bounding_box();bounds=error.bounding_box()
    assert bounds['y']>=viewport['y']-1
    assert bounds['y']+bounds['height']<=viewport['y']+viewport['height']+1


def test_real_model_error_has_avatar_and_raw_text_before_and_after_refresh(chat_browser):
    server, page, base = chat_browser
    error = {'id': 41, 'record_id': 41, 'role': 'assistant', 'msg_type': 'runtime_error',
        'content': '⚠️ {"native_finish_reason":"prohibited_content"}', 'model_error': True,
        'ai_generation': {'provider': 'fixture-provider', 'model': 'fixture-model', 'generated_at': 1},
        'web_display': {'version': 1, 'plain_text': '⚠️ {"native_finish_reason":"prohibited_content"}',
                        'model_error': True, 'segments': []}}
    async def history(limit): return [error]
    server.config.read_history = history
    page.goto(base);page.locator('[data-record-id="41"]').wait_for()
    for _ in range(2):
        entry = page.locator('[data-record-id="41"]')
        assert entry.locator('.bubble-header').is_visible()
        assert 'XGent' in entry.locator('.bubble-author').inner_text()
        assert 'fixture-provider / fixture-model' in entry.locator('.ai-generation-meta').inner_text()
        assert entry.locator('.body').inner_text() == error['content']
        assert entry.locator('.code-block-wrap').count() == 0
        page.reload();entry.wait_for()


def test_send_file_image_uses_image_preview_and_keeps_download(chat_browser):
    server, page, base = chat_browser
    message = {'id': 42, 'role': 'assistant', 'msg_type': 'agent_result', 'file_message': True,
        'content': '📄 original.png (128 bytes)', 'media': [{'kind': 'file', 'mime_type': 'image/png',
            'filename': 'original.png', 'path': '/workspace/original.png', 'download_url': '/api/media/preview-image'}]}
    async def history(limit): return [message]
    server.config.read_history = history
    page.route('**/api/media/preview-image*', lambda route: route.fulfill(body=image_bytes('PNG'), content_type='image/png'))
    page.goto(base)
    image = page.locator('[data-record-id="42"] .media-photo')
    image.wait_for()
    assert page.locator('[data-record-id="42"] .file-card').count() == 0
    image.locator('.media-img').click();page.locator('#lightbox.open').wait_for()
    assert page.locator('#lightbox-filename').inner_text() == 'original.png'
    assert page.locator('#lightbox-dl').get_attribute('href') == '/api/media/preview-image'


def test_send_file_text_preview_uses_the_existing_scoped_preview_service(chat_browser):
    server, page, base = chat_browser
    message={'id':43,'role':'assistant','msg_type':'agent_result','file_message':True,'content':'📄 config.yaml',
        'media':[{'id':'43:0','kind':'file','mime_type':'text/plain','filename':'config.yaml',
                  'download_url':'/api/media/config','conversation_id':'global_memory'}]}
    async def history(limit):return [message]
    server.config.read_history=history
    requested=[]
    def preview(route):
        query=parse_qs(urlsplit(route.request.url).query);requested.append(query)
        route.fulfill(json={'text':'ACTUAL_CONFIG: true\n','offset':0,'next_offset':20,'eof':True,'size':20,'encoding':'UTF-8'})
    page.route('**/api/workbench/artifacts/preview?*',preview)
    page.goto(base);page.locator('[data-record-id="43"] .fc-preview').wait_for()
    page.locator('[data-record-id="43"] .fc-preview').click()
    page.get_by_text('ACTUAL_CONFIG: true',exact=False).first.wait_for()
    assert requested[0]['id']==['43:0']
    assert requested[0]['conversation_id']==['global_memory']


def test_history_pruning_keeps_an_entire_visible_collapsed_series(chat_browser):
    server, page, base = chat_browser
    before = [{'id': i, 'role': 'assistant', 'msg_type': 'agent_status', 'timestamp': i,
               'content': f'Agent 第 {i} 轮 · 1 个操作', 'history_cursor': str(i)} for i in range(1, 601)]
    group = commands(601, 48, run='window-run', group='window-group')
    dataset = before + group + [{'id': 745, 'role': 'assistant', 'msg_type': 'ai_reply', 'content': 'FINAL_REPLY',
        'timestamp': 745, 'history_cursor': '745', 'reply_group_id': 'window-group', 'run_id': 'window-run', 'reply_complete': True}]
    held = []
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        if 'before' in query:
            held.append(request)
            return
        rows = dataset[-200:]
        request.fulfill(json={'messages': rows, 'conversation_id': 'global_memory', 'ui_generation': 7,
            'next_cursor': str(rows[0]['id']), 'busy': False, 'live': server.outbox.snapshot()})
    page.route('**/api/workbench/history?*', route)
    page.goto(base);page.locator('.command-series-toggle').wait_for()
    ids = [str(row['id']) for row in group]
    page.locator('#log').evaluate('''log=>{
        const anchor=document.querySelector('[data-record-id="601"]');
        log.scrollTop=Math.max(0,anchor.offsetTop-log.clientHeight+120);
    }''')
    page.wait_for_function('document.getElementById("history-loading-state").getAttribute("aria-busy")==="true"')
    page.wait_for_timeout(40)
    current = held.pop(0)
    cursor = int(parse_qs(urlsplit(current.request.url).query)['before'][0])
    rows = [row for row in dataset if row['id'] < cursor][-50:]
    current.fulfill(json={'messages': rows, 'next_cursor': str(rows[0]['id']), 'conversation_id': 'global_memory', 'ui_generation': 7})
    page.locator('[data-record-id="' + str(rows[0]['id']) + '"]').wait_for(state='attached')
    page.wait_for_timeout(150)
    assert all(page.locator('[data-record-id="' + identifier + '"]').count() == 1 for identifier in ids)
    assert '48 轮' in page.locator('.command-series-toggle').first.inner_text()
    page.locator('.command-series-toggle').first.click()
    assert page.locator('[data-record-id="601"] .body').is_visible()
    assert page.locator('[data-record-id="742"] .body').is_visible()
    order=page.locator('#log>.msg-row').evaluate_all('(rows)=>rows.map(row=>Number(row.dataset.recordId))')
    assert order==sorted(order) and len(order)==len(set(order))
    anchor=page.locator('[data-record-id="601"]')
    anchor.evaluate("row=>row.scrollIntoView({block:'start'})")
    page.locator('#log').hover();page.mouse.wheel(0,360);page.wait_for_timeout(100)
    page.mouse.wheel(0,-180);page.wait_for_timeout(100)
    assert page.locator('[data-record-id="601"] .body').is_visible()
    assert page.locator('#log').evaluate('log=>log.scrollHeight>log.clientHeight')
