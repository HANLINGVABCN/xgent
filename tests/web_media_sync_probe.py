"""The production Web-origin media tool, delivered to a deterministic Bot API."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from tests.native_tool_probe import NativeHarness, call
from tests.telegram_rich_probe import RichCapture
from xgent_app.conversations import bind_conversation, current_scope
from xgent_app.interaction import interaction
from xgent_app.web_bridge import MirrorBot
from xgent_app.presentation import metadata_dict


async def generated_to_bot(bot, root, style):
    async with NativeHarness(bot, root, 'vertex', style) as h:
        native = RichCapture()
        original_post = native._post
        async def post(method, data=None, **kwargs):
            if data and (data.get('rich_message') or {}).get('media'):
                for medium in data['rich_message']['media']:
                    field = medium['media']['media'].removeprefix('attach://')
                    assert field in data
                assert 'tg://photo' in data['rich_message']['html']
            return await original_post(method, data, **kwargs)
        native._post = post
        bridge = MirrorBot(h.outbox, 1, native)
        h.context.bot = bridge
        path = Path(bot.ArtifactManager.GENERATED_MEDIA_DIR) / '2026-11-01' / 'image.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (32, 24), 'blue').save(path)
        h.responses = [([call('generate_media', 'draw', prompt='a cat')], ''), ([], 'FINAL_ANSWER')]
        result = {'success': True, 'file_path': str(path), 'mime_type': 'image/png', 'text': '图片文字',
                  'provider_name': 'image-fixture', 'model_name': 'fixture-model'}
        with interaction('web'), patch.object(bot, '_web_real_bot', native), \
                patch.object(bot, 'run_media_protocol', AsyncMock(return_value=result)), \
                patch.object(bot, 'get_web_outbox', return_value=h.outbox):
            scope = await bot.get_conversations().resolve()
            with bind_conversation(scope):
                await h.turn('draw a picture')
                assert await bridge.flush_telegram(5)
        texts = [message['text'] for message in native.messages.values()]
        media = [text for text in texts if 'tg://photo' in text]
        assert len(media) == 1, {'messages': texts, 'stats': bridge._tg_channel().stats()}
        assert '图片文字' in media[0]
        frames = h.drain_frames()
        rows = await h.db.get_display_history(100)
        media_rows = [row for row in rows if row['msg_type'] == 'media_reply']
        assert len(media_rows) == 1
        assert metadata_dict(media_rows[0]['metadata']).get('telegram_delivery', {}).get('ids'), media_rows
        await bridge._tg_channel().aclose()
        return {'media_count': len(media), 'associated': True, 'style': style}
