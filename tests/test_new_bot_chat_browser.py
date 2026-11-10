"""Blank Bot selection, first send and cross-client adoption in isolated data."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import pytest

from tests.test_database_write_lock import _load_db_class
from tests.test_new_chat_browser import ready, state
from tests.test_workbench_browser import browser_context  # noqa: F401


@pytest.fixture(scope='module')
def workspace_url():
    root=Path(__file__).resolve().parents[1]
    process=subprocess.Popen([sys.executable,'-u',str(root/'tools/workbench_fixture.py'),
        '--messages','12','--new-chat-demo','--version-demo'],cwd=root,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',
        env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHON_DOTENV_DISABLED':'1'})
    lines=queue.Queue()
    threading.Thread(target=lambda:[lines.put(line) for line in process.stdout],daemon=True).start()
    try:
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            try:line=lines.get(timeout=1)
            except queue.Empty:continue
            try:data=json.loads(line)
            except ValueError:continue
            if isinstance(data,dict) and 'url' in data:
                yield data;return
        raise AssertionError('Bot draft fixture did not start')
    finally:
        process.terminate();process.wait(10)


@pytest.mark.parametrize('width',[390,1440])
def test_temporary_list_row_selects_bot_then_refresh_removes_only_the_row(browser_context,workspace_url,width,tmp_path):
    base=workspace_url['url'];before=state(browser_context,base)
    page=browser_context.new_page();page.set_viewport_size({'width':width,'height':900})
    ready(page,base)
    if page.locator('#conversation-new').is_hidden():page.locator('#conversation-mobile-toggle').click()
    page.locator('#conversation-new').click()
    page.wait_for_function('document.activeElement===document.querySelector("#input")')
    if width<768 and not page.evaluate('document.body.classList.contains("conv-drawer-open")'):
        page.locator('#conversation-mobile-toggle').click()
    page.locator('.conv-draft-row .conv-more').click()
    with page.expect_response('**/conversations/set_bot') as selected:
        page.get_by_role('menuitem',name='🤖 设为 Bot 当前对话',exact=True).click()
    assert selected.value.ok
    page.locator('.conv-draft-row .conv-bot-badge').wait_for(state='visible')
    assert page.url.endswith('#/chat') and page.evaluate('window.XGentConversations.current') is None
    assert len(state(browser_context,base)['items'])==len(before['items'])
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(tmp_path/f'new-bot-draft-{width}.png'))
    page.reload();page.wait_for_function('window.XGentConversations&&document.querySelector("#btn-send").disabled===false')
    assert page.locator('.conv-draft-row').count()==0
    page.locator('#input').fill('首条消息才创建 Bot 对话')
    with page.expect_response('**/api/chat') as sent:page.locator('#btn-send').click()
    cid=sent.value.json()['conversation_id']
    page.wait_for_function('(id)=>window.XGentConversations.current===id',arg=cid)
    page.locator('#log').get_by_text('隔离测试回复，已收到消息。',exact=True).wait_for()
    current=state(browser_context,base)
    assert current['telegram_conversation_id']==cid
    assert len(current['items'])==len(before['items'])+1
    assert page.url.endswith('#/chat?conversation='+cid)
    page.close()


def test_native_first_message_adopts_matching_draft_without_erasing_web_input(browser_context,workspace_url):
    base=workspace_url['url'];page=browser_context.new_page();ready(page,base)
    page.locator('#conversation-new').click();page.locator('.conv-draft-row .conv-more').click()
    with page.expect_response('**/conversations/set_bot'):page.get_by_role('menuitem',name='🤖 设为 Bot 当前对话',exact=True).click()
    page.locator('.conv-draft-row .conv-bot-badge').wait_for(state='visible')
    token=page.evaluate('window.XGentConversations.newToken')
    page.locator('#input').fill('尚未发送的网页草稿')
    async def materialize():
        db=_load_db_class()(workspace_url['database_path'])
        try:return await db.materialize_bot_new_conversation(token)
        finally:await db.close()
    with ThreadPoolExecutor(max_workers=1) as worker:
        cid=worker.submit(lambda:asyncio.run(materialize())).result(timeout=20)
    page.wait_for_function('(id)=>window.XGentConversations.current===id',arg=cid)
    assert page.locator('#input').input_value()=='尚未发送的网页草稿'
    assert page.url.endswith('#/chat?conversation='+cid)
    page.close()


def test_selected_bot_draft_keeps_group_after_refresh_and_first_send(browser_context,workspace_url):
    base=workspace_url['url'];current=state(browser_context,base)
    response=browser_context.request.post(base+'/api/workbench/conversation-groups/create',
        data={'name':'刷新后保留草稿分组','revision':current['revision']})
    assert response.ok
    gid=response.json()['group_id']
    page=browser_context.new_page();ready(page,base)
    page.locator('#conversation-group-select').select_option(gid)
    page.locator('#conversation-new').click();page.locator('.conv-draft-row .conv-more').click()
    with page.expect_response('**/conversations/set_bot'):page.get_by_role('menuitem',name='🤖 设为 Bot 当前对话',exact=True).click()
    page.reload();ready(page,base)
    assert page.locator('.conv-draft-row').count()==0
    assert page.evaluate('window.XGentConversations.newGroup')==gid
    page.locator('#input').fill('刷新后在原分组发送首条消息')
    with page.expect_response('**/api/chat') as sent:page.locator('#btn-send').click()
    cid=sent.value.json()['conversation_id']
    page.wait_for_function('(id)=>window.XGentConversations.current===id',arg=cid)
    assert page.locator('#conversation-group-select').input_value()==gid
    assert next(item for item in state(browser_context,base)['items'] if item['id']==cid)['group_id']==gid
    page.close()
