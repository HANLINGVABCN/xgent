"""Live source appends preserve selection and never redraw the hidden preview."""
from pathlib import Path
import pytest
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.web_display import build_web_display


@pytest.mark.parametrize('format',['svg','html'])
@pytest.mark.parametrize('width',[390,1440])
def test_live_source_stays_current_without_replacing_text_or_rendering_hidden_page(full_output_server,tmp_path,format,width):
    server=full_output_server[0]
    async def history(limit):return []
    server.config.read_history=history
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser,context,base=browser_session(server,p)
        page=context.new_page();page.set_viewport_size({'width':width,'height':950})
        page.goto(base+'/#/chat?conversation=global_memory');page.wait_for_function('!document.getElementById("btn-send").disabled')
        def emit(source,closed=False):
            raw='正文。\n```xgent-'+format+' 流式源码\n'+source+('\n```\n' if closed else '')
            server.outbox.put({'type':'edit','message_id':999,'text':'页面生成中','msg_type':'ai_reply',
                'web_display':build_web_display(raw,hide_unclosed=True,reply_message_id=999)})
        source=('<svg viewBox="0 0 500 300"><rect id="keep" width="500" height="300" fill="purple"/>' if format=='svg' else
                '<style>main{color:purple}</style><main id="keep">开始</main>')
        source+='\n'+''.join('<!-- 初始行 '+str(i)+' '+('x'*90)+' -->\n' for i in range(500))
        emit(source)
        card=page.locator('.visual-page');frame=card.locator('.visual-page-frame').content_frame
        frame.locator('#keep').wait_for()
        card.get_by_role('button',name='源码',exact=True).click()
        code=card.locator('.visual-page-source code');assert code.text_content()==source
        # Finish an already queued preview paint before measuring source-only updates.
        page.wait_for_timeout(150)
        page.evaluate('''()=>{
            const source=document.querySelector('.visual-page-source'),text=source.querySelector('code').firstChild;
            window.sourceNode=text;source.scrollTop=170;source.scrollLeft=12;
            window.sourcePosition=[source.scrollTop,source.scrollLeft];
            const range=document.createRange();range.setStart(text,3);range.setEnd(text,12);getSelection().removeAllRanges();getSelection().addRange(range);
            window.selectedCode=getSelection().toString();window.bodyRebuilds=0;window.hiddenPaints=0;
            new MutationObserver(events=>window.bodyRebuilds+=events.length).observe(source.closest('.body'),{childList:true});
            window.addEventListener('message',event=>{if(event.data?.type==='xgent-visual-painted')window.hiddenPaints++;});
        }''')
        for index in range(16):
            source+='<!-- 追加源码 '+str(index)+' '+('z'*3000)+' -->\n'
            emit(source);page.wait_for_timeout(10)
        page.wait_for_function('text=>document.querySelector(".visual-page-source code").textContent===text',arg=source)
        assert page.evaluate('sourceNode===document.querySelector(".visual-page-source code").firstChild')
        assert page.evaluate('getSelection().toString()===selectedCode')
        assert page.evaluate('sourcePosition.every((value,i)=>value===[document.querySelector(".visual-page-source").scrollTop,document.querySelector(".visual-page-source").scrollLeft][i])')
        assert page.evaluate('bodyRebuilds===0&&hiddenPaints===0')
        page.evaluate('getSelection().removeAllRanges();const source=document.querySelector(".visual-page-source");source.scrollTop=source.scrollHeight')
        source+='<!-- 最新尾行 -->\n';emit(source)
        page.wait_for_function('text=>document.querySelector(".visual-page-source code").textContent===text',arg=source)
        page.wait_for_function('(()=>{const node=document.querySelector(".visual-page-source");return node.scrollHeight-node.scrollTop-node.clientHeight<4;})()')
        source+=('<circle id="tail" cx="80" cy="80" r="40"/><script>window.doneRuns=1;</script></svg>' if format=='svg' else
                 '<p id="tail">完整页面</p><script>window.doneRuns=1;</script>')
        emit(source,closed=True)
        page.wait_for_function('text=>document.querySelector(".visual-page-source code").textContent===text',arg=source+'\n')
        assert page.evaluate('hiddenPaints===0') and card.locator('iframe').count()==1
        assert frame.locator('body').evaluate('()=>window.doneRuns===undefined')
        page.screenshot(path=str(tmp_path/f'live-source-{format}-{width}.png'))
        card.get_by_role('button',name='预览',exact=True).click()
        frame.locator('#tail').wait_for()
        assert frame.locator('body').evaluate('()=>window.doneRuns===1')
        assert '生成中' not in card.inner_text()
        browser.close()
