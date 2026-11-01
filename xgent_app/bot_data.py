"""Native Bot backups over the same local service as Web; no Web App or model."""
from __future__ import annotations

import asyncio
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .data_archives import FORMATS
from .data_operations import DataOperations
from .presentation import message_presentation
from .conversations import conversation_snapshot, replay_conversation
from .ui_history import without_ui_history

NOTICE = ('全部实例数据（以备份包含的内容为准），排除整份 .env。\n'
          '本机 Bot Token、用户 ID 和其他 .env 变量保留不变。\n'
          '备份仍包含数据库里的模型 API 密钥和登录配置，请自行妥善保管。')
PHASES = {'pending': '准备中', 'snapshotting': '正在创建数据库快照', 'packing': '正在压缩',
          'retrying': '文件变化，正在重试', 'verifying': '正在扫描和校验', 'verified': '校验通过',
          'backing_up': '正在保存导入前自动备份', 'activating': '正在恢复数据', 'restarting': '正在重启服务',
          'starting': '正在启动服务', 'cancelled': '已取消', 'rolled_back': '已恢复原数据'}


def export_keyboard(nonce):
    return InlineKeyboardMarkup([[InlineKeyboardButton(spec['label'], callback_data='backup_export:' + key + ':' + nonce)]
        for key, spec in FORMATS.items() if not spec.get('legacy')] +
        [[InlineKeyboardButton('🔙 返回', callback_data='menu_more_settings:2')]])


