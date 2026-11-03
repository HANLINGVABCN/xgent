"""Child prompt knowledge exclusion with ordinary tool access unchanged."""
import unittest

from tests.test_external_sync import SectionsProbeMixin


class ChildPromptContextTests(SectionsProbeMixin, unittest.TestCase):
    def test_existing_children_and_replayed_routes_omit_knowledge_only(self):
        result = self.run_probe(self.SECTIONS_PREAMBLE + r'''
import asyncio
from pathlib import Path
from unittest.mock import patch
from xgent_app.conversations import bind_conversation, conversation_snapshot, replay_conversation
from xgent_app.tool_calls import ToolSession, session_scope

async def main():
    await ns['UserDataManager'].init()
    db = await ns['BotMemoryDB'].get_instance()
    manager = ns['get_conversations']()
    parent = await manager.resolve('global_memory')
    child = (await db.create_child_conversation(parent.conversation_id, 'child'))['conversation_id']
    grandchild = (await db.create_child_conversation(child, 'grandchild'))['conversation_id']
    ordinary = (await db.manage_conversation('create', name='ordinary', select=False))['conversation_id']
    ns['PromptFileManager'].set('assistant_prompt', 'BASE_PERSONA\n')
    ns['PromptFileManager'].set('global_prompt_addon', 'BASE_GLOBAL\n')
    ns['PromptFileManager'].set('agent_prompt_addon', 'BASE_FENCE\n')
    ns['PromptFileManager'].set('agent_toolcall_addon', 'BASE_NATIVE\n')
    ns['PromptFileManager'].set('agent_disabled_addon', 'BASE_DISABLED\n')
    tick = chr(96) * 3
    for directory, filename, marker in (
        ('skill-public', 'secret-skill.md', 'PRIVATE_SKILL'),
        ('skill-private', 'local-skill.md', 'LOCAL_SKILL'),
        ('skill', 'legacy-skill.md', 'LEGACY_SKILL'),
    ):
        path = Path(directory) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tick+'!\n'+marker+'\n'+tick+'\nSKILL_BODY', encoding='utf-8')
    memory = Path(ns['MEMORY_DIR']) / 'memory_secret.txt'
    memory.parent.mkdir(parents=True, exist_ok=True)
    memory.write_text('PRIVATE_MEMORY', encoding='utf-8')
    with bind_conversation(parent):
        await db.record_global_message(1, 1, 'user_text', 'user', 'PARENT_OWN_HISTORY')
        before = ns['build_conversation_system_prompt'](True)
        assert all(marker in before for marker in ('PRIVATE_SKILL','LOCAL_SKILL','LEGACY_SKILL','PRIVATE_MEMORY'))
    for cid in (child, grandchild):
        scope = await manager.resolve(cid)
        assert scope.owner_conversation_id
        with bind_conversation(scope):
            await db.record_global_message(1, 1, 'user_text', 'user', 'CHILD_OWN_HISTORY')
            for mode, enabled, notification in (
                ('toolcall',True,False), ('fence',True,False),
                ('toolcall',False,False), ('fence',False,False), ('toolcall',False,True),
            ):
                with session_scope(ToolSession('openai','provider','model','prompt-run',mode=mode)):
                    with patch.dict(ns, {
                        'build_skill_prompt_section': lambda: (_ for _ in ()).throw(AssertionError('child scanned skills')),
                        'build_memory_prompt_section': lambda: (_ for _ in ()).throw(AssertionError('child read memories')),
                    }):
                        prompt = ns['build_conversation_system_prompt'](enabled, notification_only=notification)
                assert 'BASE_PERSONA' in prompt and 'BASE_GLOBAL' in prompt and '【对话附件】' in prompt
                assert all(marker not in prompt for marker in (
                    'PRIVATE_SKILL','LOCAL_SKILL','LEGACY_SKILL','PRIVATE_MEMORY',
                    'secret-skill.md','local-skill.md','legacy-skill.md',
                    '【用户记忆】','【技能查阅】','skill 公有目录','skill 私有目录',
                )), prompt
                if enabled and not notification:
                    assert ('BASE_NATIVE' if mode=='toolcall' else 'BASE_FENCE') in prompt
                elif not notification:
                    assert 'BASE_DISABLED' in prompt
            assert ns['build_skill_prompt_section']() == '' and ns['build_memory_prompt_section']() == ''
            # These readers are unchanged: the task only removes automatic injection.
            assert 'SKILL_BODY' in ns['read_skill_text'](str(Path('skill-public/secret-skill.md').resolve()))
            assert ns['read_memory_file']('memory_secret.txt') == 'PRIVATE_MEMORY'
            history = await db.get_conversation_messages(10)
            assert 'CHILD_OWN_HISTORY' in json.dumps(history) and 'PARENT_OWN_HISTORY' not in json.dumps(history)
            saved = conversation_snapshot()
        with bind_conversation(parent), replay_conversation(saved):
            assert ns['build_skill_prompt_section']() == '' and ns['build_memory_prompt_section']() == ''
        with bind_conversation(parent):
            assert 'PRIVATE_MEMORY' in ns['build_conversation_system_prompt'](True)
    with bind_conversation(await manager.resolve(ordinary)):
        assert 'PRIVATE_SKILL' in ns['build_conversation_system_prompt'](True)
        assert 'PRIVATE_MEMORY' in ns['build_conversation_system_prompt'](True)
    await manager.close()
    await db.close()
    print(json.dumps({'children':True,'descendants':True,'modes':True,'replayed':True,
                      'own_history':True,'readers_unchanged':True,'parent_unchanged':True}))

asyncio.run(main())
''')
        self.assertTrue(all(result.values()), result)
