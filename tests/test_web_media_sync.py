import asyncio
import json
from pathlib import Path

import pytest
from PIL import Image
from telegram import Bot
from telegram.request import BaseRequest
from xgent_app.fanout import Op
from xgent_app.telegram_native import OP_NATIVE_MEDIA
from xgent_app.web_bridge import deliver_op_to_bot
from tests.test_thinking_params import run_in_app


@pytest.mark.parametrize('style', ['nonstream', 'foreground', 'background'])
def test_web_generated_media_is_sent_and_linked_to_telegram(tmp_path, style):
    result = run_in_app('import asyncio\nfrom tests.web_media_sync_probe import generated_to_bot\n' +
                        f'print(json.dumps(asyncio.run(generated_to_bot(bot, {str(tmp_path)!r}, {style!r}))))')
    assert result['media_count'] == 1 and result['associated']


class CapturedApiRequest(BaseRequest):
    def __init__(self):
        self.calls = []

    @property
    def read_timeout(self):
        return 10

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        parameters = dict(request_data.parameters)
        files = request_data.multipart_data
        if isinstance(parameters.get('rich_message'), str):
            parameters['rich_message'] = json.loads(parameters['rich_message'])
        self.calls.append((url.rsplit('/', 1)[-1], parameters, files))
        return 200, json.dumps({'ok': True, 'result': {'message_id': 900, 'date': 1,
            'chat': {'id': 1, 'type': 'private'}, 'text': 'sent'}}).encode()


@pytest.mark.parametrize('thread_id', [None, 55])
def test_media_uses_actual_sdk_multipart_and_keeps_topic_out_of_transport_options(tmp_path, thread_id):
    image = tmp_path / 'image.png'
    Image.new('RGB', (32, 24), 'blue').save(image)
    async def exercise():
        api = CapturedApiRequest()
        bot = Bot('900:fixture', request=api)
        op = Op(OP_NATIVE_MEDIA, logical_id=1000, chat_id=1, payload={
            'artifacts': [{'path': str(image), 'mime_type': 'image/png'}], 'text': '图片说明',
            'kwargs': {'message_thread_id': thread_id} if thread_id else {},
            'telegram_native': {'phase': 'media'},
            '_conversation_context': {'conversation_id': 'fixture', 'telegram_delivery': True,
                'telegram_bot_id': 900, 'telegram_chat_id': 1, 'telegram_thread_id': thread_id,
                'origin': 'web' if thread_id else 'legacy'}})
        try:
            assert await deliver_op_to_bot(bot, op, None) == 900
            method, parameters, files = api.calls[-1]
            assert method == 'sendRichMessage'
            assert parameters.get('message_thread_id') == thread_id
            media = parameters['rich_message']['media'][0]
            assert media['media']['type'] == 'photo'
            name = media['media']['media'].removeprefix('attach://')
            assert name in files
            assert 'tg://photo?id=' + media['id'] in parameters['rich_message']['html']
        finally:
            await bot.request.shutdown()
    asyncio.run(exercise())
