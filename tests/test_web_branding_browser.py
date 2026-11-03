"""Preset geometry, safe previews, configuration persistence and live Web identity."""
import base64
import io
import pytest
from PIL import Image

from tests.test_workbench_browser import browser_context, workspace_url, ready  # noqa: F401
from xgent_app.web_branding import DEFAULT_BRANDING

PATHS = ['M7.5 7.5L16 16L7.5 24.5', 'M16 16L24.5 7.5', 'M17.5 24.5H24.5']
PRESETS = [('4-A', '极客黑客绿'), ('4-B', '电光赛博霓虹'), ('4-C', '终端窗口徽标'),
           ('4-D', '黑曜石钛金'), ('4-E', '纯白极简反显'), ('4-F', '冷暖双色对撞')]


@pytest.fixture
def branding_page(browser_context, workspace_url):
    base = workspace_url['url']
    original = browser_context.request.get(base + '/api/branding').json()['branding']
    assert browser_context.request.post(base + '/api/config', data={'key': 'web_branding', 'value': DEFAULT_BRANDING}).ok
    assert browser_context.request.post(base + '/api/workbench/conversations/switch', data={'id': 'global_memory'}).ok
    page = browser_context.new_page()
    ready(page, base, 'settings')
    page.locator('.branding-form').wait_for()
    yield page
    page.close()
    assert browser_context.request.post(base + '/api/config', data={'key': 'web_branding', 'value': original}).ok


def current_brand(context, base):
    return context.request.get(base + '/api/branding').json()['branding']


def logo(page):
    return page.locator('.wb-brand [data-brand-logo]')


def name(page):
    return page.get_by_role('textbox', name='系统名称', exact=True)


def code(page):
    return page.get_by_role('textbox', name='Logo 代码或图片链接', exact=True)


def preset(page, identifier):
    return page.locator('.brand-avatar-strip [data-avatar="' + identifier + '"]')


def active_avatar(value):
    return next((item for item in value['avatars'] if item['id'] == value['avatar_id']), value)


def save(page):
    page.get_by_role('button', name='保存品牌设置', exact=True).click()
    page.get_by_text('品牌设置已保存，其他网页设备同步生效。', exact=True).wait_for()


def test_six_presets_exact_geometry_and_default_github_logo(branding_page, browser_context, workspace_url, tmp_path):
    page = branding_page
    assert preset(page, '4-B').get_attribute('aria-checked') == 'true'
    assert page.locator('#bot-avatar').is_hidden()
    assert code(page).input_value().strip() == browser_context.request.get(workspace_url['url'] + '/assets/logo.svg').text().strip()
    for identifier, title in PRESETS:
        preset(page, identifier).click()
        assert preset(page, identifier).inner_text() == identifier[-1].lower()
        svg = logo(page).locator('svg')
        assert svg.get_attribute('viewBox') == '0 0 32 32'
        assert svg.locator('path').evaluate_all('(nodes)=>nodes.map(n=>n.getAttribute("d"))') == PATHS
        assert svg.locator('g').get_attribute('stroke-width') == '2.8'
        assert svg.locator('g').get_attribute('stroke-linecap') == 'round'
        assert svg.locator('g').get_attribute('stroke-linejoin') == 'round'
        assert code(page).input_value().startswith('<svg')
        assert page.locator('#login [data-brand-logo] svg').get_attribute('viewBox') == '0 0 32 32'
        if identifier == '4-C':
            assert svg.locator('circle').evaluate_all('(nodes)=>nodes.map(n=>n.getAttribute("fill"))') == ['#ef4444', '#f59e0b', '#10b981']
        if identifier == '4-E':
            assert svg.locator('path').evaluate_all('(nodes)=>nodes.map(n=>n.getAttribute("stroke"))') == ['#ffffff'] * 3
    page.screenshot(path=str(tmp_path / 'branding-presets.png'))
    assert current_brand(browser_context, workspace_url['url']) == DEFAULT_BRANDING
    page.get_by_role('radio', name='自定义', exact=True).click()
    assert code(page).input_value() == ''
    assert logo(page).locator('svg').count() == 0
    page.get_by_role('button', name='取消品牌预览', exact=True).click()
    assert name(page).input_value() == 'XGent'
    assert '#38bdf8' in code(page).input_value()


