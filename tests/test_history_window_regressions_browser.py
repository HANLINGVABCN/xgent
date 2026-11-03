"""Keep the reader's actual history window across paging and transport recovery."""
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_chat_failure_regressions_browser import commands
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_history_prefetch_browser import history_browser, page_data, ready, remember_anchor, assert_anchor  # noqa: F401


def test_expanded_series_stays_open_when_earlier_pages_extend_the_same_run(history_browser):
    server, page, base = history_browser
    group = commands(101, 160, run='long-run', group='long-group')
    for row in group:
        row['conversation_id'] = 'A'
    data = group + [{'id': 581, 'record_id': 581, 'role': 'assistant', 'msg_type': 'ai_reply',
        'timestamp': 581, 'content': '真实最终回复', 'history_cursor': '581',
        'reply_group_id': 'long-group', 'run_id': 'long-run', 'reply_complete': True}]
    held = []
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        if 'before' in query:
            held.append(request)
        else:
            rows = data[-200:]
            request.fulfill(json={'messages': rows, 'conversation_id': 'A', 'ui_generation': 7,
                'next_cursor': str(rows[0]['id']), 'busy': False, 'live': server.outbox.snapshot()})
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    page.locator('.command-series-toggle').wait_for()
    first = page.locator('.command-series-anchor').get_attribute('data-record-id')
    page.locator('.command-series-toggle').click()
    assert page.locator(f'[data-record-id="{first}"] .body').is_visible()
    page.locator('#log').evaluate('(log)=>log.scrollTop=0')
    page.wait_for_function('document.getElementById("history-loading-state").getAttribute("aria-busy")==="true"')
    anchor = remember_anchor(page)
    request = held.pop(0)
    cursor = int(parse_qs(urlsplit(request.request.url).query)['before'][0])
    rows = [row for row in data if row['id'] < cursor][-50:]
    request.fulfill(json={'messages': rows, 'conversation_id': 'A', 'ui_generation': 7,
        'next_cursor': str(rows[0]['id']), 'last_cursor': str(rows[-1]['id'])})
    page.locator(f'[data-record-id="{rows[0]["id"]}"]').wait_for(state='attached')
    page.wait_for_timeout(80)
    assert page.locator(f'[data-record-id="{first}"] .body').is_visible()
    assert page.locator('.command-series-control.series-open').count() == 1
    assert_anchor(page, anchor)
    ids = page.locator('#log>.msg-row[data-record-id]').evaluate_all('(rows)=>rows.map(row=>Number(row.dataset.recordId))')
    assert ids == sorted(set(ids))
    for _ in range(2):
        page.locator('#log').evaluate('(log)=>log.scrollTop=0')
        page.wait_for_function('document.getElementById("history-loading-state").getAttribute("aria-busy")==="true"')
        request = held.pop(0)
        cursor = int(parse_qs(urlsplit(request.request.url).query)['before'][0])
        rows = [row for row in data if row['id'] < cursor][-50:]
        request.fulfill(json={'messages': rows, 'conversation_id': 'A', 'ui_generation': 7,
            'next_cursor': str(rows[0]['id']), 'last_cursor': str(rows[-1]['id'])})
        page.locator(f'[data-record-id="{rows[0]["id"]}"]').wait_for(state='attached')
        page.wait_for_timeout(60)
        assert page.locator(f'[data-record-id="{first}"] .body').is_visible()
        assert page.locator('.command-series-control.series-open').count() == 1


def paging_corpus():
    data = []
    for index in range(40):
        start = len(data) + 1
        data.append({'id': start, 'role': 'user', 'msg_type': 'user_text',
            'content': f'第 {index + 1} 次实际请求', 'timestamp': start, 'history_cursor': str(start), 'conversation_id': 'A'})
        group = commands(start + 1, 8, run=f'run-{index}', group=f'group-{index}')
        for row in group:
            row['conversation_id'] = 'A'
        data.extend(group)
        identifier = len(data) + 1
        data.append({'id': identifier, 'role': 'assistant', 'msg_type': 'ai_reply', 'timestamp': identifier,
            'content': f'第 {index + 1} 次真实最终回复', 'history_cursor': str(identifier), 'conversation_id': 'A',
            'reply_group_id': f'group-{index}', 'run_id': f'run-{index}', 'reply_complete': True})
    return data


