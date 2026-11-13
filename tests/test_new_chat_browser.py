"""Real first sends create a conversation only after text or files are accepted."""
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from tests.test_workbench_browser import browser_context  # noqa: F401


@pytest.fixture(scope='module')
def workspace_url():
    root=Path(__file__).resolve().parents[1]
    process=subprocess.Popen([sys.executable,'-u',str(root/'tools/workbench_fixture.py'),'--messages','12','--new-chat-demo'],
        cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',
        env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHON_DOTENV_DISABLED':'1'})
    lines=queue.Queue()
    threading.Thread(target=lambda:[lines.put(line) for line in process.stdout],daemon=True).start()
    try:
        deadline=time.time()+45
        while time.time()<deadline:
            try:line=lines.get(timeout=1)
            except queue.Empty:continue
            try:data=json.loads(line)
            except ValueError:continue
            if isinstance(data,dict) and 'url' in data:
                yield data;return
        raise AssertionError('new chat fixture did not start')
    finally:
        process.terminate();process.wait(10)


def state(context,base):
    return context.request.get(base+'/api/workbench/conversations').json()


def ready(page,base,path='#/chat'):
    page.goto(base+'/'+path)
    page.wait_for_function('window.XGentConversations&&document.querySelector("#composer-model")?.disabled===false&&document.querySelector("#btn-send").disabled===false')


@pytest.mark.parametrize('width',[320,390,768,1440])
def test_new_button_and_invalid_links_show_blank_without_writing_or_exposing_old_context(browser_context,workspace_url,width,tmp_path):
    base=workspace_url['url'];before=state(browser_context,base)
    page=browser_context.new_page();page.set_viewport_size({'width':width,'height':950});requests=[];errors=[]
    page.on('request',lambda request:requests.append(request) if request.method=='POST' else None)
    page.on('pageerror',lambda error:errors.append(str(error)))
    ready(page,base,'#/chat?conversation=global_memory');page.locator('#log .msg-row').first.wait_for()
    page.locator('#input').fill('原对话独立草稿')
    if page.locator('#conversation-new').is_hidden():page.locator('#conversation-mobile-toggle').click()
    page.locator('#conversation-new').click()
    page.wait_for_function('location.hash==="#/chat"&&!window.XGentConversations.current&&!document.querySelector("#btn-send").disabled')
    assert page.locator('#log .msg-row').count()==0 and page.locator('#input').input_value()==''
    page.locator('#input').fill('新对话独立草稿')
    for path in ['#/chat','#/chat?conversation=deleted','#/chat?conversation=deleted&message=history:1']:
        ready(page,base,path)
        page.reload();page.wait_for_function('!document.querySelector("#btn-send").disabled')
        page.wait_for_function('location.hash==="#/chat"&&window.XGentConversations.current===null')
        assert page.locator('#log .msg-row').count()==0
        assert page.locator('#input').input_value()=='新对话独立草稿'
        assert page.locator('#empty-state').is_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(tmp_path/f'new-chat-{width}.png'))
    assert len(state(browser_context,base)['items'])==len(before['items'])
    assert not any('/conversations/create' in request.url for request in requests)
    assert not errors
    page.close()


def test_first_text_creates_one_conversation_and_url_then_reload_and_second_message_reuse_it(browser_context,workspace_url):
    base=workspace_url['url'];before=state(browser_context,base);page=browser_context.new_page()
    ready(page,base);assert page.url.endswith('#/chat')
    page.locator('#input').fill('首次消息，提交后才保存对话')
    with page.expect_response('**/api/chat') as response:page.locator('#btn-send').click()
    receipt=response.value.json();cid=receipt['conversation_id'];assert receipt['new_conversation']
    page.wait_for_function('(cid)=>window.XGentConversations.current===cid&&location.hash==="#/chat?conversation="+cid',arg=cid)
    page.locator('#log').get_by_text('隔离测试回复，已收到消息。',exact=True).wait_for()
    assert len(state(browser_context,base)['items'])==len(before['items'])+1
    assert state(browser_context,base)['telegram_conversation_id']==before['telegram_conversation_id']
    page.reload();page.locator('#log').get_by_text('首次消息，提交后才保存对话',exact=True).wait_for()
    page.wait_for_function('!document.querySelector("#btn-send").disabled')
    page.locator('#input').fill('第二条仍在同一对话')
    with page.expect_response('**/api/chat'):page.locator('#btn-send').click()
    page.locator('#log').get_by_text('第二条仍在同一对话',exact=True).wait_for()
    assert len(state(browser_context,base)['items'])==len(before['items'])+1
    assert page.url.endswith('#/chat?conversation='+cid)
    with sqlite3.connect(workspace_url['database_path']) as conn:
        assert conn.execute("SELECT COUNT(*) FROM global_messages WHERE session_id=? AND msg_type='user_text'",(cid,)).fetchone()[0]==2
    page.close()