def test_system_name_and_avatar_update_existing_new_replies_and_refresh(branding_page, browser_context, workspace_url):
    page = branding_page
    name(page).fill('星光 <助手>')
    preset(page, '4-D').click()
    assert page.locator('.wb-brand [data-brand-name]').inner_text() == '星光 <助手>'
    assert page.locator('#login h2').inner_text() == '星光 <助手> Web'
    page.wait_for_function('document.querySelectorAll(".bubble.ai [data-brand-name]").length>0')
    assert page.locator('.bubble.ai [data-brand-name]').first.inner_text() == '星光 <助手>'
    assert logo(page).locator('path').first.get_attribute('stroke') == '#f59e0b'
    assert current_brand(browser_context, workspace_url['url'])['name'] == 'XGent'
    save(page)
    saved = current_brand(browser_context, workspace_url['url'])
    assert saved == {**DEFAULT_BRANDING, 'name': '星光 <助手>', 'preset': '4-D'}
    page.evaluate('''()=>window.XGentChat.renderRecord({id:999999,role:'assistant',msg_type:'ai_reply',content:'NEW_BRANDED_REPLY',timestamp:1},document.getElementById('log'))''')
    assert page.locator('.bubble.ai [data-brand-name]').last.inner_text() == '星光 <助手>'
    assert page.locator('.bubble.ai [data-brand-logo]').last.locator('path').first.get_attribute('stroke') == '#f59e0b'
    page.reload()
    page.locator('.branding-form').wait_for()
    assert name(page).input_value() == '星光 <助手>'
    assert page.title() == '星光 <助手> Web Chat'
    assert preset(page, '4-D').get_attribute('aria-checked') == 'true'
    assert page.locator('.wb-brand script').count() == 0


def test_svg_html_url_and_dataurl_preview_without_saving_per_keystroke(branding_page, browser_context, workspace_url):
    page = branding_page
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="12" fill="#fc923c"/></svg>'
    page.get_by_role('radio', name='自定义', exact=True).click()
    code(page).fill(svg)
    assert logo(page).locator('circle').get_attribute('fill') == '#fc923c'
    markup = '<div style="width:100%;height:100%;background:#10b981;color:white;display:grid;place-items:center">Z</div>'
    code(page).fill(markup)
    assert logo(page).locator('#logo>div').inner_text() == 'Z'
    target = 'https://images.example/logo.png'
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buffer, format='PNG')
    page.route(target, lambda route: route.fulfill(content_type='image/png', body=buffer.getvalue()))
    code(page).fill(target)
    assert logo(page).locator('img').get_attribute('src') == target
    page.wait_for_function('document.querySelector(".wb-brand [data-brand-logo]").shadowRoot.querySelector("img").naturalWidth===4')
    data = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    code(page).fill(data)
    assert logo(page).locator('img').get_attribute('src') == data
    assert current_brand(browser_context, workspace_url['url']) == DEFAULT_BRANDING
    save(page)
    assert active_avatar(current_brand(browser_context, workspace_url['url']))['source'] == data


@pytest.mark.parametrize('extension', ['png', 'jpg', 'webp', 'svg'])
def test_local_image_upload_uses_dataurl_and_persists_config(branding_page, browser_context, workspace_url, extension):
    page = branding_page
    if extension == 'svg':
        raw = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" fill="cyan"/></svg>'
        mime = 'image/svg+xml'
    else:
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'blue').save(buffer, format={'png': 'PNG', 'jpg': 'JPEG', 'webp': 'WEBP'}[extension])
        raw = buffer.getvalue()
        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'webp': 'image/webp'}[extension]
    with page.expect_file_chooser() as choice:
        page.get_by_role('button', name='上传本地图片', exact=True).click()
    choice.value.set_files({'name': 'my-logo.' + extension, 'mimeType': mime, 'buffer': raw})
    page.wait_for_function('document.querySelector(".branding-form textarea").value.startsWith("data:image/")')
    data = code(page).input_value()
    assert base64.b64decode(data.split(',')[1]) == raw
    assert logo(page).locator('img').get_attribute('src') == data
    save(page)
    saved = current_brand(browser_context, workspace_url['url'])
    assert saved['mode'] == 'upload' and active_avatar(saved)['source'] == data
    page.reload()
    page.locator('.branding-form').wait_for()
    assert code(page).input_value() == data


def test_custom_code_cannot_execute_scripts_or_restyle_host_page(branding_page):
    page = branding_page
    color = page.evaluate('getComputedStyle(document.body).backgroundColor')
    page.get_by_role('radio', name='自定义', exact=True).click()
    code(page).fill('''<div style="color:#38bdf8;width:100%;height:100%">SAFE
      <script>window.brandExecuted=1</script><img src="x" onerror="window.brandExecuted=2">
      <svg onload="window.brandExecuted=3" viewBox="0 0 32 32"><path d="M1 1L31 31"/></svg>
      <style>body{background:red}</style><style>:ho\\73 t{position:fixed;width:100vw}</style></div>''')
    assert logo(page).locator('script,[onerror],[onload]').count() == 0
    assert page.evaluate('window.brandExecuted') is None
    assert page.evaluate('getComputedStyle(document.body).backgroundColor') == color
    save(page)
    page.reload()
    page.locator('.branding-form').wait_for()
    assert page.evaluate('window.brandExecuted') is None


