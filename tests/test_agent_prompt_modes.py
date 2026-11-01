from pathlib import Path

import pytest

from tests.test_thinking_params import run_in_app
from xgent_app.prompt_defaults import DEFAULT_GLOBAL_PROMPT, DEFAULT_TOOLCALL_PROMPT, migrate_shipped_prompt

FIXTURES = Path(__file__).parent / 'fixtures' / 'prompt-upgrades'


@pytest.mark.parametrize('name,key,expected', [('toolcall_addon.txt', 'agent_toolcall_addon', DEFAULT_TOOLCALL_PROMPT),
                                            ('global_addon.txt', 'global_prompt_addon', DEFAULT_GLOBAL_PROMPT)])
def test_only_exact_old_default_is_upgraded_and_original_backup_is_preserved(tmp_path, name, key, expected):
    path = tmp_path / name
    original = (FIXTURES / name).read_bytes()
    path.write_bytes(original)
    assert migrate_shipped_prompt(path, key)
    assert path.read_text(encoding='utf-8') == expected
    backups = list(tmp_path.glob('*.bak'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert not migrate_shipped_prompt(path, key)
    assert len(list(tmp_path.glob('*.bak'))) == 1
    custom = original + '\nUSER_ADDED_RULE\n'.encode()
    path.write_bytes(custom)
    assert not migrate_shipped_prompt(path, key)
    assert path.read_bytes() == custom
    assert not list(tmp_path.glob('.prompt-upgrade-*'))


def test_prompt_changed_during_default_upgrade_is_not_overwritten(tmp_path, monkeypatch):
    import os
    from xgent_app import prompt_defaults
    path = tmp_path / 'toolcall_addon.txt'
    path.write_bytes((FIXTURES / path.name).read_bytes())
    fsync = os.fsync
    calls = 0
    def changed_after_flush(fd):
        nonlocal calls
        fsync(fd)
        calls += 1
        if calls == 2:
            path.write_text('USER_EDIT_DURING_UPGRADE', encoding='utf-8')
    monkeypatch.setattr(prompt_defaults.os, 'fsync', changed_after_flush)
    assert not migrate_shipped_prompt(path, 'agent_toolcall_addon')
    assert path.read_text(encoding='utf-8') == 'USER_EDIT_DURING_UPGRADE'
    assert not list(tmp_path.glob('.prompt-upgrade-*'))


def test_mode_prompt_isolation_keeps_persona_memory_and_selected_custom_file(tmp_path):
    result = run_in_app('''import asyncio
from unittest.mock import patch
from tests.attachment_request_probe import Harness
from xgent_app.tool_calls import ToolSession, session_scope
from xgent_app.prompt_defaults import DEFAULT_TOOLCALL_PROMPT
async def exercise(root):
    async with Harness(bot,root) as h:
        bot.PromptFileManager.set('agent_prompt_addon', 'CUSTOM_FENCE_ONLY\\n本环境没有原生工具，禁止使用 toolcall')
        bot.PromptFileManager.set('agent_toolcall_addon', DEFAULT_TOOLCALL_PROMPT + 'CUSTOM_NATIVE_ONLY\\n')
        bot.PromptFileManager.set('assistant_prompt', 'PERSONA_KEEP\\n')
        bot.PromptFileManager.set('global_prompt_addon', 'GLOBAL_KEEP\\n')
        with patch.object(bot,'build_memory_prompt_section',return_value='MEMORY_KEEP\\n'), patch.object(bot,'build_skill_prompt_section',return_value='SKILL_KEEP\\n'):
            with session_scope(ToolSession('openai','p','m','r',mode='toolcall')):
                await bot.UserDataManager.save_config('agent_call_mode','fence')
                native=bot.build_conversation_system_prompt(True)
                disabled=bot.build_conversation_system_prompt(False)
            with session_scope(ToolSession('openai','p','m','r2',mode='fence')):
                fence=bot.build_conversation_system_prompt(True)
            for text in (native,fence,disabled):
                assert all(text.count(value)==1 for value in ('PERSONA_KEEP','GLOBAL_KEEP','MEMORY_KEEP','SKILL_KEEP'))
            assert 'CUSTOM_NATIVE_ONLY' in native and 'CUSTOM_FENCE_ONLY' not in native
            assert '禁止使用 toolcall' not in native and 'read_file' in native and 'send_file' in native
            assert 'CUSTOM_FENCE_ONLY' in fence and 'CUSTOM_NATIVE_ONLY' not in fence
            assert 'CUSTOM_FENCE_ONLY' not in disabled and 'CUSTOM_NATIVE_ONLY' not in disabled
            assert '本次没有 Agent 工具' in disabled and '需要交付文件时使用' not in disabled
            await bot.UserDataManager.save_config('agent_call_mode','toolcall')
            assert 'CUSTOM_NATIVE_ONLY' in bot.build_conversation_system_prompt(True)
            path=bot.PromptFileManager.get_abs_path('agent_toolcall_addon')
            from pathlib import Path
            Path(path).write_text('',encoding='utf-8')
            try:bot.build_conversation_system_prompt(True)
            except ValueError:pass
            else:raise AssertionError('Empty native prompt silently fell back')
            Path(path).unlink()
            try:bot.build_conversation_system_prompt(True)
            except OSError:pass
            else:raise AssertionError('Missing native prompt silently fell back')
            assert bot.PromptFileManager.get('agent_prompt_addon').startswith('CUSTOM_FENCE_ONLY')
        return {'isolated':True,'persona_kept':True,'no_fallback':True}
''' + f'print(json.dumps(asyncio.run(exercise({str(tmp_path)!r}))))')
    assert all(result.values())


def test_fresh_prompt_initialization_supplies_native_defaults_and_keeps_user_edits(tmp_path):
    result = run_in_app('''from pathlib import Path
from xgent_app.prompt_defaults import DEFAULT_TOOLCALL_PROMPT
PFM=bot.PromptFileManager
PFM.PROMPTS_DIR=''' + repr(str(tmp_path)) + '''
PFM.init()
path=Path(PFM.get_abs_path('agent_toolcall_addon'))
assert path.read_text(encoding='utf-8')==DEFAULT_TOOLCALL_PROMPT
path.write_text('USER_NATIVE_RULE',encoding='utf-8')
PFM.init()
assert path.read_text(encoding='utf-8')=='USER_NATIVE_RULE'
labels=[b.text for row in bot.get_prompts_menu().inline_keyboard for b in row]
assert any('正则围栏模式提示词' in label for label in labels)
assert any('Tool call 模式提示词' in label for label in labels)
print(json.dumps({'default':True,'preserved':True,'labels':True}))''')
    assert all(result.values())


def test_missing_global_file_does_not_mask_existing_database_prompt(tmp_path):
    result = run_in_app('''from pathlib import Path
PFM=bot.PromptFileManager
PFM.PROMPTS_DIR=''' + repr(str(tmp_path)) + '''
bot.UserDataManager.set('global_prompt_addon','SAVED_GLOBAL_RULE')
PFM.init()
assert Path(PFM.get_abs_path('global_prompt_addon')).read_text(encoding='utf-8')==''
assert bot.get_runtime_prompt('global_prompt_addon')=='SAVED_GLOBAL_RULE'
print(json.dumps({'saved_prompt_preserved':True}))''')
    assert result['saved_prompt_preserved']


def test_idle_prompt_describes_notification_only_even_with_agent_globally_enabled(tmp_path):
    result = run_in_app('''import asyncio,time
from unittest.mock import AsyncMock,patch
from tests.native_tool_probe import NativeHarness
async def exercise(root):
    async with NativeHarness(bot,root,'openai','nonstream') as h:
        with patch.object(h.db,'get_last_user_message_time',new=AsyncMock(return_value=time.time()-172800)):
            await bot._check_and_send_idle_message(h.context)
        assert len(h.requests)==1
        assert not h.requests[0].get('tools')
        prompt=h.requests[0]['messages'][0]['content']
        assert '本次没有 Agent 工具' in prompt
        assert '这不改变用户的 Agent 开关设置' in prompt
        assert '【Agent 权限关闭】' not in prompt
        assert '需要用户开启 Agent 模式' not in prompt
        assert bot.UserDataManager.get('agent_mode') is True
        assert '当前执行入口是 API tools' not in prompt
        assert '唯一执行入口是回复正文' not in prompt
        return {'notification_only':True,'no_tools':True}
''' + f'print(json.dumps(asyncio.run(exercise({str(tmp_path)!r}))))')
    assert all(result.values())


def test_shipped_skill_summaries_do_not_reintroduce_fence_only_instructions():
    result = run_in_app('''from pathlib import Path
import re
summary='\\n'.join(bot.extract_skill_summary_blocks(path.read_text(encoding='utf-8'))
                  for path in (Path(bot.PROJECT_ROOT)/'skill-public').glob('*.md'))
assert not re.search(r'\\b(?:run|shell|stdin|shellkill|read|grep|intel|edit|file|sendfile|media|ask|over)-x\\b',summary)
assert 'BEGIN/END 标记' not in summary
assert '用户明确要求“记住”' in summary and 'trigger' in summary
print(json.dumps({'mode_neutral_summaries':True}))''')
    assert result['mode_neutral_summaries']
