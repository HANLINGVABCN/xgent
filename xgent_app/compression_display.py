"""Transient compression output; committing a summary remains the DB's job."""
from contextlib import ExitStack, suppress
from contextvars import ContextVar
from dataclasses import replace

from .presentation import PresentationTurn, message_presentation, presentation_turn
from .presentation_delivery import PresentationBot, PresentationContext
from .response_modes import response_policy
from .web_display import build_web_display, web_display_scope

_current = ContextVar('compression_output', default=None)
_LABELS = {'foreground': '前台流式输出中...', 'background': '后台流式输出中...',
           'nonstream': '非流式输出中...'}


def current_compression_output():
    return _current.get()


class CompressionBot(PresentationBot):
    def _telegram_hint(self, hint, kind, previous=None):
        hint = dict(hint)
        mode = self.turn.response_policy.telegram_mode
        preview = hint.get('telegram_content') or {}
        if kind == 'ai_reply' and (hint.get('purpose') == 'generation' or preview.get('complete') is False):
            text = _LABELS[mode]
            if mode == 'background' and preview:
                text += f" 已生成 {len(str(preview.get('raw') or ''))} 字"
            if mode != 'foreground' or not preview:
                hint['telegram_display'] = {**hint.get('telegram_display', {}), 'text': text, 'parse_mode': None}
        return super()._telegram_hint(hint, kind, previous)


class _Context:
    def __init__(self, original, bot):
        self.original, self.bot = original, bot

    def __getattr__(self, name):
        return getattr(self.original, name)


class CompressionOutput:
    def __init__(self, namespace, context, chat_id, stop_event):
        self.ns, self.original_context = namespace, context
        self.chat_id, self.stop_event = chat_id, stop_event
        self.stack = ExitStack()
        self.renderer = self.status = None
        self.context, self.token = context, None

    async def open(self):
        from .conversations import bind_conversation, current_scope
        from .web_bridge import MirrorBot
        scope = current_scope()
        bot = self.original_context.bot
        origin = scope.origin
        if origin == 'legacy' and getattr(bot, '_is_xgent_web_bot', False):
            origin = 'web'
        if scope.origin == 'web':
            db = await self.ns['BotMemoryDB'].get_instance()
            selected = (await db.get_conversation_state()).get('telegram_conversation_id')
            # Compression is management input, but its generated reply follows
            # the same conversation route as chat. Other menus stay unchanged.
            self.stack.enter_context(bind_conversation(replace(scope,
                telegram_delivery=scope.conversation_id == selected)))
        if scope.origin == 'web' and not isinstance(bot, MirrorBot):
            bot = MirrorBot(getattr(bot, 'outbox', None), self.chat_id,
                real_bot=self.ns['get_web_real_bot'](), channel=self.ns['telegram_channel']())
        data = self.ns['UserDataManager']
        self.policy = response_policy({key: data.get(key) for key in
            ('stream_mode', 'stream_style', 'web_response_mode')}, origin)
        self.turn = PresentationTurn('folded')
        self.turn.response_policy = self.policy
        self.stack.enter_context(presentation_turn(self.turn))
        self.context = PresentationContext(_Context(self.original_context, bot), self.turn)
        self.context.bot = CompressionBot(bot, self.turn)
        self.token = _current.set(self)
        return self

    async def start(self, keyboard):
        self.context.bot.begin_telegram_generation(self.policy.generation_mode)
        with message_presentation({'kind': 'ai_reply', 'purpose': 'generation', 'transient': True}):
            self.status = await self.context.bot.send_message(chat_id=self.chat_id,
                text=_LABELS[self.policy.generation_mode], reply_markup=keyboard)
        if self.policy.generation_mode == 'foreground':
            self.renderer = self.ns['TelegramStreamRenderer'](
                self.context, self.chat_id, self.status, keyboard, 3900, self.stop_event)
            with message_presentation({'kind': 'ai_reply', 'purpose': 'generation', 'transient': True}):
                self.renderer.start()
        return self.status

    async def append(self, chunk):
        if self.renderer is not None:
            # Rendering failure cannot change model completion or commit rules.
            with suppress(Exception):
                await self.renderer.append(chunk)

    async def pause(self):
        if self.renderer is not None:
            await self.renderer.cancel()

    async def complete(self, entry, summary):
        """Finalize only after commit_compression has returned successfully."""
        await self.pause()
        record_id = entry['response_row_id']
        before = set(self.context.bot.messages)
        if self.status is None:
            with message_presentation({'kind': 'ai_reply', 'record_id': record_id}):
                sent = await self.ns['safe_send_message'](self.context, self.chat_id, summary)
            if not sent:
                return
            self.status = sent[0]
        with message_presentation({'kind': 'ai_reply', 'record_id': record_id,
                'telegram_content': {'raw': summary, 'complete': True, 'owner_id': self.status.message_id}}), \
                web_display_scope(build_web_display(summary, fold=True, reply_message_id=self.status.message_id)):
            if self.renderer is not None:
                self.renderer.response_parts = [summary]
                self.renderer.current_text = summary
                await self.renderer.remove_controls()
                ids = list(self.renderer.message_ids)
            else:
                await self.ns['finalize_text_response'](self.context, self.chat_id, self.status, summary)
                ids = [self.status.message_id, *[mid for mid in self.context.bot.messages if mid not in before]]
        self.turn.last_record_id = record_id
        db = await self.ns['BotMemoryDB'].get_instance()
        from .telegram_records import bind_record
        row = await db.get_display_message(record_id)
        if row is not None:
            await bind_record(db, row, ids)
        outbox = getattr(self.context.bot, 'outbox', None)
        if outbox is not None:
            await db.patch_display_metadata(record_id, {'web_live': {
                'epoch': outbox.snapshot()['epoch'], 'message_ids': ids},
                'reply_group_id': self.turn.reply_group_id})
        self.status.presentation_message_ids = ids
        await self.ns['publish_saved_reply'](self.context, record_id, reply=self.status)

    async def discard(self):
        """Remove only speculative generation slots, never the saved error."""
        await self.pause()
        if self.status is None and self.renderer is None:
            return
        messages = self.renderer._web_messages if self.renderer is not None else [self.status]
        for message in messages:
            if message is not None:
                with suppress(Exception):
                    await message.delete()
        self.context.bot._telegram_generation = None
        self.status = None

    async def close(self):
        try:
            await self.pause()
            finish = getattr(self.context.bot, 'finish_telegram_controls', None)
            if finish is not None:
                with suppress(Exception):
                    await finish()
        finally:
            if self.token is not None:
                _current.reset(self.token)
            self.stack.close()