def test_invalid_link_waits_for_delayed_list_and_returns_blank_without_history_error(browser_context,workspace_url):
    base=workspace_url['url'];before=state(browser_context,base);page=browser_context.new_page();held=[]
    page.route('**/api/workbench/conversations',lambda route:held.append(route))
    page.goto(base+'/#/chat?conversation=missing-on-first-load')
    page.wait_for_timeout(400)
    assert held
    assert '历史加载失败' not in page.locator('#toast').text_content()
    for route in held:route.fulfill(json=before)
    page.wait_for_function('location.hash==="#/chat"&&window.XGentConversations.current===null&&!document.querySelector("#btn-send").disabled')
    assert page.locator('#log .msg-row').count()==0
    assert '历史加载失败' not in page.locator('#toast').text_content()
    assert len(state(browser_context,base)['items'])==len(before['items'])
    page.close()


@pytest.mark.parametrize('chunked',[False,True])
@pytest.mark.parametrize('mode',['attachment','server_upload'])
def test_first_attachment_waits_for_durable_admission_and_preserves_original_file(browser_context,workspace_url,chunked,mode):
    base=workspace_url['url'];before=state(browser_context,base);page=browser_context.new_page();ready(page,base)
    history_reads=[]
    page.on('request',lambda request:history_reads.append(request.url) if '/api/workbench/history?' in request.url else None)
    raw=(b'CHUNKED ORIGINAL FILE\x00'*500000) if chunked else b'FIRST ATTACHMENT COMPLETE TEXT\nALL BYTES'
    name='first.bin' if chunked else 'first.txt'
    page.locator('#file-input' if mode=='attachment' else '#server-upload-input').set_input_files({'name':name,'mimeType':'application/octet-stream' if chunked else 'text/plain','buffer':raw})
    assert len(state(browser_context,base)['items'])==len(before['items'])
    assert page.url.endswith('#/chat')
    page.locator('#input').fill('首条带附件的说明');page.locator('#btn-send').click()
    page.wait_for_function('!!window.XGentConversations.current&&document.querySelector("#input").value===""',timeout=60000)
    cid=page.evaluate('window.XGentConversations.current')
    page.locator('#log').get_by_text('隔离测试回复，已收到消息。',exact=True).wait_for()
    assert len(state(browser_context,base)['items'])==len(before['items'])+1
    with sqlite3.connect(workspace_url['database_path']) as conn:
        row=conn.execute("SELECT metadata FROM global_messages WHERE session_id=? AND msg_type=?",(cid,'user_file' if mode=='attachment' else 'user_text')).fetchone()
        metadata=json.loads(row[0]);ref=metadata['attachments' if mode=='attachment' else 'server_uploads'][0]
        assert metadata['web_file_message']['text']=='首条带附件的说明'
        original=Path(workspace_url['database_path']).parent/'xgent_storage/uploads'/ref['path']
        assert original.read_bytes()==raw
    assert page.url.endswith('#/chat?conversation='+cid)
    assert history_reads==[], 'First upload admission must continue its existing view, without reading an entire history window'
    page.close()


def test_first_upload_replays_messages_received_before_http_ack_without_loading_history(browser_context,workspace_url):
    base=workspace_url['url'];page=browser_context.new_page();ready(page,base)
    held,history_reads=[],[]
    def delay(route):held.append((route,route.fetch()))
    page.route('**/api/attachments',delay)
    page.on('request',lambda request:history_reads.append(request.url) if '/api/workbench/history?' in request.url else None)
    page.locator('#file-input').set_input_files({'name':'original.txt','mimeType':'text/plain','buffer':b'Complete original file'})
    page.locator('#input').fill('确认晚到时也直接接上已有消息');page.locator('#btn-send').click()
    row=page.locator('#log>.msg-row.user');row.wait_for()
    row.evaluate('row=>window.originalUpload=row')
    page.wait_for_timeout(400)
    assert held and history_reads==[]
    assert page.url.endswith('#/chat')
    route,response=held[0];route.fulfill(response=response)
    page.locator('#log').get_by_text('隔离测试回复，已收到消息。',exact=True).wait_for()
    assert row.evaluate('row=>row===window.originalUpload')
    assert page.locator('#log>.msg-row.user').count()==1
    assert history_reads==[]
    page.close()