class BotBackups:
    def __init__(self, namespace):
        self.ns = namespace
        self.operations = DataOperations(namespace)
        self.cards = {}
        self.tasks = set()
        self.active_import = None

    def start(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def handle(self, context, query, data):
        message = query.message
        key = (message.chat_id, message.message_id)
        if data.startswith('backup_status:'):
            job = self.operations.status(data.split(':', 1)[1])
            if job.get('bot_chat_id') != message.chat_id:
                raise ValueError('这个备份任务不属于当前聊天')
            if job['state'] == 'completed':
                text = '导入完成，服务启动正常。' if job['kind'] == 'import' else '备份已生成。'
            elif job['state'] == 'failed' or job.get('bot_error'):
                from .error_reporting import error_text
                text = '操作未完成：' + error_text(job.get('error') or job.get('bot_error') or '请检查恢复状态')
            else:
                text = PHASES.get(job.get('phase'), job.get('phase') or '正在处理')
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton('刷新结果', callback_data='backup_status:' + job['id'])],
                [InlineKeyboardButton('🔙 返回', callback_data='menu_more_settings:2')]])
            if len(text) + len(NOTICE) >= 3800:
                bridge = self.ns['build_trigger_delivery_bot'](message.chat_id)
                await self.ns['safe_send_message'](self.ns['_SelfTriggerContext'](bridge), message.chat_id, text)
                text = '操作未完成，原始错误已发送。'
            await message.edit_text(text + '\n\n' + NOTICE, reply_markup=keyboard)
            return
        if data == 'menu_backup_export':
            nonce = uuid.uuid4().hex
            self.cards[key] = {'nonce': nonce}
            await message.edit_text('📤 导出数据\n\n' + NOTICE + '\n\n请选择压缩模式：', reply_markup=export_keyboard(nonce))
            return
        if data == 'menu_backup_import' or data.startswith('backup_page:'):
            page = int(data.split(':', 1)[1]) if data.startswith('backup_page:') else 0
            catalog = await asyncio.to_thread(self.operations.list_backups)
            items = catalog['items']
            page = max(0, min(page, max(0, (len(items) - 1) // 6)))
            rows = []
            nonce = uuid.uuid4().hex
            for item in items[page * 6:page * 6 + 6]:
                action = self.ns['CallbackDataStore'].store('backup_import:' + nonce + ':' + item['name'])
                rows.append([InlineKeyboardButton(item['name'], callback_data=action)])
            navigation = []
            if page:
                navigation.append(InlineKeyboardButton('上一页', callback_data=f'backup_page:{page - 1}'))
            if (page + 1) * 6 < len(items):
                navigation.append(InlineKeyboardButton('下一页', callback_data=f'backup_page:{page + 1}'))
            if navigation:
                rows.append(navigation)
            rows.append([InlineKeyboardButton('🔙 返回', callback_data='menu_more_settings:2')])
            self.cards[key] = {'nonce': nonce}
            await message.edit_text('📥 导入数据\n\n' + NOTICE +
                '\n\n选择备份后会完整校验，自动备份当前数据，然后导入并重启服务。' +
                (f'\n第 {page + 1} 页，共 {len(items)} 个备份。' if items else '\n当前没有可导入的备份。'),
                reply_markup=InlineKeyboardMarkup(rows))
            return
        if data.startswith('backup_export:'):
            _, format, nonce = data.split(':', 2)
            card = self.cards.get(key, {})
            if card.get('nonce') != nonce:
                raise ValueError('备份菜单已变化，请重新选择')
            if card.get('started'):
                return
            if format not in FORMATS or FORMATS[format].get('legacy'):
                raise ValueError('请选择当前支持的压缩模式')
            job = await self.operations.export({'request_id': 'bot-export-' + nonce,
                'archive_format': format, 'include_command_outputs': True, 'include_prompts': True,
                'include_environment': False, 'confirm_secrets': True})
            self.operations.update(job['id'], bot_chat_id=message.chat_id)
            self.cards[key] = {'active': True, 'started': True, 'nonce': nonce, 'id': job['id'], 'kind': 'export'}
            await message.edit_text('📤 正在导出 · ' + FORMATS[format]['label'] + '\n\n' + NOTICE, reply_markup=None)
            self.start(self.watch(message, key, job['id'], 'export', conversation_snapshot()))
        elif data.startswith('backup_import:'):
            _, nonce, name = data.split(':', 2)
            card = self.cards.get(key, {})
            if card.get('nonce') != nonce:
                raise ValueError('备份列表已变化，请重新选择')
            if card.get('started'):
                return
            if self.active_import is not None:
                raise ValueError('已有数据导入正在进行，请等待完成')
            job = await self.operations.import_stored({'request_id': 'bot-import-' + nonce, 'name': name})
            self.operations.update(job['id'], bot_chat_id=message.chat_id)
            self.cards[key] = {'active': True, 'started': True, 'nonce': nonce, 'id': job['id'], 'kind': 'import'}
            self.active_import = job['id']
            await message.edit_text('📥 正在校验备份：' + name + '\n\n' + NOTICE +
                '\n校验通过后自动备份当前数据并导入；服务会短暂停止后重新启动。', reply_markup=None)
            self.start(self.watch(message, key, job['id'], 'import', conversation_snapshot()))

    @without_ui_history
    async def watch(self, message, key, identifier, kind, route):
        with replay_conversation(route), message_presentation({'kind': 'system_op', 'purpose': 'status',
                'audience': ['telegram'], 'model_context': False}):
            try:
                previous = None
                while True:
                    state = self.operations.status(identifier)
                    if state['state'] == 'failed':
                        raise RuntimeError(state.get('error') or '备份操作失败')
                    if state['state'] == 'cancelled':
                        if self.cards.get(key, {}).get('id') == identifier:
                            await message.edit_text('备份操作已取消。\n\n' + NOTICE,
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 返回', callback_data='menu_more_settings:2')]]))
                        return
                    if state['state'] in {'completed', 'ready'}:
                        break
                    phase = state.get('phase')
                    if phase != previous and self.cards.get(key, {}).get('id') == identifier:
                        await message.edit_text(('📤 导出数据' if kind == 'export' else '📥 导入数据') +
                            '\n' + PHASES.get(phase, phase or '正在处理') + '\n\n' + NOTICE, reply_markup=None)
                        previous = phase
                    await asyncio.sleep(.6)
                if kind == 'export':
                    path = state['result']['path']
                    bridge = self.ns['build_trigger_delivery_bot'](message.chat_id)
                    context = self.ns['_SelfTriggerContext'](bridge)
                    notice = await self.ns['execute_sendfile_protocol'](path,
                        executor=self.ns['AgentExecutor'], context=context, chat_id=message.chat_id,
                        api_base_url=self.ns['BotConfig'].API_BASE_URL,
                        local_api_host_data_dir=self.ns['_LOCAL_API_HOST_DATA_DIR'],
                        local_api_container_data_dir=self.ns['_LOCAL_API_CONTAINER_DATA_DIR'],
                        max_file_size=self.ns['AgentExecutor'].MAX_FILE_SIZE,
                        safe_send_message=self.ns['safe_send_message'], safe_text=self.ns['safe_text'],
                        logger=self.ns['logger'], cancel_task_quietly=self.ns['cancel_task_quietly'])
                    if self.cards.get(key, {}).get('id') == identifier:
                        await message.edit_text('📤 备份已生成\n' + NOTICE + '\n\n文件发送：' + notice.removeprefix('[sendfile结果] '),
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 返回', callback_data='menu_more_settings:2')]]))
                else:
                    if self.cards.get(key, {}).get('id') == identifier:
                        await message.edit_text('📥 校验通过，正在导入并重启服务。\n\n' + NOTICE,
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('查看导入结果', callback_data='backup_status:' + identifier)]]))
                    bridge = self.ns['build_trigger_delivery_bot'](message.chat_id)
                    if not await bridge.flush_telegram(timeout=5):
                        raise RuntimeError('导入通知尚未送达，本次未启动恢复；可重新选择备份。')
                    await asyncio.to_thread(self.operations.activate, {'id': identifier,
                        'confirm_replace': True, 'preserve_environment': True})
            except Exception as exc:
                from .error_reporting import error_text
                failure = '⚠️ ' + error_text(str(exc))
                state = self.operations.status(identifier)
                self.operations.update(identifier, bot_error=error_text(str(exc)))
                if kind == 'import' and state['state'] != 'activating':
                    if state.get('staging'):
                        await asyncio.to_thread(self.operations.bundles.discard_staging, state['staging'])
                    self.operations.update(identifier, state='failed', phase='failed', error=error_text(str(exc)))
                if self.cards.get(key, {}).get('id') == identifier and len(failure) + len(NOTICE) < 3800:
                    await message.edit_text(failure + '\n\n' + NOTICE,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 返回', callback_data='menu_more_settings:2')]]))
                else:
                    bridge = self.ns['build_trigger_delivery_bot'](message.chat_id)
                    await self.ns['safe_send_message'](self.ns['_SelfTriggerContext'](bridge), message.chat_id, failure)
            finally:
                activating = kind == 'import' and self.operations.status(identifier)['state'] == 'activating'
                if kind == 'import' and not activating and self.active_import == identifier:
                    self.active_import = None
                if self.cards.get(key, {}).get('id') == identifier:
                    self.cards[key]['active'] = activating


async def handle(namespace, context, query, data):
    controller = namespace.get('_bot_backups')
    if controller is None:
        controller = namespace['_bot_backups'] = BotBackups(namespace)
    await controller.handle(context, query, data)
