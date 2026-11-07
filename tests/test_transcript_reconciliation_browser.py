"""Durable message identities survive refresh, withdrawal and transport restarts."""
from copy import deepcopy
import pytest
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session


def test_restart_and_withdrawal_never_adopt_or_remove_another_saved_ai_reply(full_output_server):
    server=full_output_server[0]
    epoch=server.outbox.snapshot()['epoch']
    records=[{'id':1,'role':'user','msg_type':'user_text','content':'保留第一条输入','timestamp':1},
        {'id':2,'role':'assistant','msg_type':'ai_reply','content':'保留第一条 AI 回答','timestamp':2,
         'web_live':{'epoch':epoch,'message_ids':[101]}}]
    async def history(limit):return deepcopy(records)
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p)
        page=context.new_page();page.goto(base+'/#/chat?conversation=global_memory')
        page.get_by_text('保留第一条 AI 回答',exact=True).wait_for()
        # Logical transport IDs can restart at the same value after a service restart.
        server.outbox.put({'type':'history_reset'})
        new_epoch=server.outbox.snapshot()['epoch']
        records.extend([{'id':3,'role':'user','msg_type':'user_text','content':'第二条输入','timestamp':3},
            {'id':4,'role':'assistant','msg_type':'ai_reply','content':'第二条 AI 回答','timestamp':4,
             'web_live':{'epoch':new_epoch,'message_ids':[101]}}])
        page.get_by_text('第二条 AI 回答',exact=True).wait_for()
        assert page.locator('[data-record-id="2"] .body').inner_text()=='保留第一条 AI 回答'
        assert page.locator('[data-record-id="4"] .body').inner_text()=='第二条 AI 回答'
        # A resync after withdrawal must not replay old aliases over surviving records.
        records[:]=records[:2]
        server.outbox.put({'type':'context_reset','conversation_id':'global_memory'})
        page.locator('[data-record-id="4"]').wait_for(state='detached')
        assert page.locator('[data-record-id="2"] .body').inner_text()=='保留第一条 AI 回答'
        assert page.locator('.msg-row.ai').count()==1
        before=page.locator('#log').inner_text()
        page.reload();page.get_by_text('保留第一条 AI 回答',exact=True).wait_for()
        assert page.locator('#log').inner_text()==before
        browser.close()


def test_withdrawal_keeps_visual_replies_in_order_and_retains_the_preview_frame(full_output_server):
    server=full_output_server[0]
    records=[{'id':1,'role':'user','msg_type':'user_text','content':'第一条输入','timestamp':1},
        {'id':2,'role':'assistant','msg_type':'ai_reply','content':'带网页预览的回复','timestamp':2,
         'visual_page':{'version':2,'title':'保留预览','url':'/api/test-page','width':400,'height':120}},
        {'id':3,'role':'user','msg_type':'user_text','content':'第二条输入','timestamp':3},
        {'id':4,'role':'assistant','msg_type':'ai_reply','content':'普通回复','timestamp':4},
        {'id':5,'role':'user','msg_type':'user_text','content':'准备撤回的输入','timestamp':5,'conversation_actions':{'withdraw':True}},
        {'id':6,'role':'assistant','msg_type':'ai_reply','content':'准备撤回的回答','timestamp':6}]
    async def history(limit):return deepcopy(records)
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p)
        context.route('**/api/test-page',lambda route:route.fulfill(json={'version':2,'format':'html','source':'<button>页面按钮</button>','title':'保留预览','width':400,'height':120}))
        page=context.new_page();page.goto(base+'/#/chat?conversation=global_memory')
        page.locator('[data-record-id="2"] iframe').wait_for()
        page.evaluate('window.originalPreview=document.querySelector(`[data-record-id="2"] iframe`)')
        context.route('**/api/workbench/conversations/withdraw/preview',lambda route:route.fulfill(json={'can_withdraw':True,'message_count':2,'warnings':[],'turn_id':'last-turn','current_digest':'test'}))
        def withdraw(route):
            records[:]=records[:4]
            route.fulfill(json={'ok':True,'draft':{'text':'准备撤回的输入'}})
        context.route('**/api/workbench/conversations/withdraw',withdraw)
        page.locator('[data-record-id="5"]').get_by_role('button',name='撤回此消息及之后',exact=True).click()
        page.locator('#wb-dialog').get_by_role('button',name='确认撤回',exact=True).click()
        page.locator('[data-record-id="6"]').wait_for(state='detached')
        assert page.locator('#log>[data-record-id]').evaluate_all('rows=>rows.map(row=>Number(row.dataset.recordId))')==[1,2,3,4]
        assert page.evaluate('originalPreview===document.querySelector(`[data-record-id="2"] iframe`)&&originalPreview.isConnected')
        assert page.locator('[data-record-id="4"] .body').inner_text()=='普通回复'
        browser.close()