def test_lost_first_receipt_keeps_draft_and_reloaded_retry_does_not_duplicate_conversation(browser_context,workspace_url):
    base=workspace_url['url'];before=state(browser_context,base);page=browser_context.new_page();ready(page,base)
    receipts=[]
    def lose(route):
        response=route.fetch();receipts.append(response.json());route.abort()
    page.route('**/api/chat',lose)
    text='响应丢失后继续用同一发送标识';page.locator('#input').fill(text);page.locator('#btn-send').click()
    page.wait_for_function('document.querySelector("#toast").textContent.includes("内容已保留")')
    assert page.url.endswith('#/chat') and page.locator('#input').input_value()==text
    assert len(state(browser_context,base)['items'])==len(before['items'])+1
    page.unroute('**/api/chat');page.reload();page.wait_for_function('!document.querySelector("#btn-send").disabled')
    assert page.locator('#input').input_value()==text
    page.locator('#btn-send').click()
    page.wait_for_function('(cid)=>window.XGentConversations.current===cid',arg=receipts[0]['conversation_id'])
    page.locator('#log').get_by_text('隔离测试回复，已收到消息。',exact=True).wait_for()
    assert len(state(browser_context,base)['items'])==len(before['items'])+1
    page.close()


def test_old_list_and_sync_snapshot_cannot_replace_successfully_saved_new_conversation(browser_context,workspace_url):
    base=workspace_url['url'];before=state(browser_context,base);page=browser_context.new_page();ready(page,base)
    held=[]
    def delay_first(route):
        if not held:held.append((route,route.fetch().json()))
        else:route.continue_()
    page.route('**/api/workbench/conversations',delay_first)
    page.evaluate('()=>{window.XGentConversations.refresh();}')
    page.wait_for_timeout(200);assert held
    page.locator('#input').fill('不能被早发出的列表回执覆盖')
    with page.expect_response('**/api/chat') as response:page.locator('#btn-send').click()
    receipt=response.value.json();cid=receipt['conversation_id']
    assert receipt['conversation_revision']>held[0][1]['revision']
    page.wait_for_function('(cid)=>window.XGentConversations.current===cid',arg=cid)
    route,old=held[0];route.fulfill(json=old)
    page.evaluate('old=>window.XGentConversations.accept(old)',old)
    page.wait_for_timeout(100)
    assert page.evaluate('window.XGentConversations.current')==cid
    assert page.url.endswith('#/chat?conversation='+cid)
    assert len(state(browser_context,base)['items'])==len(before['items'])+1
    page.close()


def test_two_blank_tabs_first_send_group_and_late_receipt_preserve_local_selection(browser_context,workspace_url):
    base=workspace_url['url'];before=state(browser_context,base)
    created=browser_context.request.post(base+'/api/workbench/conversation-groups/create',data={'revision':before['revision'],'name':'空白页发送的目标分组'})
    assert created.ok;group=created.json()['group_id']
    first,second=browser_context.new_page(),browser_context.new_page()
    ready(first,base);ready(second,base)
    first.locator('#input').fill('第一标签页的独立草稿')
    second.locator('#conversation-group-select').select_option(group)
    second.locator('#input').fill('第二标签页首次发送')
    held=[]
    def delay(route):held.append((route,route.fetch()))
    second.route('**/api/chat',delay);second.locator('#btn-send').click()
    second.wait_for_function('document.querySelector("#btn-send").disabled')
    second.wait_for_timeout(150)
    assert held
    # The accepted result must not navigate a reader who already switched away.
    second.locator('#conversation-group-select').select_option('ungrouped')
    second.locator('.conv-row[data-conversation-id=global_memory] .conv-open').click()
    second.wait_for_function('window.XGentConversations.current==="global_memory"')
    route,response=held[0];cid=response.json()['conversation_id'];route.fulfill(response=response)
    second.wait_for_function('!document.querySelector("#btn-send").disabled')
    assert second.evaluate('window.XGentConversations.current')=='global_memory'
    assert first.evaluate('window.XGentConversations.current') is None
    assert first.locator('#input').input_value()=='第一标签页的独立草稿'
    saved=state(browser_context,base)
    assert len(saved['items'])==len(before['items'])+1
    assert next(item for item in saved['items'] if item['id']==cid)['group_id']==group
    first.close();second.close()


