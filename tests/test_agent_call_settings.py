import re

import pytest

from tests.test_thinking_params import run_in_app
from tests.test_workbench_browser import workspace_url, browser_context, ready  # noqa: F401
from xgent_app.repository_archive import archive_url, request_for


def test_fresh_defaults_and_existing_database_missing_mode_keep_fence(tmp_path):
    result = run_in_app('''import asyncio,sqlite3
from pathlib import Path
async def main():
    path=Path('mode.db')
    db=bot.BotMemoryDB(str(path));await db._init_db()
    fresh=await db.get_config('agent_call_mode');await db.close()
    with sqlite3.connect(path) as conn:conn.execute("DELETE FROM config WHERE key='agent_call_mode'")
    db=bot.BotMemoryDB(str(path));await db._init_db()
    older=await db.get_config('agent_call_mode');await db.set_config('agent_call_mode','toolcall');await db.close()
    db=bot.BotMemoryDB(str(path));await db._init_db()
    kept=await db.get_config('agent_call_mode');await db.close()
    print(json.dumps({'fresh':fresh,'older':older,'kept':kept}))
asyncio.run(main())''')
    assert result == {'fresh': 'toolcall', 'older': 'fence', 'kept': 'toolcall'}


def test_web_call_mode_choices_save_and_preserve_composer_draft(browser_context, workspace_url):
    page = browser_context.new_page()
    ready(page, workspace_url['url'])
    page.locator('#input').fill('unchanged draft')
    trigger = page.get_by_role('button', name='生成选项', exact=True)
    for name, value in [('正则围栏', 'fence'), ('Tool call', 'toolcall')]:
        trigger.click()
        page.get_by_role('radiogroup', name='工具调用方式').get_by_role('radio', name=name, exact=True).click()
        page.locator('#composer-options-popover').wait_for(state='hidden')
        settings = browser_context.request.get(workspace_url['url'] + '/api/workbench/bootstrap').json()
        assert settings['settings']['values']['agent_call_mode'] == value
        assert page.locator('#input').input_value() == 'unchanged draft'
    response = browser_context.request.post(workspace_url['url'] + '/api/workbench/settings',
        data={'key': 'agent_call_mode', 'value': 'invalid'})
    assert not response.ok
    page.close()


def test_private_archive_uses_auth_only_for_github_and_keeps_explicit_source(tmp_path, monkeypatch):
    for key in ('UPDATE_ZIP_URL', 'UPDATE_GITHUB_TOKEN', 'GITHUB_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / '.env'
    env.write_text('UPDATE_GITHUB_TOKEN="fixture-token"\n', encoding='utf-8')
    request = request_for(env)
    assert request.full_url == 'https://api.github.com/repos/HANLINGVABCN/xgent/zipball/main'
    assert request.get_header('Authorization') == 'Bearer fixture-token'
    env.write_text('UPDATE_GITHUB_TOKEN=fixture-token\nUPDATE_ZIP_URL=https://example.org/release.zip\n', encoding='utf-8')
    assert not request_for(env).has_header('Authorization')
    assert request_for(env).full_url == 'https://example.org/release.zip'
    assert archive_url('https://github.com/HANLINGVABCN/xgent.git') == request.full_url


def test_standalone_installer_embedded_python_still_parses():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / 'install.sh').read_text(encoding='utf-8')
    for index, fragment in enumerate(re.findall(r"<<'PY'\n(.*?)\nPY", text, flags=re.S)):
        compile(fragment, f'installer-heredoc-{index}', 'exec')
