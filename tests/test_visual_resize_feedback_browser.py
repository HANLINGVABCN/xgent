"""Responsive cards retain their design width across gutters and repeated state changes."""
import json
from pathlib import Path

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.web_display import build_web_display


SOURCE = '''<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0}
body{display:flex;justify-content:center;align-items:center;min-height:100vh;padding:12px;font-family:system-ui}
main{width:100%;max-width:480px;position:relative;padding:20px 18px 22px;overflow:hidden;background:#182443;border-radius:20px;color:white;text-align:center}
.labels,.steps,.actions{display:flex;justify-content:space-between;gap:10px}
.labels span,.steps span{padding:4px 10px;font-size:12px;border:1px solid #89a;border-radius:8px}
h1{font-size:20px;margin:10px 0 5px}p{font-size:13px;min-height:20px;margin-bottom:12px}
.stage{width:100%;height:250px;position:relative;overflow:hidden}
svg{width:100%;height:100%}
.steps{margin-bottom:12px}
button{font-size:15px;padding:12px 18px;border:0;border-radius:12px;background:#975ccd;color:white}
#action{flex:1}#replay{display:none}#replay.show{display:block}
.particle{position:absolute;animation:burst 1s forwards;pointer-events:none}
@keyframes burst{to{transform:translate(80px,-60px);opacity:0}}
</style></head><body><main id="card">
<div class="labels"><span>左侧角色</span><span>待确认状态</span><span>右侧角色</span></div>
<h1>自适应互动页面</h1><p id="status">初始说明</p>
<div class="stage"><svg viewBox="0 0 460 255"><circle id="drawing" cx="230" cy="128" r="90" fill="#9ac"/></svg></div>
<div class="steps"><span>第一步</span><span>第二步</span><span>第三步</span></div>
<div class="actions"><button id="action">完成互动</button><button id="replay">再看一次</button></div>
</main><script>
window.executions=(window.executions||0)+1;window.clicks=0;
document.getElementById('action').addEventListener('pointerdown',()=>{
 window.clicks++;document.getElementById('status').textContent='状态已经改变，这里展示更长的结果说明，并且继续保留所有操作和完整内容。';
 document.getElementById('action').textContent='互动已经完成，点击另一按钮可以重新开始';document.getElementById('replay').classList.add('show');
 const p=document.createElement('span');p.className='particle';p.textContent='✨';document.querySelector('.stage').append(p);setTimeout(()=>p.remove(),1000);
});
document.getElementById('replay').addEventListener('pointerdown',()=>{
 document.getElementById('status').textContent='初始说明';document.getElementById('action').textContent='完成互动';document.getElementById('replay').classList.remove('show');
});
</script></body></html>'''


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('scenario', ['initial-gutter', 'late-gutter', 'source-hidden', 'corrupt-saved-size'])
def test_repeated_interactions_do_not_narrow_and_reset_recovers_canvas(full_output_server, width, scenario, tmp_path):
    server = full_output_server[0]
    gutter = 'html{overflow-y:scroll;scrollbar-gutter:stable both-edges}html::-webkit-scrollbar{width:17px}'
    source = SOURCE.replace('<style>', '<style>'+gutter, 1) if scenario == 'initial-gutter' else SOURCE
    raw = '```xgent-html 完整互动\n'+source+'\n```'
    record = {'id': 720, 'role': 'assistant', 'msg_type': 'ai_reply', 'content': raw,
              'timestamp': 1, 'conversation_id': 'global_memory', 'web_display': build_web_display(raw)}

    async def history(limit):
        return [record]
    server.config.read_history = history
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        if scenario == 'corrupt-saved-size':
            context.add_init_script('if(location.protocol==="http:")localStorage.setItem("xgent-visual-sizes",JSON.stringify({"global_memory:720:0":{width:220,logicalWidth:64,logicalHeight:1967}}))')
        page = context.new_page()
        page.set_viewport_size({'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(base+'/#/chat?conversation=global_memory')
        card = page.locator('.visual-page')
        frame = card.locator('.visual-page-frame').content_frame
        frame.locator('#action').wait_for()
        page.wait_for_function('document.querySelector(".visual-page").getAttribute("aria-busy")==="false"')

        def settle():
            page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))))')

        def canvas():
            return frame.locator('body').evaluate('()=>{const r=document.getElementById("card").getBoundingClientRect();return {width:r.width,height:r.height,left:r.left,right:r.right,top:r.top,bottom:r.bottom,viewportWidth:innerWidth,viewportHeight:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight};}')

        settle()
        before = canvas()
        assert before['width'] > 350, before
        frame.locator('#action').evaluate('node=>window.originalAction=node')
        if scenario == 'late-gutter':
            frame.locator('head').evaluate('node=>{const style=document.createElement("style");style.textContent="html{overflow-y:scroll!important;scrollbar-gutter:stable both-edges!important}html::-webkit-scrollbar{width:17px!important}";node.append(style);}')
        if scenario == 'source-hidden':
            card.get_by_role('button', name='源码', exact=True).click()
            page.wait_for_timeout(100)
            card.get_by_role('button', name='预览', exact=True).click()
            page.locator('#log').evaluate('node=>node.style.display="none"')
            page.wait_for_timeout(100)
            page.locator('#log').evaluate('node=>node.style.display=""')
        card.get_by_role('button', name='展开页面', exact=True).click()
        settle()
        samples = []
        for _ in range(30):
            frame.locator('#action').dispatch_event('pointerdown')
            settle()
            samples.append(canvas())
            frame.locator('#replay').dispatch_event('pointerdown')
            settle()
            samples.append(canvas())
        assert all(abs(value['width']-before['width']) <= 2 for value in samples), samples[-3:]
        assert all(value['scrollHeight'] <= value['viewportHeight']+1 for value in samples), samples[-3:]
        assert all(value['bottom'] <= value['viewportHeight']+1 for value in samples), samples[-3:]
        assert frame.locator('#action').evaluate('node=>node===window.originalAction')
        assert frame.locator('body').evaluate('()=>window.executions===1&&window.clicks===30')
        card.get_by_role('button', name='关闭页面', exact=True).click()
        settle()
        grip = card.get_by_role('button', name='拖拽等比例调整页面大小', exact=True)
        grip.focus()
        page.keyboard.press('ArrowLeft')
        settle()
        assert canvas()['width'] == before['width']
        card.get_by_role('button', name='恢复自动大小', exact=True).click()
        settle()
        assert canvas()['width'] > 350
        assert frame.locator('#action').evaluate('node=>node===window.originalAction')
        assert frame.locator('body').evaluate('()=>window.executions===1&&window.clicks===30')
        page.screenshot(path=str(tmp_path/f'repeat-{width}-{scenario}.png'))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.reload()
        page.locator('.visual-page-ready').wait_for()
        settle()
        assert canvas()['width'] > 350
        assert canvas()['scrollHeight'] <= canvas()['viewportHeight']+1
        assert not errors
        browser.close()