def test_failed_first_send_keeps_blank_url_and_draft_without_saving_empty_conversation(browser_context,workspace_url):
    base=workspace_url['url'];before=state(browser_context,base);page=browser_context.new_page();ready(page,base)
    page.route('**/api/chat',lambda route:route.fulfill(status=503,json={'error':'隔离测试：保存暂时失败'}))
    text='创建失败时留在输入框的消息';page.locator('#input').fill(text);page.locator('#btn-send').click()
    page.get_by_text('隔离测试：保存暂时失败；内容已保留，可重试发送。',exact=True).wait_for()
    assert page.url.endswith('#/chat') and page.locator('#input').input_value()==text
    assert len(state(browser_context,base)['items'])==len(before['items'])
    page.unroute('**/api/chat');page.locator('#btn-send').click()
    page.wait_for_function('!!window.XGentConversations.current')
    assert len(state(browser_context,base)['items'])==len(before['items'])+1
    page.close()


def test_settings_task_can_choose_saved_source_without_creating_blank_conversation(browser_context,workspace_url):
    base=workspace_url['url'];before=state(browser_context,base);page=browser_context.new_page();ready(page,base)
    page.locator('#input').fill('仍未发送的新对话草稿')
    page.evaluate('location.hash="/tasks"');page.get_by_role('button',name='创建任务',exact=True).first.click()
    dialog=page.locator('#wb-dialog')
    dialog.locator('[name=conversation_id]').select_option('global_memory')
    dialog.locator('[name=task]').fill('空白页创建的来源明确的任务')
    dialog.locator('[name=command]').fill('echo isolated-task-not-run')
    dialog.locator('[name=expression]').fill('1d')
    with page.expect_response('**/api/workbench/tasks/create') as response:
        dialog.get_by_role('button',name='确认创建任务',exact=True).click()
    assert response.value.ok,response.value.text()
    page.wait_for_function('!document.querySelector("#wb-dialog").open')
    tasks=browser_context.request.get(base+'/api/workbench/tasks').json()['items']
    assert next(item for item in tasks if item['summary']=='空白页创建的来源明确的任务')['conversation_id']=='global_memory'
    assert len(state(browser_context,base)['items'])==len(before['items'])
    page.locator('.wb-brand').click();page.wait_for_function('location.hash==="#/chat"&&!document.querySelector("#btn-send").disabled')
    assert page.evaluate('window.XGentConversations.current') is None
    assert page.locator('#input').input_value()=='仍未发送的新对话草稿'
    page.close()


def test_deleted_saved_target_does_not_navigate_away_from_settings(browser_context,workspace_url):
    base=workspace_url['url'];page=browser_context.new_page()
    created=browser_context.request.post(base+'/api/workbench/conversations/create',data={'name':'设置中的已删除来源'}).json()
    cid=created['conversation_id'];ready(page,base,'#/chat?conversation='+cid)
    page.locator('#workspace-settings').click();page.locator('.wb-settings-nav').wait_for()
    deleted=browser_context.request.post(base+'/api/workbench/conversations/delete',data={'id':cid,'confirm':True})
    assert deleted.ok,deleted.text()
    page.evaluate('window.XGentConversations.refresh()')
    assert page.url.endswith('#/settings')
    assert page.evaluate('window.XGentConversations.current') is None
    page.locator('.wb-brand').click();page.wait_for_function('location.hash==="#/chat"&&!document.querySelector("#btn-send").disabled')
    assert page.locator('#log .msg-row').count()==0
    page.close()


def test_first_command_and_settings_refresh_preserve_the_saved_conversation(browser_context,workspace_url):
    base=workspace_url['url'];before=state(browser_context,base);page=browser_context.new_page();ready(page,base)
    page.locator('#input').fill('/start')
    with page.expect_response('**/api/chat') as response:page.locator('#btn-send').click()
    receipt=response.value.json();assert receipt['management'] and receipt['new_conversation']
    cid=receipt['conversation_id'];page.wait_for_function('(cid)=>window.XGentConversations.current===cid',arg=cid)
    assert len(state(browser_context,base)['items'])==len(before['items'])+1
    page.locator('#input').fill('设置刷新仍保留已创建对话的草稿')
    page.locator('#workspace-settings').click();page.wait_for_function('document.body.dataset.page==="settings"')
    page.reload();page.locator('.wb-settings-nav').wait_for();page.locator('.wb-brand').click()
    page.wait_for_function('(cid)=>window.XGentConversations.current===cid&&document.body.dataset.page==="chat"',arg=cid)
    page.wait_for_function('!document.querySelector("#btn-send").disabled')
    assert page.locator('#input').input_value()=='设置刷新仍保留已创建对话的草稿'
    assert page.url.endswith('#/chat?conversation='+cid)
    page.close()