def serve_corpus(server, data, query):
    baseline = not any(key in query for key in ('before', 'after'))
    if 'anchor' in query:
        target = int(query['anchor'][0].split(':')[1])
        rows = data[max(0, target - 25):target + 25]
    elif 'before' in query:
        rows = [row for row in data if row['id'] < int(query['before'][0])][-50:]
    elif 'after' in query:
        rows = [row for row in data if row['id'] > int(query['after'][0])][:50]
    else:
        rows = data[-50:]
    first, last = (rows[0]['id'], rows[-1]['id']) if rows else (0, 0)
    more = last < len(data) if 'after' in query else first > 1
    return {'messages': rows, 'conversation_id': 'A', 'ui_generation': 7, 'busy': False,
        'first_cursor': str(first), 'last_cursor': str(last),
        'next_cursor': str(last if 'after' in query else first) if more else None,
        **({'live': server.outbox.snapshot()} if baseline else {}),
        **({'before': {'cursor': str(first), 'has_more': first > 1},
            'after': {'cursor': str(last), 'has_more': last < len(data)}} if 'anchor' in query else {})}


@pytest.mark.parametrize('mobile', [False, True])
def test_repeated_scroll_and_expansion_keep_a_contiguous_history_window(history_browser, mobile):
    server, page, base = history_browser
    corpus = paging_corpus()
    errors, pages = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        pages.append(query)
        request.fulfill(json=serve_corpus(server, corpus, query))
    page.route('**/api/workbench/history?*', route)
    if mobile:
        page.set_viewport_size({'width': 390, 'height': 844})
    ready(page, base)
    page.locator('.command-series-toggle').first.wait_for()
    initial = int(page.locator('#log>.msg-row[data-record-id]').first.get_attribute('data-record-id'))
    for index in range(20):
        page.locator('#log').hover()
        page.mouse.wheel(0, -900)
        page.wait_for_timeout(60)
        toggle = page.locator('.command-series-toggle:visible')
        if index % 4 == 0:
            on_screen = toggle.evaluate_all('nodes=>nodes.findIndex(node=>{const b=node.getBoundingClientRect(),l=document.getElementById("log").getBoundingClientRect();return b.top>=l.top&&b.bottom<=l.bottom;})')
            if on_screen >= 0:
                toggle.nth(on_screen).click()
        if index % 3 == 0:
            page.mouse.wheel(0, 500)
            page.wait_for_timeout(50)
            page.mouse.wheel(0, -700)
        page.wait_for_timeout(80)
        ids = page.locator('#log>.msg-row[data-record-id]').evaluate_all('(rows)=>rows.map(row=>Number(row.dataset.recordId))')
        assert ids == list(range(ids[0], ids[-1] + 1)), (index, ids)
        assert page.locator('#log').evaluate('log=>log.scrollHeight>log.clientHeight')
    assert int(page.locator('#log>.msg-row[data-record-id]').first.get_attribute('data-record-id')) < initial
    assert any('before' in query for query in pages)
    assert errors == []