def test_save_failure_preserves_editor_and_retry_then_updates_other_device_and_login(branding_page, browser_context, workspace_url):
    page = branding_page
    base = workspace_url['url']
    name(page).fill('跨设备品牌')
    preset(page, '4-A').click()
    before = code(page).input_value()
    page.route('**/api/config', lambda route: route.fulfill(status=503, json={'error': '保存暂时不可用'}) if route.request.method == 'POST' else route.continue_())
    page.get_by_role('button', name='保存品牌设置', exact=True).click()
    page.get_by_text('保存暂时不可用', exact=True).wait_for()
    assert name(page).input_value() == '跨设备品牌' and code(page).input_value() == before
    assert current_brand(browser_context, base) == DEFAULT_BRANDING
    page.unroute('**/api/config')
    other_context = browser_context.browser.new_context(storage_state=browser_context.storage_state())
    other_context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    anonymous = browser_context.browser.new_context()
    anonymous.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
    try:
        other = other_context.new_page()
        ready(other, base)
        save(page)
        other.wait_for_function('window.XGentBranding.name==="跨设备品牌"')
        assert logo(other).locator('path').first.get_attribute('stroke') == '#10b981'
        login = anonymous.new_page()
        login.goto(base)
        login.locator('#login').wait_for()
        login.wait_for_function('window.XGentBranding.name==="跨设备品牌"')
        assert login.locator('#login h2').inner_text() == '跨设备品牌 Web'
        assert login.locator('#login [data-brand-logo] path').first.get_attribute('stroke') == '#10b981'
        assert anonymous.request.get(base + '/api/config').status == 401
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    finally:
        other_context.close()
        anonymous.close()


def test_compact_single_scroll_row_code_save_and_avatar_naming(branding_page, browser_context, workspace_url, tmp_path):
    page = branding_page
    page.set_viewport_size({'width': 390, 'height': 844})
    strip = page.locator('.brand-avatar-strip')
    metrics = strip.evaluate('''node=>{
      const items=[...node.querySelectorAll('.brand-preset')];
      return {labels:items.slice(0,6).map(n=>n.innerText),ys:items.map(n=>n.getBoundingClientRect().y),
        icon:items[0].querySelector('.brand-preset-icon').getBoundingClientRect().height,
        label:items[0].querySelector('.brand-avatar-label').getBoundingClientRect().height,
        scrollable:node.scrollWidth>node.clientWidth};
    }''')
    assert metrics['labels'] == ['a', 'b', 'c', 'd', 'e', 'f']
    assert max(metrics['ys']) - min(metrics['ys']) < 1
    assert metrics['label'] <= metrics['icon']/2 and metrics['scrollable']
    for index in range(3):
        page.get_by_role('radio', name='自定义', exact=True).click()
        assert code(page).input_value() == ''
        code(page).fill(f'<svg viewBox="0 0 32 32"><rect width="32" height="32" fill="rgb({index*70},80,160)"/></svg>')
        page.get_by_role('textbox', name='头像名称', exact=True).fill('头像' + str(index))
        page.locator('.brand-code-editor').get_by_role('button', name='保存头像', exact=True).click()
        page.get_by_text('头像已保存。', exact=True).wait_for()
    stored = current_brand(browser_context, workspace_url['url'])
    assert len(stored['avatars']) == 3
    assert [item['name'] for item in stored['avatars']] == ['头像0', '头像1', '头像2']
    assert stored['source'] == '' and stored['avatar_id'] == stored['avatars'][-1]['id']
    identifier = stored['avatar_id']
    page.get_by_role('textbox', name='头像名称', exact=True).fill('改名')
    page.get_by_role('button', name='命名', exact=True).click()
    page.get_by_text('头像已保存。', exact=True).wait_for()
    renamed = current_brand(browser_context, workspace_url['url'])
    assert len(renamed['avatars']) == 3 and renamed['avatar_id'] == identifier
    assert active_avatar(renamed)['name'] == '改名'
    page.reload()
    page.locator('.branding-form').wait_for()
    assert len(current_brand(browser_context, workspace_url['url'])['avatars']) == 3
    assert page.get_by_role('radio', name='改名', exact=True).get_attribute('aria-checked') == 'true'
    assert page.get_by_role('textbox', name='头像名称', exact=True).input_value() == '改名'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(tmp_path / 'branding-compact-mobile.png'))


def test_avatar_save_keeps_unsaved_system_name_and_merges_other_device_library(branding_page, browser_context, workspace_url):
    page = branding_page
    base = workspace_url['url']
    name(page).fill('尚未保存的系统名')
    page.get_by_role('radio', name='自定义', exact=True).click()
    code(page).fill('<div style="background:cyan;width:100%;height:100%">A</div>')
    page.get_by_role('textbox', name='头像名称', exact=True).fill('本页头像')
    external = {**DEFAULT_BRANDING, 'avatars': [{'id': 'other-device', 'name': '另一设备头像', 'mode': 'custom',
                                                'source': '<div style="background:orange;width:100%;height:100%">B</div>'}]}
    assert browser_context.request.post(base + '/api/config', data={'key': 'web_branding', 'value': external}).ok
    page.evaluate('window.XGentBranding.refresh(true)')
    page.get_by_role('button', name='保存头像', exact=True).click()
    page.get_by_text('头像已保存。', exact=True).wait_for()
    stored = current_brand(browser_context, base)
    assert stored['name'] == 'XGent'
    assert {item['name'] for item in stored['avatars']} == {'本页头像', '另一设备头像'}
    assert name(page).input_value() == '尚未保存的系统名'
    save(page)
    assert current_brand(browser_context, base)['name'] == '尚未保存的系统名'
