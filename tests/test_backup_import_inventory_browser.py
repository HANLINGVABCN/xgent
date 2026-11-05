"""A sparse archive still displays the full, safely disabled import inventory."""
import pytest
from tests.test_workbench_browser import browser_context,workspace_url  # noqa: F401
from tests.test_backup_options_browser import backup_api,open_backups
from xgent_app.data_contents import BACKUP_GROUPS


@pytest.mark.parametrize('width',[320,390,768,1440])
@pytest.mark.parametrize('theme',['light','dark'])
def test_sparse_archive_lists_all_groups_and_only_restores_available_parts(browser_context,workspace_url,width,theme,tmp_path):
    page=browser_context.new_page();page.set_viewport_size({'width':width,'height':1000});page.emulate_media(reduced_motion='reduce')
    records=backup_api(page,import_keys=['secrets','memory'])
    page.on('dialog',lambda dialog:dialog.accept())
    open_backups(page,workspace_url['url']);page.evaluate('theme=>document.body.classList.toggle("dark",theme==="dark")',theme)
    page.locator('[data-archive-name="manual-fixture.zip"] .wb-backup-entry-select').click()
    page.get_by_role('button',name='确认覆盖并导入',exact=True).wait_for()
    groups=page.locator('[data-import-row]')
    assert groups.evaluate_all('rows=>rows.map(row=>row.dataset.importRow)')==[group['id'] for group in BACKUP_GROUPS]
    assert page.locator('[data-import-category]:enabled').count()==2
    assert page.locator('[data-import-category]:disabled').count()==5
    for group in BACKUP_GROUPS:
        row=page.locator('[data-import-row="'+group['id']+'"]')
        if group['id'] in ('configuration','conversations'):
            assert row.locator('input').is_enabled()
        else:
            assert row.locator('input').is_disabled() and not row.locator('input').is_checked()
            assert row.get_attribute('aria-disabled')=='true'
            assert row.locator('.wb-import-availability').inner_text()=='压缩包未包含'
    configuration=page.locator('[data-import-row=configuration]');configuration.locator('summary').click()
    assert configuration.locator('[data-import-part=secrets]').inner_text().endswith('已包含')
    assert configuration.locator('[data-import-part=ai_config]').inner_text().endswith('未包含')
    page.get_by_role('button',name='全不选导入部分',exact=True).click()
    assert page.locator('[data-import-category]:checked').count()==0
    assert page.get_by_role('button',name='确认覆盖并导入',exact=True).is_disabled()
    page.get_by_role('button',name='全选可导入部分',exact=True).click()
    assert page.locator('[data-import-category]:checked').count()==2
    assert page.locator('[data-import-category]:disabled').count()==5
    page.locator('.wb-backup-import-card').scroll_into_view_if_needed()
    assert page.locator('.wb-import-content-groups').evaluate('node=>node.scrollWidth<=node.clientWidth+1')
    page.screenshot(path=str(tmp_path/f'import-inventory-{width}-{theme}.png'))
    page.get_by_role('button',name='确认覆盖并导入',exact=True).click()
    page.get_by_text('导入完成，所覆盖的旧内容已清理。',exact=True).wait_for()
    data=next(data for resource,data in records if resource=='activate')
    assert set(data['categories'])=={'secrets','memory'}
    page.close()


def test_switching_archive_rechecks_absence_and_all_selection(browser_context,workspace_url):
    page=browser_context.new_page();backup_api(page);open_backups(page,workspace_url['url'])
    page.locator('[data-archive-name="manual-fixture.zip"] .wb-backup-entry-select').click()
    page.get_by_label('导入 连接与应用配置',exact=True).wait_for()
    assert page.get_by_label('导入 连接与应用配置',exact=True).is_enabled()
    page.locator('[data-archive-name="manual-output.tar.xz"] .wb-backup-entry-select').click()
    page.wait_for_function('document.querySelector("[data-import-category=command_outputs]")?.disabled===false')
    assert page.locator('[data-import-row]').count()==len(BACKUP_GROUPS)
    assert page.get_by_label('导入 连接与应用配置',exact=True).is_disabled()
    assert page.get_by_label('导入 对话与记忆',exact=True).is_disabled()
    page.get_by_role('button',name='全选可导入部分',exact=True).click()
    assert page.locator('[data-import-category]:checked').count()==1
    assert page.locator('[data-import-category]:checked').get_attribute('data-import-category')=='command_outputs'
    page.close()


def test_declared_empty_content_is_available_and_failed_import_keeps_absent_disabled(browser_context,workspace_url):
    page=browser_context.new_page();backup_api(page,import_keys=['memory'],empty_parts=['memory'])
    page.route('**/api/workbench/data/activate',lambda route:route.fulfill(status=503,json={'error':'暂时无法导入'}))
    page.on('dialog',lambda dialog:dialog.accept())
    open_backups(page,workspace_url['url'])
    page.locator('[data-archive-name="manual-fixture.zip"] .wb-backup-entry-select').click()
    memory=page.get_by_label('导入 对话与记忆',exact=True);memory.wait_for()
    assert memory.is_enabled() and memory.is_checked()
    assert '0 个文件 · 0 B' in page.locator('[data-import-row=conversations] .wb-import-availability').inner_text()
    page.get_by_role('button',name='确认覆盖并导入',exact=True).click()
    page.get_by_text('暂时无法导入',exact=True).wait_for()
    assert memory.is_enabled() and memory.is_checked()
    assert page.locator('[data-import-category]:disabled').count()==6
    assert page.get_by_role('button',name='确认覆盖并导入',exact=True).is_enabled()
    page.close()
