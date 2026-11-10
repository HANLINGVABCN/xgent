"""Decorative fixed particles must not turn a fitted HTML card into a clipped page."""
from pathlib import Path

import pytest

from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.web_display import build_web_display


SOURCE_PATH = Path(__file__).parent / 'fixtures' / 'visual-pages' / 'birthday-floating-effects.html'


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('effect_position', ['fixed', 'absolute'])
def test_floating_particles_preserve_fitted_page_and_complete_bottom_controls(full_output_server, width, effect_position, tmp_path):
    source = SOURCE_PATH.read_text(encoding='utf-8')
    source = source.replace('position: fixed;', 'position: ' + effect_position + ';')
    raw = '```xgent-html 生辰蛋糕与心愿卡\n' + source + '\n```'
    record = {'id': 851, 'role': 'assistant', 'msg_type': 'ai_reply', 'content': raw,
              'timestamp': 1, 'conversation_id': 'global_memory', 'web_display': build_web_display(raw)}
    server = full_output_server[0]
    async def history(limit):
        return [record]
    server.config.read_history = history
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        page = context.new_page()
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(base + '/#/chat?conversation=global_memory')
        card = page.locator('.visual-page')
        frame = card.locator('.visual-page-frame').content_frame
        frame.locator('.heart-particle').first.wait_for(state='attached')
        page.locator('.visual-page-ready').wait_for()

        def metrics():
            return frame.locator('body').evaluate('''() => {
                const root = document.documentElement, content = document.querySelector('.container'),
                    bounds = content.getBoundingClientRect(), button = document.querySelector('#wishBtn'),
                    tip = document.querySelector('#wishTip');
                return {width: innerWidth, height: innerHeight, scrollWidth: root.scrollWidth,
                    scrollHeight: root.scrollHeight, left: bounds.left, right: bounds.right,
                    top: bounds.top, bottom: bounds.bottom, compact: root.hasAttribute('data-xgent-card'),
                    overflowX: getComputedStyle(root).overflowX, overflowY: getComputedStyle(root).overflowY,
                    buttonBottom: button.getClientRects().length ? button.getBoundingClientRect().bottom : null,
                    tipBottom: tip.getClientRects().length ? tip.getBoundingClientRect().bottom : null};
            }''')

        def fits():
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve))))')
            value = metrics()
            assert value['compact'], value
            assert value['left'] >= -1 and value['right'] <= value['width'] + 1, value
            assert value['top'] >= -1 and value['bottom'] <= value['height'] + 1, value
            # Decorative particles can extend the scroll metrics while flying
            # outside the scene. The complete card fits, with no scrollbars.
            assert value['overflowX'] in {'hidden', 'clip'} and value['overflowY'] in {'hidden', 'clip'}, value
            assert (value['buttonBottom'] or value['tipBottom']) <= value['height'] + 1, value
            return value

        fits()
        frame.locator('.container').evaluate('node => window.keptContainer = node')
        frame.locator('#wishBtn').click()
        frame.locator('#wishTip').wait_for()
        fits()
        card.get_by_role('button', name='展开页面', exact=True).click()
        fits()
        card.get_by_role('button', name='关闭页面', exact=True).click()
        fits()
        handle = card.get_by_role('button', name='拖拽等比例调整页面大小', exact=True)
        before = card.locator('.visual-page-viewport').bounding_box()
        handle.focus()
        page.keyboard.press('ArrowLeft')
        fits()
        after = card.locator('.visual-page-viewport').bounding_box()
        assert after['width'] < before['width']
        assert abs(before['width'] / before['height'] - after['width'] / after['height']) < .02
        card.get_by_role('button', name='恢复自动大小', exact=True).click()
        fits()
        card.get_by_role('button', name='源码', exact=True).click()
        assert card.locator('.visual-page-source code').text_content().strip() == source.strip()
        card.get_by_role('button', name='预览', exact=True).click()
        fits()
        assert frame.locator('.container').evaluate('node => node === window.keptContainer')
        assert frame.locator('#wishTip').is_visible()
        page.screenshot(path=str(tmp_path / f'birthday-complete-{width}-{effect_position}.png'))
        page.reload()
        frame.locator('.heart-particle').first.wait_for(state='attached')
        fits()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        browser.close()