def test_reconnect_with_newer_messages_keeps_the_reading_range_and_expanded_blocks(history_browser):
    server, page, base = history_browser
    corpus, requests = paging_corpus(), []
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        requests.append(query)
        request.fulfill(json=serve_corpus(server, corpus, query))
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    page.evaluate('window.XGentChat.locate("history:320")')
    page.locator('[data-record-id="320"]').wait_for()
    assert page.locator('[data-record-id="320"] .body').is_visible()
    page.locator('[data-record-id="320"]').evaluate('row=>row.scrollIntoView({block:"start"})')
    page.wait_for_timeout(80)
    anchor = remember_anchor(page)
    protected_ids = page.locator('#log>.msg-row[data-record-id]').evaluate_all('''rows=>{
        const viewport=document.getElementById('log').getBoundingClientRect();
        const expanded=new Set(Array.from(document.querySelectorAll('.command-series-control.series-open'),
            control=>control.closest('.msg-row').dataset.replyGroupId));
        return rows.filter(row=>{const b=row.getBoundingClientRect();return expanded.has(row.dataset.replyGroupId)||
            b.height>0&&b.bottom>viewport.top&&b.top<viewport.bottom;}).map(row=>Number(row.dataset.recordId));
    }''')
    with server.outbox._changed:
        server.outbox._epoch = 'b' * 32
        server.outbox._changed.notify_all()
    server.outbox.put({'type': 'message', 'conversation_id': 'A', 'message_id': 99901,
                      'msg_type': 'ai_reply', 'text': '远处的新回复正在生成', 'run_id': 'latest-run'})
    page.wait_for_function('!document.getElementById("btn-send").disabled')
    page.wait_for_timeout(200)
    assert any(query.get('anchor') for query in requests[2:])
    current_ids = page.locator('#log>.msg-row[data-record-id]').evaluate_all('(rows)=>rows.map(row=>Number(row.dataset.recordId))')
    assert all(identifier in current_ids for identifier in protected_ids), (protected_ids, current_ids, anchor)
    ids = page.locator('#log>.msg-row[data-record-id]').evaluate_all('(rows)=>rows.map(row=>Number(row.dataset.recordId))')
    assert ids == list(range(ids[0], ids[-1] + 1))
    assert page.get_by_text('远处的新回复正在生成', exact=True).count() == 0
    assert page.locator('.command-series-control.series-open').count() >= 1
    assert_anchor(page, anchor)


def test_transport_resync_does_not_replace_the_history_being_read(history_browser):
    server, page, base = history_browser
    held, baselines = [], []
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        if 'before' in query:
            held.append(request)
        else:
            baselines.append(query)
            request.fulfill(json=page_data(server, 401, 451, baseline=True, next_cursor='401'))
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    for expected in (351, 301):
        page.locator('#log').evaluate('(log)=>log.scrollTop=300')
        page.wait_for_function('document.getElementById("history-loading-state").getAttribute("aria-busy")==="true"')
        request = held.pop(0)
        cursor = int(parse_qs(urlsplit(request.request.url).query)['before'][0])
        assert cursor == expected + 50
        request.fulfill(json=page_data(server, expected, expected + 50, next_cursor=str(expected)))
        page.locator(f'[data-record-id="{expected}"]').wait_for(state='attached')
    page.locator('[data-record-id="320"]').evaluate('row=>row.scrollIntoView({block:"start"})')
    anchor = remember_anchor(page)
    old_ids = page.locator('#log>.msg-row[data-record-id]').evaluate_all('(rows)=>rows.map(row=>Number(row.dataset.recordId))')
    # Recover a lost transport epoch while the database generation stays the same.
    with server.outbox._changed:
        server.outbox._epoch = 'a' * 32
        server.outbox._changed.notify_all()
    server.outbox.put({'type': 'notice', 'conversation_id': 'A', 'message_id': 99001, 'text': '重连后的动态'})
    page.wait_for_function('!document.getElementById("btn-send").disabled')
    page.wait_for_timeout(200)
    assert len(baselines) >= 2
    assert all(page.locator(f'[data-record-id="{identifier}"]').count() == 1 for identifier in old_ids)
    assert_anchor(page, anchor)


def test_deleted_reading_anchor_recovers_to_current_history_without_retaining_stale_rows(history_browser):
    server, page, base = history_browser
    replaced, requests = False, []
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        requests.append(query)
        if replaced and 'anchor' in query:
            request.fulfill(status=404, json={'error': '原消息已撤回'})
        else:
            start = 801 if replaced else 301
            data = page_data(server, start, start + 50, baseline=True)
            if replaced:
                data['ui_generation'] = 8
            request.fulfill(json=data)
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    page.locator('[data-record-id="320"]').evaluate('row=>row.scrollIntoView({block:"start"})')
    replaced = True
    with server.outbox._changed:
        server.outbox._epoch = 'c' * 32
        server.outbox._changed.notify_all()
    server.outbox.put({'type': 'notice', 'conversation_id': 'A', 'message_id': 99902, 'text': '新历史'})
    page.locator('[data-record-id="801"]').wait_for(state='attached')
    assert any('anchor' in query for query in requests)
    assert page.locator('[data-record-id="320"]').count() == 0
    assert page.locator('#log>.msg-row[data-record-id]').count() == 50


