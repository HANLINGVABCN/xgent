"""Draft previews use server URLs and keep real message actions after receipt."""
import json
from pathlib import Path
import sqlite3
import time

import pytest

from tests.test_workbench_browser import workspace_url, browser_context, ready  # noqa: F401
from tests.test_attachments import image_bytes
from tests.message_fixtures import typed_record


def test_withdraw_media_restores_previews_and_resends_without_file_upload(browser_context, workspace_url):
    base = workspace_url['url']
    response = browser_context.request.post(base + '/api/workbench/conversations/create', data={'name': '附件撤回重用'})
    assert response.ok
    cid = response.json()['current_chat_id']
    files = Path(workspace_url['database_path']).parent / 'xgent_storage' / 'uploads'
    files.mkdir(parents=True, exist_ok=True)
    inputs = [('reuse-photo.png', image_bytes(), 'image/png'),
              ('reuse-video.mp4', b'mocked-video-preview', 'video/mp4'), ('reuse-upload.txt', b'path-only input', 'text/plain')]
    refs = []
    for index, (name, raw, mime) in enumerate(inputs):
        (files / name).write_bytes(raw)
        refs.append({'version': 1, 'storage': 'uploads', 'path': name, 'name': name,
                     'size': len(raw), 'mime_type': mime, 'order': index})
    metadata = typed_record({'msg_type': 'user_file', 'role': 'user', 'metadata': {
        'attachments': refs[:2], 'server_uploads': refs[2:], 'file_ingress_mode': 'attachment',
        'web_file_message': {'version': 1, 'text': '保留原来的说明'}}})['metadata']
    with sqlite3.connect(workspace_url['database_path']) as conn:
        cursor = conn.execute("INSERT INTO global_messages(chat_id,user_id,msg_type,role,content,timestamp,session_id,metadata) VALUES(1,1,'user_file','user',?,?,?,?)",
                              ('保留原来的说明\nFILE_INDEX', time.time(), cid, json.dumps(metadata)))
        row_id = cursor.lastrowid
    page = browser_context.new_page()
    page.goto(base + '/#/chat?conversation=' + cid)
    page.wait_for_function('!document.getElementById("btn-send").disabled')
    row = page.locator(f'[data-record-id="{row_id}"]')
    row.wait_for()
    row.get_by_role('button', name='撤回此消息及之后', exact=True).click()
    page.get_by_role('button', name='确认撤回', exact=True).click()
    page.wait_for_function('document.querySelectorAll(".server-draft-file").length===3')
    assert page.locator('#input').input_value() == '保留原来的说明'
    pending = page.locator('#pending-files')
    assert pending.locator('img').count() == pending.locator('video').count() == 1
    assert pending.locator('img').get_attribute('src').startswith('/api/media/')
    assert pending.locator('video').get_attribute('src').startswith('/api/media/')
    assert '↑ 上传：reuse-upload.txt' in pending.inner_text()
    page.reload()
    page.wait_for_function('document.querySelectorAll(".server-draft-file").length===3')
    assert page.locator('#input').input_value() == '保留原来的说明'
    page.get_by_role('button', name='移除 reuse-video.mp4', exact=True).click()
    page.wait_for_function('document.querySelectorAll(".server-draft-file").length===2')
    requests = []
    page.route('**/api/chat', lambda route: (requests.append(route.request.post_data_json), route.fulfill(json={'ok': True})))
    uploads = []
    page.on('request', lambda request: uploads.append(request.url) if any(endpoint in request.url for endpoint in ('/api/attachments', '/api/server-uploads', '/api/file-transfers')) else None)
    page.locator('#btn-send').click()
    page.wait_for_function('document.querySelectorAll(".server-draft-file").length===0')
    assert len(requests) == 1 and requests[0]['conversation_id'] == cid
    assert requests[0]['text'] == '保留原来的说明'
    assert not uploads
    assert all((files / name).read_bytes() == raw for name, raw, _ in inputs)
    page.close()


def test_numeric_setting_failure_keeps_edit_and_message_draft(browser_context, workspace_url):
    page=browser_context.new_page();ready(page,workspace_url['url'])
    page.locator('#input').fill('消息草稿保留')
    page.get_by_role('button',name='生成选项',exact=True).click()
    page.get_by_role('button',name='Agent 轮数',exact=True).click()
    page.get_by_role('spinbutton',name='Agent 轮数',exact=True).fill('31')
    page.route('**/api/workbench/settings',lambda route:route.fulfill(status=503,json={'error':'保存未完成'}))
    page.locator('.composer-number-save').click()
    page.get_by_text('保存未完成',exact=True).wait_for()
    assert page.get_by_role('spinbutton',name='Agent 轮数',exact=True).input_value()=='31'
    assert page.locator('#input').input_value()=='消息草稿保留'
    page.close()


def test_ai_brand_avatar_and_name_have_requested_fixed_sizes(browser_context, workspace_url):
    page = browser_context.new_page()
    page.goto(workspace_url['url']+'/#/chat?conversation=global_memory')
    author = page.locator('.msg-row.ai .bubble-author:has([data-brand-name])').first
    author.wait_for()
    metrics = author.evaluate('''node=>{
      const icon=node.querySelector('[data-brand-logo]'),name=node.querySelector('[data-brand-name]');
      const i=icon.getBoundingClientRect(),n=name.getBoundingClientRect(),style=getComputedStyle(name);
      return {width:i.width,height:i.height,font:style.fontSize,weight:style.fontWeight,center:Math.abs((i.y+i.height/2)-(n.y+n.height/2))};
    }''')
    assert metrics['width'] == metrics['height'] == 24
    assert metrics['font'] == '15px' and int(metrics['weight']) >= 600
    assert metrics['center'] < 1
    page.close()
