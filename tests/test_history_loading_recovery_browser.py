"""Pending, truncated and timed-out reads keep the browser responsive and its anchor."""
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_history_prefetch_browser import history_browser, page_data, ready, remember_anchor, assert_anchor  # noqa: F401


@pytest.mark.parametrize('width', [390, 1440])
def test_slow_page_is_visible_and_can_be_replaced_without_moving_the_reader(history_browser, width, tmp_path):
    server, page, base = history_browser
    held, calls, errors = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_viewport_size({'width': width, 'height': 900})
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        if 'before' not in query:
            request.fulfill(json=page_data(server, 51, 101, next_cursor='51', baseline=True))
        else:
            calls.append(query['before'][0])
            if len(calls) == 1:
                held.append(request)
            else:
                request.fulfill(json=page_data(server, 1, 51))
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    page.locator('#input').fill('慢网络时仍能编辑的草稿')
    page.locator('#log').evaluate('log=>log.scrollTop=300')
    page.locator('#history-loading-state').wait_for(state='visible')
    assert page.locator('.history-loading-spinner').is_visible()
    anchor = remember_anchor(page)
    page.locator('#input').fill('加载时继续修改草稿')
    page.get_by_role('button', name='立即重试', exact=True).wait_for()
    assert_anchor(page, anchor)
    page.screenshot(path=str(tmp_path/f'history-slow-{width}.png'))
    page.get_by_role('button', name='立即重试', exact=True).click()
    page.locator('[data-record-id="1"]').wait_for(state='attached')
    assert_anchor(page, anchor)
    held[0].fulfill(json=page_data(server, 5001, 5051))
    page.wait_for_timeout(80)
    assert page.locator('[data-record-id="5001"]').count() == 0
    assert page.locator('#input').input_value() == '加载时继续修改草稿'
    assert page.locator('#history-loading-state').is_hidden()
    assert calls == ['51', '51']
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert errors == []


@pytest.mark.parametrize('failure', ['unavailable', 'truncated'])
def test_transient_or_partial_page_retries_the_same_cursor_and_preserves_the_window(history_browser, failure):
    server, page, base = history_browser
    calls, held = [], []
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        if 'before' not in query:
            request.fulfill(json=page_data(server, 51, 101, next_cursor='51', baseline=True))
        else:
            calls.append(query['before'][0])
            if len(calls) == 1:
                if failure == 'unavailable':
                    request.fulfill(status=503, json={'error': 'temporary network failure'})
                else:
                    request.fulfill(content_type='application/json', body='{"messages":[')
            else:
                held.append(request)
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    page.locator('#log').evaluate('log=>log.scrollTop=300')
    page.wait_for_function('document.querySelector("#history-loading-state").dataset.state==="retrying"')
    page.wait_for_timeout(700)
    assert calls == ['51', '51']
    page.locator('#log').evaluate('log=>log.scrollTop=180')
    anchor = remember_anchor(page)
    held[0].fulfill(json=page_data(server, 1, 51))
    page.locator('[data-record-id="1"]').wait_for(state='attached')
    assert_anchor(page, anchor)
    identifiers = page.locator('#log>.msg-row').evaluate_all('rows=>rows.map(row=>Number(row.dataset.recordId))')
    assert identifiers == list(range(1, 101))
    assert page.locator('#history-loading-state').is_hidden()


def test_hung_requests_expire_without_losing_cursor_and_manual_retry_recovers(history_browser):
    server, page, base = history_browser
    # 加速请求截止时间与重试退避，真实 fetch、取消和页面投递流程保持不变。
    page.add_init_script('''{
      const timer=window.setTimeout.bind(window);
      window.setTimeout=(fn,ms,...args)=>timer(fn,ms===12000?220:ms===600||ms===1400?40:ms,...args);
    }''')
    held, calls = [], []
    def route(request):
        query = parse_qs(urlsplit(request.request.url).query)
        if 'before' not in query:
            request.fulfill(json=page_data(server, 51, 101, next_cursor='51', baseline=True))
        else:
            calls.append(query['before'][0])
            if len(calls) <= 3:
                held.append(request)
            else:
                request.fulfill(json=page_data(server, 1, 51))
    page.route('**/api/workbench/history?*', route)
    ready(page, base)
    page.locator('#log').evaluate('log=>log.scrollTop=0')
    page.get_by_role('button', name='重试加载历史', exact=True).wait_for()
    anchor = remember_anchor(page)
    assert calls == ['51'] * 3
    page.get_by_role('button', name='重试加载历史', exact=True).click()
    page.locator('[data-record-id="1"]').wait_for(state='attached')
    assert_anchor(page, anchor)
    assert calls == ['51'] * 4
    for request in held:
        request.fulfill(json=page_data(server, 5001, 5051))
    page.wait_for_timeout(80)
    assert page.locator('[data-record-id="5001"]').count() == 0
    assert page.locator('#history-loading-state').is_hidden()
