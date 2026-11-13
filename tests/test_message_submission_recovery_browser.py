"""Visible local sends survive stale snapshots and queue-to-history handoff."""
import io
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_attachments import image_bytes
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_history_prefetch_browser import history_browser, ready  # noqa: F401
from xgent_app.file_ingress import read_multipart


@pytest.fixture
def submission_browser(history_browser):
    server, page, base = history_browser
    state = {'records': [], 'items': [], 'revision': 1}
    async def queue(action, cid, data):
        return {'conversation_id': cid, 'generation': 7, 'revision': state['revision'], 'items': state['items']}
    async def accept(*args, **kwargs):
        raise AssertionError('This fixture must not call a model or enqueue a real input')
    server.config.queue_api, server.config.accept_text = queue, accept
    def history(route):
        query = parse_qs(urlsplit(route.request.url).query)
        cid = query.get('conversation_id', ['A'])[0]
        route.fulfill(json={'messages': state['records'] if cid == 'A' else [],
            'conversation_id': cid, 'ui_generation': 7, 'queue_enabled': True, 'next_cursor': None,
            'busy': False, 'live': {**server.outbox.snapshot(), 'frames': []}})
    page.route('**/api/workbench/history?*', history)
    return server, page, base, state


def saved_message(text, identifier=501, **extra):
    return {'id': identifier, 'record_id': identifier, 'role': 'user', 'msg_type': 'user_text',
        'content': text, 'text': text, 'conversation_id': 'A', 'ui_generation': 7,
        'timestamp': 1794499200, 'history_cursor': str(identifier), **extra}


@pytest.mark.parametrize('width', [390, 1440])
def test_text_appears_before_ack_and_survives_snapshot_with_exact_identity(submission_browser, width, tmp_path):
    server, page, base, state = submission_browser
    page.set_viewport_size({'width': width, 'height': 900})
    held, payloads = [], []
    page.route('**/api/chat', lambda route: (payloads.append(route.request.post_data_json), held.append(route)))
    ready(page, base)
    text = '慢网络下也要立刻出现的文字\n第二行保留'
    page.locator('#input').fill(text);page.locator('#btn-send').click()
    row = page.locator('#log>.msg-row.user')
    row.wait_for();assert row.locator('.body').inner_text() == text
    row.evaluate('row=>window.sentRow=row')
    page.evaluate('()=>window.XGentChat.reload()')
    assert row.evaluate('row=>row===window.sentRow')
    assert row.locator('.body').inner_text() == text
    page.locator('#input').fill('发送中另写的新草稿')
    row.locator('.message-send-state').filter(has_text='正在确认发送').wait_for()
    page.screenshot(path=str(tmp_path/f'pending-message-{width}.png'))
    request_id = payloads[0]['request_id']
    message = saved_message(text, web_request_id=request_id, queue_id='queued-text')
    state['records'].append(message)
    server.outbox.put({**message, 'type': 'record_snapshot'})
    page.locator('[data-record-id="501"]').wait_for()
    assert row.evaluate('row=>row===window.sentRow')
    assert page.locator('#log>.msg-row.user').count() == 1
    held[0].fulfill(json={'ok': True, 'queued': True, 'id': 'queued-text', 'conversation_id': 'A', 'generation': 7})
    page.wait_for_function('!document.getElementById("btn-send").disabled')
    assert row.locator('.message-send-state').count() == 0
    assert page.locator('#input').input_value() == '发送中另写的新草稿'
    assert len(payloads) == 1


def test_queue_handoff_never_drops_the_local_bubble(submission_browser):
    server, page, base, state = submission_browser
    payloads = []
    def submit(route):
        payloads.append(route.request.post_data_json)
        item = {'id': 'queued-text', 'conversation_id': 'A', 'generation': 7, 'revision': 1, 'origin': 'web',
            'seq': 1, 'text': payloads[-1]['text'], 'status': 'pending', 'reason': 'waiting'}
        state['items'] = [item]
        route.fulfill(json={'ok': True, 'queued': True, **item})
    page.route('**/api/chat', submit)
    ready(page, base)
    text = '从队列接入对话时不能消失'
    page.locator('#input').fill(text);page.locator('#btn-send').click()
    page.locator('.queue-item').wait_for()
    assert page.locator('.queue-preview p').inner_text() == text
    state['items'] = [];state['revision'] += 1
    server.outbox.put({'type': 'queue_state', 'conversation_id': 'A'})
    row = page.locator('#log>.msg-row.user');row.wait_for(state='visible')
    assert row.locator('.body').inner_text() == text
    page.evaluate('()=>window.XGentChat.reload()')
    assert row.locator('.body').inner_text() == text
    message = saved_message(text, queue_id='queued-text', web_request_id=payloads[0]['request_id'])
    state['records'].append(message);server.outbox.put({**message, 'type': 'record_snapshot'})
    page.locator('[data-record-id="501"]').wait_for()
    assert page.locator('#log>.msg-row.user').count() == 1
    assert row.locator('.message-send-state').count() == 0


