"""Live stopped replies use the same persisted presentation as browser reload."""
import pytest
from tests.test_thinking_params import run_in_app
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session


@pytest.mark.parametrize('style',['foreground','background','nonstream'])
def test_stopped_reply_and_code_are_identical_live_and_after_refresh(full_output_server,tmp_path,style):
    case=run_in_app('import asyncio\nfrom tests.stopped_reply_probe import exercise\n'+f'print(json.dumps(asyncio.run(exercise(bot,{str(tmp_path)!r},{style!r}))))')
    server=full_output_server[0];records=[]
    async def history(limit):return records
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p)
        page=context.new_page();page.goto(base+'/#/chat?conversation=global_memory')
        page.wait_for_function('!document.getElementById("btn-send").disabled')
        epoch=server.outbox.snapshot()['epoch']
        for frame in case['frames']:
            if frame.get('web_live'):frame={**frame,'web_live':{**frame['web_live'],'epoch':epoch}}
            server.outbox.put(frame)
        row=page.locator('[data-record-id="'+str(case['reply_id'])+'"]');row.wait_for()
        page.locator('.stop-notice').wait_for()
        assert page.locator('.msg-row.ai').count()==1
        assert page.locator('.bubble.ai').get_by_role('button',name='❌ 停止回答',exact=True).count()==0
        before=row.locator('.body').inner_html()
        records.extend(case['history']);page.reload();row.wait_for()
        assert row.locator('.body').inner_html()==before
        assert page.locator('.msg-row.ai').count()==1 and page.locator('.stop-notice').count()==1
        if style!='nonstream':assert row.locator('.code-block-wrap pre').is_visible()
        browser.close()
