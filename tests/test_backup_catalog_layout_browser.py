"""Archive names, metadata and actions stay readable inside the backup list."""
import pytest
from tests.test_workbench_browser import browser_context,workspace_url  # noqa: F401
from tests.test_backup_options_browser import backup_api,open_backups


@pytest.mark.parametrize('width',[320,390,768,1440])
@pytest.mark.parametrize('ui_size',[14,20])
def test_long_backup_name_fits_and_actions_remain_compact(browser_context,workspace_url,width,ui_size,tmp_path):
    page=browser_context.new_page();page.set_viewport_size({'width':width,'height':1000});page.emulate_media(reduced_motion='reduce')
    name='xgent-manual-2026-11-05-181115-cf7e79c1-完整项目数据备份及全部对话附件.zip'
    backup_api(page,archive_names=[name]);open_backups(page,workspace_url['url'])
    page.evaluate('(size)=>window.XGentAppearance.preview({web_ui_font_size:size})',ui_size)
    entry=page.locator('.wb-backup-entry');entry.scroll_into_view_if_needed()
    assert entry.locator('.wb-backup-entry-name').inner_text()==name
    assert entry.locator('button.wb-btn').count()==0
    metrics=entry.evaluate('''node=>{
      const b=node.getBoundingClientRect(),button=node.querySelector('.wb-backup-entry-select'),
        name=button.querySelector('strong'),dl=node.querySelector('a'),box=node.querySelector('input');
      const fits=element=>{const r=element.getBoundingClientRect();return r.left>=b.left&&r.right<=b.right+1};
      return {overflow:node.scrollWidth-node.clientWidth,buttonHeight:button.offsetHeight,
        nameFits:fits(name),downloadFits:fits(dl),checkFits:fits(box),display:getComputedStyle(button).flexDirection};
    }''')
    assert metrics['overflow']<=1
    assert metrics['nameFits'] and metrics['downloadFits'] and metrics['checkFits']
    assert metrics['display']=='column'
    assert metrics['buttonHeight']<300
    assert entry.locator('.wb-backup-download').get_attribute('href').startswith('/api/workbench/data/backup-download?name=')
    assert '手动备份' in entry.inner_text() and '3 个文件' in entry.inner_text() and 'ZIP' in entry.inner_text()
    assert page.locator('.wb-backup-entries').evaluate('node=>node.scrollWidth<=node.clientWidth+1')
    page.screenshot(path=str(tmp_path/f'backup-{width}-{ui_size}.png'))
    entry.locator('[data-backup-name]').check()
    assert '已选 1 / 1 个' in page.locator('.wb-backup-delete-summary').inner_text()
    assert page.get_by_role('button',name='删除选中压缩包',exact=True).is_enabled()
    entry.locator('.wb-backup-entry-select').click()
    page.get_by_role('button',name='确认覆盖并导入',exact=True).wait_for()
    assert entry.locator('.wb-backup-entry-select').get_attribute('aria-pressed')=='true'
    page.close()
