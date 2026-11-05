"""Theme choice, readable palettes and avatar independence on the real Web frontend."""
import pytest
from tests.test_workbench_browser import browser_context,workspace_url,ready  # noqa: F401
from xgent_app.web_branding import DEFAULT_BRANDING

PRESETS=[('neon','流光蓝紫','4-B'),('slate','终端雾蓝','4-C'),('gold','黑曜钛金','4-D'),('mono','黑白极简','4-E'),('duo','冷暖对撞','4-F'),('forest','黑客翠绿','4-A')]


@pytest.fixture
def themed_page(browser_context,workspace_url):
    base=workspace_url['url'];original=browser_context.request.get(base+'/api/branding').json()['branding']
    assert browser_context.request.post(base+'/api/config',data={'key':'web_branding','value':DEFAULT_BRANDING}).ok
    page=browser_context.new_page()
    page.add_init_script("localStorage.removeItem('xgent-theme-palette');localStorage.setItem('xgent-theme','light')")
    ready(page,base)
    page.locator('#input').fill('主题切换保留我的草稿')
    page.locator('#workspace-settings').click();page.locator('.theme-grid').wait_for();page.locator('.branding-form').wait_for()
    yield page
    page.close()
    assert browser_context.request.post(base+'/api/config',data={'key':'web_branding','value':original}).ok


def contrast(a,b):
    def luminance(rgb):
        channels=[float(value.strip())/255 for value in rgb.removeprefix('rgb(').removesuffix(')').split(',')]
        return sum((value/12.92 if value<=.04045 else ((value+.055)/1.055)**2.4)*weight for value,weight in zip(channels,[.2126,.7152,.0722]))
    x,y=sorted([luminance(a),luminance(b)]);return (y+.05)/(x+.05)


def test_theme_and_avatar_order_defaults_are_independent(themed_page,browser_context,workspace_url):
    page=themed_page
    assert page.locator('.theme-option .theme-letter').all_text_contents()==list('abcdef')
    assert page.locator('.brand-avatar-label').all_text_contents()[:6]==list('abcdef')
    assert page.locator('.brand-preset').evaluate_all('rows=>rows.slice(0,6).map(n=>n.dataset.avatar)')==[item[2] for item in PRESETS]
    assert page.locator('.theme-option[aria-checked=true]').get_attribute('data-palette-choice')=='neon'
    assert page.locator('.brand-preset[aria-checked=true]').get_attribute('data-avatar')=='4-B'
    original=browser_context.request.get(workspace_url['url']+'/api/branding').json()['branding']
    page.get_by_role('radio',name='黑曜钛金',exact=True).click()
    assert browser_context.request.get(workspace_url['url']+'/api/branding').json()['branding']==original
    page.locator('[data-avatar="4-C"]').click();page.locator('.branding-form').get_by_role('button',name='保存设置',exact=True).click()
    page.get_by_text('品牌设置已保存，其他网页设备同步生效。',exact=True).wait_for()
    assert page.evaluate('window.XGentTheme.palette')=='gold'
    page.add_init_script("localStorage.setItem('xgent-theme-palette','gold')")
    page.reload();page.locator('.theme-grid').wait_for();page.locator('.brand-preset[aria-checked=true]').wait_for()
    assert page.evaluate('window.XGentTheme.palette')=='gold'
    assert page.locator('.brand-preset[aria-checked=true]').get_attribute('data-avatar')=='4-C'
    page.locator('.wb-brand').click();page.wait_for_function('document.body.dataset.page==="chat"')
    assert page.locator('#input').input_value()=='主题切换保留我的草稿'


@pytest.mark.parametrize('mode',['light','dark'])
def test_each_theme_has_its_own_readable_surfaces(themed_page,mode):
    page=themed_page;page.evaluate('(mode)=>window.XGentTheme.setMode(mode)',mode);backgrounds=[]
    for identifier,name,_ in PRESETS:
        page.get_by_role('radio',name=name,exact=True).click()
        assert page.locator('.theme-option[aria-checked=true]').get_attribute('data-palette-choice')==identifier
        assert page.evaluate('document.documentElement.dataset.theme')==mode
        colors=page.locator('#header').evaluate('(n)=>{const s=getComputedStyle(n);return [s.color,s.backgroundColor]}')
        assert contrast(*colors)>=7,(name,mode,colors)
        backgrounds.append(colors[1])
        action=page.locator('.branding-form button[type=submit]').evaluate('(n)=>{const s=getComputedStyle(n);return [s.color,s.backgroundColor]}')
        assert contrast(*action)>=4.5,(name,mode,action)
        assert page.locator('.brand-preset[aria-checked=true]').get_attribute('data-avatar')=='4-B'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert len(set(backgrounds))==6


def test_theme_cross_tab_and_keyboard_keep_choice_and_avatar(themed_page,browser_context,workspace_url):
    page=themed_page;other=browser_context.new_page();ready(other,workspace_url['url'])
    try:
        page.get_by_role('radio',name='流光蓝紫',exact=True).focus();page.keyboard.press('ArrowRight')
        page.wait_for_function('window.XGentTheme.palette==="slate"')
        other.wait_for_function('window.XGentTheme.palette==="slate"')
        assert page.get_by_role('radio',name='终端雾蓝',exact=True).evaluate('n=>n===document.activeElement')
        page.evaluate('window.XGentTheme.setMode("dark")')
        other.wait_for_function('document.body.classList.contains("dark")')
        assert page.locator('.brand-preset[aria-checked=true]').get_attribute('data-avatar')=='4-B'
        page.locator('.wb-settings-nav [data-panel=agent]').click();page.locator('[name=agent_max_iterations]').wait_for()
        other.evaluate('window.XGentTheme.setPalette("duo")')
        page.wait_for_function('window.XGentTheme.palette==="duo"')
        page.locator('.wb-settings-nav [data-panel=appearance]').click();page.locator('.theme-grid').wait_for()
        assert page.get_by_role('radio',name='冷暖对撞',exact=True).get_attribute('aria-checked')=='true'
    finally:other.close()
