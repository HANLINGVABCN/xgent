import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_backup_options import instance
from tests.test_thinking_params import run_in_app
from xgent_app.agent_sendfile import execute_sendfile_protocol
from xgent_app.bot_data import BotBackups
from xgent_app.conversations import ConversationScope, bind_conversation
from xgent_app.data_archives import ArchiveReader
from xgent_app.data_operations import DataOperations


class Message:
    chat_id = 1
    message_id = 99

    def __init__(self):
        self.edits = []

    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))
        return self


class NativeOnlyBot:
    def __init__(self):
        self.files = []

    async def send_document(self, document, filename, **kwargs):
        self.files.append((filename, document.read()))
        return SimpleNamespace(message_id=500)

    async def flush_telegram(self, timeout=5):
        return True


def namespace(paths, native):
    return {'DATA_PATHS': paths, 'CallbackDataStore': SimpleNamespace(store=lambda value: value),
        'build_trigger_delivery_bot': lambda chat_id: native,
        '_SelfTriggerContext': lambda bot: SimpleNamespace(bot=bot),
        'execute_sendfile_protocol': execute_sendfile_protocol,
        'AgentExecutor': SimpleNamespace(resolve_file_path=lambda value: value, MAX_FILE_SIZE=50 * 1024 * 1024),
        'BotConfig': SimpleNamespace(API_BASE_URL=''), '_LOCAL_API_HOST_DATA_DIR': '',
        '_LOCAL_API_CONTAINER_DATA_DIR': '', 'safe_send_message': AsyncMock(), 'safe_text': str,
        'logger': logging.getLogger(__name__), 'cancel_task_quietly': AsyncMock()}


async def finish(controller):
    await asyncio.gather(*list(controller.operations.tasks))
    await asyncio.gather(*list(controller.tasks))


@pytest.mark.parametrize('format', ['zip', 'tar.zst', 'tar.xz'])
def test_bot_exports_all_data_without_environment_or_web_and_repeated_click_does_not_resend(tmp_path, format):
    paths, _ = instance(tmp_path)
    (paths.root / 'prompts').mkdir()
    (paths.root / 'prompts/main.txt').write_text('persona unchanged')
    paths.env.write_text('BOT_TOKEN=private-env-fixture\nAUTHORIZED_USER_ID=123\n')
    native = NativeOnlyBot()
    async def exercise():
        with bind_conversation(ConversationScope('A', 0, origin='telegram')):
            controller = BotBackups(namespace(paths, native))
            message = Message()
            query = SimpleNamespace(message=message)
            await controller.handle(None, query, 'menu_backup_export')
            buttons = [button for row in message.edits[-1][1].inline_keyboard for button in row]
            assert len([button for button in buttons if str(button.callback_data).startswith('backup_export:')]) == 3
            action = next(button.callback_data for button in buttons if button.callback_data.startswith('backup_export:' + format + ':'))
            await controller.handle(None, query, action)
            await finish(controller)
            await controller.handle(None, query, action)
            await finish(controller)
            assert len(native.files) == 1, message.edits
            job = next(iter(controller.operations.jobs.values()))
            with ArchiveReader(job['result']['path']) as archive:
                manifest = json.loads(archive.read_manifest())
                assert manifest['include_environment'] is False
                assert manifest['version'] == 3
                assert '.env' not in manifest['files']
                assert {'xgent_memory.db', 'memory/note.md', 'prompts/main.txt',
                        'xgent_storage/command_outputs/result.txt'} <= set(manifest['files'])
            assert any('.env' in text and '用户 ID' in text for text, _ in message.edits)
    asyncio.run(exercise())


def test_bot_lists_existing_backups_and_imports_with_environment_protection_without_web(tmp_path):
    paths, bundles = instance(tmp_path)
    exported = bundles.export()
    native = NativeOnlyBot()
    async def exercise():
        with bind_conversation(ConversationScope('A', 0, origin='telegram')):
            controller = BotBackups(namespace(paths, native))
            activate = controller.operations.activate = Mock(return_value={'ok': True})
            message = Message()
            query = SimpleNamespace(message=message)
            await controller.handle(None, query, 'menu_backup_import')
            action = next(button.callback_data for row in message.edits[-1][1].inline_keyboard
                          for button in row if str(button.callback_data).startswith('backup_import:'))
            assert Path(exported['path']).name in action
            await controller.handle(None, query, action)
            await finish(controller)
            activate.assert_called_once()
            assert activate.call_args.args[0]['preserve_environment'] is True
            assert activate.call_args.args[0]['confirm_replace'] is True
            await controller.handle(None, query, action)
            activate.assert_called_once()
            assert not native.files
    asyncio.run(exercise())