def failed_sequence():
    from xgent_app.web_display import build_operation_display
    group = commands(101, 13, run='failed-history-run', group='failed-history-group')
    for row in group:
        row['conversation_id'] = 'A'
        if row['msg_type'] == 'agent_result':
            text = '\n'.join(f'实际输出第 {line} 行' for line in range(50))
            row['content'] = row['text'] = text
            row['web_display'] = build_operation_display({'success': True, 'output': text}, 'folded')
    error = {'id': 140, 'record_id': 140, 'timestamp': 140, 'history_cursor': '140', 'conversation_id': 'A',
        'role': 'assistant', 'msg_type': 'runtime_error', 'model_error': True,
        'content': '⚠️ ConnectError: [Errno -2] Name or service not known',
        'run_id': 'failed-history-run', 'reply_group_id': 'failed-history-group', 'reply_complete': True,
        'ai_generation': {'provider': 'fixture-provider', 'model': 'fixture-model', 'generated_at': 140}}
    return group + [error]


def test_failed_command_sequence_shows_one_author_and_keeps_literal_error(history_browser):
    server, page, base = history_browser
    data = failed_sequence()
    def route(request):
        request.fulfill(json={'messages': data, 'conversation_id': 'A', 'ui_generation': 7,
            'busy': False, 'live': server.outbox.snapshot()})
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    page.locator('.command-series-toggle').wait_for()
    assert page.locator('.bubble-header:visible', has_text='XGent').count() == 1
    error = page.locator('[data-record-id="140"]')
    assert error.locator('.body').inner_text() == data[-1]['content']
    assert error.locator('.code-block-wrap').count() == 0
    page.locator('.command-series-toggle').click()
    assert page.locator('.bubble-header:visible', has_text='XGent').count() == 1
    page.reload()
    error.wait_for()
    assert error.locator('.body').inner_text() == data[-1]['content']
    assert page.locator('.bubble-header:visible', has_text='XGent').count() == 1


@pytest.mark.parametrize('mobile', [False, True])
def test_expanding_old_failed_sequence_keeps_the_clicked_position_on_screen(history_browser, mobile):
    server, page, base = history_browser
    before = [dict(record, conversation_id='A') for record in page_data(server, 1, 101)['messages']]
    after = [dict(record, conversation_id='A') for record in page_data(server, 141, 201)['messages']]
    data = before + failed_sequence() + after
    def route(request):
        request.fulfill(json={'messages': data, 'conversation_id': 'A', 'ui_generation': 7,
            'busy': False, 'live': server.outbox.snapshot()})
    page.route('**/api/workbench/history?*', route)
    if mobile:
        page.set_viewport_size({'width': 390, 'height': 844})
    ready(page, base)
    toggle = page.locator('.command-series-toggle')
    toggle.wait_for()
    page.locator('#log').evaluate('''log=>{
        const control=document.querySelector('.command-series-control');
        const top=control.getBoundingClientRect().top-log.getBoundingClientRect().top+log.scrollTop;
        log.scrollTop=top-140;
    }''')
    page.wait_for_timeout(80)
    top = toggle.bounding_box()['y']
    toggle.click()
    page.wait_for_timeout(180)
    control = page.locator('.command-series-control')
    assert abs(control.bounding_box()['y'] - top) < 3
    first = page.locator('[data-record-id="101"] .body').bounding_box()
    viewport = page.locator('#log').bounding_box()
    assert first['y'] >= viewport['y'] and first['y'] < viewport['y'] + viewport['height']
    assert page.locator('[data-record-id="140"] .body').inner_text() == failed_sequence()[-1]['content']


