"""Cross-process mode changes update Web controls without losing drafts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from tests.test_database_write_lock import _load_db_class
from tests.test_workbench_browser import browser_context, workspace_url  # noqa: F401


def test_cli_style_config_change_updates_chat_and_settings_tabs(browser_context, workspace_url):
    base = workspace_url['url']
    assert browser_context.request.post(base+'/api/config', data={'key':'stream_mode','value':False}).ok
    chat, settings = browser_context.new_page(), browser_context.new_page()
    chat.goto(base+'/#/chat')
    chat.wait_for_function('document.querySelector("#composer-model")?.disabled===false')
    chat.locator('#input').fill('跨端同步不能丢掉草稿')
    settings.goto(base+'/#/settings')
    settings.locator('.wb-settings-nav [data-panel=conversation]').click()
    mode = settings.get_by_label('回复方式', exact=True)
    mode.wait_for()
    assert settings.get_by_label('Bot 回复方式', exact=True).count()==0
    assert mode.input_value()=='nonstream'

    def change(enabled):
        async def write():
            db = _load_db_class()(workspace_url['database_path'])
            try:
                await db.set_config('stream_mode', enabled)
            finally:
                await db.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(write())).result(timeout=10)

    chat.get_by_role('button', name='生成选项', exact=True).click()
    chat.get_by_role('button', name='回复方式', exact=True).click()
    for enabled, value, label in [(True,'foreground','流式'), (False,'nonstream','非流式')]:
        change(enabled)
        chat.wait_for_function('(label)=>[...document.querySelectorAll("[role=radio]")].some(node=>node.textContent===label&&node.getAttribute("aria-checked")==="true")', arg=label)
        settings.wait_for_function('(value)=>document.querySelector("select[name=response_mode]")?.value===value', arg=value)
        assert chat.locator('#input').input_value()=='跨端同步不能丢掉草稿'
        assert mode.input_value()==value
    chat.close();settings.close()