@pytest.mark.parametrize('include_environment', [True, False])
def test_restoring_a_bot_backup_preserves_exact_local_environment(tmp_path, include_environment):
    source_root, target_root = tmp_path/'source', tmp_path/'target'
    source_root.mkdir(); target_root.mkdir()
    source_paths, source = instance(source_root)
    target_paths, target = instance(target_root)
    source_paths.env.write_text('BOT_TOKEN=foreign\nAUTHORIZED_USER_ID=999\nCUSTOM_SETTING=foreign\n')
    target_paths.env.write_bytes(b'BOT_TOKEN=local\r\nAUTHORIZED_USER_ID=123\r\nCUSTOM_SETTING=local\r\n')
    before = target_paths.env.read_bytes()
    exported = source.export(include_environment=include_environment)
    staging, _ = target.prepare_import(exported['path'])
    result = target.activate(staging, preserve_environment=include_environment)
    assert target_paths.env.read_bytes() == before
    assert '.env' not in result['installed_state'] and '.env' not in result['moved_state']


def test_environment_is_omitted_from_independent_parts_as_well_as_the_file(tmp_path):
    paths, service = instance(tmp_path)
    paths.env.write_text('BOT_TOKEN=secret\nAUTHORIZED_USER_ID=999\n')
    exported = service.export(categories=['secrets', 'ai_config', 'app_settings'], include_environment=False)
    with ArchiveReader(exported['path']) as archive:
        for member in archive.members:
            if member.name.startswith('backup_parts/'):
                records = [json.loads(line) for line in archive.open(member).read().splitlines()]
                assert records[0]['env'] is False
                assert not any(record.get('type') == 'env' for record in records)


def test_import_result_can_be_read_after_restart_and_other_chat_cannot_read_it(tmp_path):
    paths, _ = instance(tmp_path)
    native = NativeOnlyBot()
    async def exercise():
        with bind_conversation(ConversationScope('A', 0, origin='telegram')):
            controller = BotBackups(namespace(paths, native))
            job, _ = controller.operations.create('import', 'bot-import-result-fixture')
            controller.operations.update(job['id'], state='completed', bot_chat_id=1)
            restarted = BotBackups(namespace(paths, native))
            message = Message()
            await restarted.handle(None, SimpleNamespace(message=message), 'backup_status:' + job['id'])
            assert '导入完成' in message.edits[-1][0]
            message.chat_id = 2
            with pytest.raises(ValueError, match='不属于'):
                await restarted.handle(None, SimpleNamespace(message=message), 'backup_status:' + job['id'])
    asyncio.run(exercise())


def test_more_settings_second_page_has_native_backup_buttons():
    result = run_in_app('''
first=bot.get_more_settings_menu(1)
second=bot.get_more_settings_menu(2)
print(json.dumps({'first':[b.callback_data for row in first.inline_keyboard for b in row],
                  'second':[b.callback_data for row in second.inline_keyboard for b in row]}))
''')
    assert 'menu_more_settings:2' in result['first']
    assert {'menu_backup_export', 'menu_backup_import'} <= set(result['second'])
    assert 'menu_more_settings' in result['second']


def test_web_and_cli_native_menus_keep_conversation_export_while_bot_gets_data_backups():
    result = run_in_app('''
from xgent_app.conversations import ConversationScope,bind_conversation
menus={}
for origin in ('telegram','web','cli'):
    with bind_conversation(ConversationScope('global_memory',0,origin=origin)):
        menus[origin]=[b.callback_data for row in bot.get_more_settings_menu(2).inline_keyboard for b in row]
print(json.dumps(menus))
''')
    assert 'menu_backup_export' in result['telegram'] and 'menu_backup_import' in result['telegram']
    assert all('cmd_export_all' in result[origin] and 'menu_backup_export' not in result[origin] for origin in ('web', 'cli'))


@pytest.mark.parametrize('fail', [False, True])
def test_bot_import_guard_is_persisted_for_detached_coordinator_without_launching_any_service(tmp_path, monkeypatch, fail):
    from xgent_app import data_operations
    paths, _ = instance(tmp_path)
    (paths.code/'install.sh').write_text('# fixture only')
    operations = DataOperations({'DATA_PATHS': paths})
    job, _ = operations.create('import', 'bot-import-activation-fixture')
    operations.update(job['id'], state='ready', staging=str(tmp_path/'staging-not-activated'))
    before = paths.env.read_bytes()
    monkeypatch.setattr(data_operations, 'os', SimpleNamespace(name='posix'))
    launch = Mock(side_effect=OSError('fixture launch error') if fail else None)
    monkeypatch.setattr(data_operations, 'subprocess', SimpleNamespace(Popen=launch, DEVNULL=data_operations.subprocess.DEVNULL))
    if fail:
        from xgent_app.data_bundles import BundleError
        with pytest.raises(BundleError, match='未能启动'):
            operations.activate({'id': job['id'], 'confirm_replace': True, 'preserve_environment': True})
        assert operations.status(job['id'])['state'] == 'failed'
    else:
        operations.activate({'id': job['id'], 'confirm_replace': True, 'preserve_environment': True})
        saved = json.loads(operations.job_path(job['id']).read_text(encoding='utf-8'))
        assert saved['preserve_environment'] is True
        assert 'xgent_app.data_restore' in launch.call_args.args[0]
    assert paths.env.read_bytes() == before