def test_expansion_during_pending_page_keeps_all_loaded_history_and_the_error(history_browser):
    server, page, base = history_browser
    before = [dict(row, conversation_id='A', msg_type='agent_status') for row in page_data(server, 1, 301)['messages']]
    group = failed_sequence()
    for row in group:
        row['id'] += 200
        row['record_id'] = row['id']
        row['timestamp'] = row['id']
        row['history_cursor'] = str(row['id'])
    after = [dict(row, conversation_id='A') for row in page_data(server, 341, 601)['messages']]
    data, held = before + group + after, []
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        if 'before' in query:
            held.append(request)
        else:
            request.fulfill(json=serve_corpus(server, data, query))
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    page.evaluate('window.XGentChat.locate("history:340")')
    page.locator('[data-record-id="340"]').wait_for()
    def pending_page():
        cursor = page.locator('#log>[data-history-cursor]').first.get_attribute('data-history-cursor')
        request = next(item for item in held if parse_qs(urlsplit(item.request.url).query)['before'][0] == cursor)
        held.remove(request)
        return request
    for _ in range(3):
        page.locator('#log').evaluate('log=>log.scrollTop=0')
        page.locator('#log').hover()
        page.mouse.wheel(0, -80)
        page.wait_for_function('document.getElementById("history-loading-state").getAttribute("aria-busy")==="true"')
        request = pending_page()
        query = parse_qs(urlsplit(request.request.url).query)
        chunk = serve_corpus(server, data, query)
        request.fulfill(json=chunk)
        page.locator(f'[data-record-id="{chunk["messages"][0]["id"]}"]').wait_for(state='attached')
        page.wait_for_timeout(40)
    original_ids = page.locator('#log>.msg-row[data-record-id]').evaluate_all('rows=>rows.map(row=>Number(row.dataset.recordId))')
    assert len(original_ids) >= 200
    page.locator('#log').evaluate('log=>log.scrollTop=0')
    page.locator('#log').hover()
    page.mouse.wheel(0, -80)
    page.wait_for_function('document.getElementById("history-loading-state").getAttribute("aria-busy")==="true"')
    request = pending_page()
    toggle = page.locator('.command-series-toggle')
    toggle.evaluate('node=>node.scrollIntoView({block:"center"})')
    top = toggle.bounding_box()['y']
    toggle.click()
    request.fulfill(json=serve_corpus(server, data, parse_qs(urlsplit(request.request.url).query)))
    page.wait_for_timeout(180)
    current_ids = page.locator('#log>.msg-row[data-record-id]').evaluate_all('rows=>rows.map(row=>Number(row.dataset.recordId))')
    assert set(original_ids) <= set(current_ids), sorted(set(original_ids) - set(current_ids))
    assert current_ids == list(range(current_ids[0], current_ids[-1] + 1))
    assert page.locator('.command-series-control.series-open').count() == 1
    assert abs(page.locator('.command-series-control').bounding_box()['y'] - top) < 3
    assert page.locator('[data-record-id="340"] .body').inner_text() == group[-1]['content']


@pytest.mark.parametrize('gesture', ['wheel', 'touch', 'keyboard'])
def test_user_can_load_older_records_when_the_current_content_fits_the_screen(history_browser, gesture):
    server, page, base = history_browser
    held = []
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        if 'before' in query:
            held.append(request)
        else:
            request.fulfill(json=page_data(server, 51, 52, baseline=True, next_cursor='51'))
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    assert page.locator('#log>.msg-row').count() == 1
    assert page.locator('#log').evaluate('log=>log.scrollTop===0')
    if gesture == 'wheel':
        page.locator('#log').hover()
        page.mouse.wheel(0, -80)
    elif gesture == 'touch':
        page.locator('#log').evaluate('''log=>{
            const touch=y=>new Touch({identifier:1,target:log,clientX:30,clientY:y});
            log.dispatchEvent(new TouchEvent('touchstart',{touches:[touch(200)]}));
            log.dispatchEvent(new TouchEvent('touchmove',{touches:[touch(300)]}));
            log.dispatchEvent(new TouchEvent('touchend',{touches:[]}));
        }''')
    else:
        page.locator('#log').evaluate('log=>{log.tabIndex=0;log.focus({preventScroll:true});}')
        page.keyboard.press('ArrowUp')
    page.wait_for_function('document.getElementById("history-loading-state").getAttribute("aria-busy")==="true"')
    assert len(held) == 1
    held[0].fulfill(json=page_data(server, 1, 51))
    page.locator('[data-record-id="1"]').wait_for(state='attached')
    assert page.locator('[data-record-id="51"]').count() == 1
