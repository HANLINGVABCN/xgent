"""Generation/execution stop controls stay below the same reply's footer."""
from copy import deepcopy
import pytest
from xgent_app.web_display import web_block_html
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session


@pytest.mark.parametrize('width',[390,1440])
def test_stop_placement_survives_command_attachment_markup_refresh_and_phase_switch(full_output_server,width):
    server=full_output_server[0];records=[]
    async def history(limit):return deepcopy(records)
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p);page=context.new_page();page.set_viewport_size({'width':width,'height':950})
        page.goto(base+'/#/chat?conversation=global_memory');page.wait_for_function('!document.getElementById("btn-send").disabled')
        def stop(phase):return [[{'text':'停止回答','callback_data':'act_stop_generation:run-one:'+phase}]]
        reply={'record_id':501,'message_id':8001,'conversation_id':'global_memory','run_id':'run-one','msg_type':'ai_reply',
            'role':'assistant','timestamp':1,'text':'执行命令。','reply_markup':stop('generation'),
            'web_display':{'version':1,'segments':[{'kind':'html','text':web_block_html('echo first',protocol='run-x',state='running',command_key='call:first')},
                {'kind':'html','text':web_block_html('echo second',protocol='run-x',state='pending',command_key='call:second')},
                {'kind':'html','footer':True,'text':'<i>用量信息始终在停止按钮上方</i>'}]}}
        server.outbox.put({**reply,'type':'message'})
        owner=page.locator('[data-record-id="501"]');owner.wait_for()
        def assert_position(phase):
            button=owner.get_by_role('button',name='❌ 停止回答',exact=True);button.wait_for()
            assert button.get_attribute('data-stop-phase')==phase
            assert owner.locator('.body [data-stop-generation]').count()==0
            assert owner.locator('.reply-run-controls').count()==1
            assert button.bounding_box()['y']>=owner.locator('.message-footer').bounding_box()['y']+owner.locator('.message-footer').bounding_box()['height']
            assert owner.evaluate('row=>row.querySelector(".reply-run-controls")===row.querySelector(".bubble").lastElementChild')
        assert_position('generation')
        server.outbox.put({'type':'edit_markup','message_id':8001,'record_id':501,'conversation_id':'global_memory','run_id':'run-one','reply_markup':None})
        result={'record_id':502,'message_id':8002,'conversation_id':'global_memory','run_id':'run-one','msg_type':'agent_result',
            'role':'assistant','timestamp':2,'text':'','reply_markup':stop('execution-first'),
            'command_result':{'version':1,'key':'call:first','kind':'run','command':'echo first','reply_record_id':501,'state':'running'}}
        server.outbox.put({**result,'type':'message'})
        page.locator('[data-record-id="502"].command-result-attached').wait_for(state='attached');assert_position('execution-first')
        # Reading the input block must never move or hide its stop control.
        owner.get_by_role('button',name='展开命令与输出',exact=True).first.click()
        owner.get_by_role('button',name='收起命令与输出',exact=True).first.click();assert_position('execution-first')
        changed=deepcopy(reply);changed['web_display']['segments'].insert(0,{'kind':'markdown','text':'流式补充正文。'})
        changed.pop('reply_markup');server.outbox.put({**changed,'type':'edit'})
        owner.get_by_text('流式补充正文。',exact=True).wait_for();assert_position('execution-first')
        # Result markup-only updates retain binding and return to the same host.
        server.outbox.put({'type':'edit_markup','message_id':8002,'conversation_id':'global_memory','run_id':'run-one','reply_markup':stop('execution-updated')})
        page.wait_for_function('document.querySelector("[data-stop-phase=execution-updated]")!==null');assert_position('execution-updated')
        # The next operation owns its own phase, while the visual position stays.
        server.outbox.put({'type':'edit_markup','message_id':8002,'conversation_id':'global_memory','run_id':'run-one','reply_markup':None})
        second=deepcopy(result);second.update(record_id=503,message_id=8003,reply_markup=stop('execution-second'))
        second['command_result'].update(key='call:second',command='echo second')
        server.outbox.put({**second,'type':'message'});assert_position('execution-second')
        records.extend([{**changed,'id':501,'content':'执行命令。'},{**result,'id':502,'reply_markup':None},{**second,'id':503}])
        page.reload();owner.wait_for();assert_position('execution-second')
        stops=[]
        context.route('**/api/stop',lambda route:(stops.append(route.request.post_data_json),route.fulfill(json={'ok':True})))
        owner.get_by_role('button',name='❌ 停止回答',exact=True).click()
        assert stops==[{'conversation_id':'global_memory','run_id':'run-one','phase_ref':'execution-second'}]
        server.outbox.put({'type':'edit_markup','message_id':8003,'conversation_id':'global_memory','run_id':'run-one','reply_markup':None})
        page.wait_for_function('document.querySelectorAll("[data-stop-generation]").length===0')
        browser.close()