def test_identical_texts_adopt_their_own_receipt_even_when_sync_arrives_out_of_order(submission_browser):
    server, page, base, state = submission_browser
    payloads = []
    def submit(route):
        payloads.append(route.request.post_data_json)
        route.fulfill(json={'ok': True, 'queued': True, 'id': 'queue-'+str(len(payloads)),
                            'conversation_id': 'A', 'generation': 7})
    page.route('**/api/chat', submit)
    ready(page, base)
    for _ in range(2):
        page.locator('#input').fill('重复的内容也应该是两条独立消息');page.locator('#btn-send').click()
        page.wait_for_function('!document.getElementById("btn-send").disabled&&document.getElementById("input").value===""')
    rows = page.locator('#log>.msg-row.user')
    assert rows.count() == 2
    rows.evaluate_all('rows=>window.originalMessages=rows')
    for index in (1, 0):
        message = saved_message(payloads[index]['text'], 501+index, web_request_id=payloads[index]['request_id'], queue_id='queue-'+str(index+1))
        state['records'].append(message);server.outbox.put({**message, 'type': 'record_snapshot'})
        page.locator('[data-record-id="'+str(501+index)+'"]').wait_for()
    assert rows.evaluate_all('rows=>rows.every((row,index)=>row===window.originalMessages[index]&&row.dataset.recordId===String(501+index))')
    assert rows.count() == 2


def test_failed_text_retry_reuses_request_and_bubble_without_erasing_new_draft(submission_browser):
    server, page, base, state = submission_browser
    requests = []
    def submit(route):
        payload = route.request.post_data_json;requests.append(payload)
        if len(requests) == 1:
            route.abort()
        else:
            state['records'].append(saved_message(payload['text'], web_request_id=payload['request_id']))
            route.fulfill(json={'ok': True, 'queued': True, 'id': 'queued-text', 'conversation_id': 'A', 'generation': 7})
    page.route('**/api/chat', submit)
    ready(page, base)
    page.locator('#input').fill('确认丢失后按同一标识重试');page.locator('#btn-send').click()
    row = page.locator('#log>.msg-row.user')
    row.get_by_role('button', name='重试发送此消息').wait_for()
    row.evaluate('row=>window.sentRow=row')
    page.locator('#input').fill('重试时也保留这个新草稿')
    row.get_by_role('button', name='重试发送此消息').click()
    page.wait_for_function('!document.getElementById("btn-send").disabled')
    page.evaluate('()=>window.XGentChat.reload()')
    assert requests[0]['request_id'] == requests[1]['request_id']
    assert row.evaluate('row=>row===window.sentRow')
    assert page.locator('#log>.msg-row.user').count() == 1
    assert page.locator('#input').input_value() == '重试时也保留这个新草稿'


def test_image_preview_survives_pending_ack_and_stale_history(submission_browser, tmp_path):
    server, page, base, state = submission_browser
    held, uploads = [], []
    def upload(route):
        request = route.request
        data = read_multipart(io.BytesIO(request.post_data_buffer), len(request.post_data_buffer),
                              request.headers['content-type'], tmp_path)
        uploads.append({'text': data['text'], 'key': data['idempotency_key']});data['_temporary'].cleanup();held.append(route)
    page.route('**/api/attachments', upload)
    ready(page, base)
    page.locator('#file-input').set_input_files({'name': 'neutral.png', 'mimeType': 'image/png', 'buffer': image_bytes()})
    page.locator('#input').fill('图片说明始终留在原消息里');page.locator('#btn-send').click()
    row = page.locator('#log>.msg-row.user');row.locator('.media-img').wait_for()
    page.wait_for_function('document.querySelector("#log .media-img").complete')
    row.evaluate('row=>{window.sentRow=row;window.sentImage=row.querySelector(".media-img");}')
    page.evaluate('()=>window.XGentChat.reload()')
    assert row.evaluate('row=>row===window.sentRow&&row.querySelector(".media-img")===window.sentImage')
    assert row.locator('.body').inner_text() == uploads[0]['text']
    # 实时连接断开时，独立的上传请求与原图片仍然保留。
    page.evaluate('window.dispatchEvent(new Event("offline"))')
    assert row.locator('.media-img').is_visible()
    assert row.evaluate('row=>row.querySelector(".media-img")===window.sentImage')
    held[0].fulfill(status=503, json={'error': 'temporary upload failure'})
    row.get_by_role('button', name='重试发送此消息').wait_for()
    assert page.locator('.pending-file').count() == 1
    assert row.locator('.media-img').is_visible()
    assert row.evaluate('row=>row.querySelector(".media-img")===window.sentImage')
