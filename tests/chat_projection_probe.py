"""Exercise the reported media/file/form workflow through the actual Agent loop."""
from unittest.mock import AsyncMock, patch

from PIL import Image

from tests.native_tool_probe import NativeHarness, call
from xgent_app.web_history import build_history_message


async def workflow(bot, root, style):
    async with NativeHarness(bot, root, 'gemini', style) as h:
        from pathlib import Path
        image = Path(bot.ArtifactManager.GENERATED_MEDIA_DIR) / '2026-11-01' / 'fixture.png'
        image.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (32, 24), 'blue').save(image)
        source = h.root / 'toolcall_all_test.txt'
        h.responses = [
            ([call('generate_media', 'image', prompt='local media fixture')], ''),
            ([call('write_file', 'write', path=str(source), content='status: pending\n')], ''),
            ([call('read_file', 'read', path=str(source)),
              call('edit_file', 'edit', path=str(source), old='pending', new='complete')], ''),
            ([call('send_file', 'send', path=str(image))], ''),
            ([call('ask_user', 'ask', questions=[{'label': 'Q1', 'type': 'text', 'prompt': 'Result?'}])], ''),
        ]
        media = {'success': True, 'file_path': str(image), 'mime_type': 'image/png',
                 'text': '已生成媒体', 'provider_name': 'fixture', 'model_name': 'image-fixture'}
        with patch.object(bot, 'run_media_protocol', AsyncMock(return_value=media)):
            await h.turn('check media, files, edits and forms')
        rows = await h.db.get_display_history(200)
        assert not [row for row in rows if row['msg_type'] == 'runtime_error'], rows
        frames = h.drain_frames()
        history = [build_history_message(row, bot.ArtifactManager.ROOT_DIR, str(root)) for row in rows]
        files = [message for message in history if message.get('file_message')]
        assert len(files) == 2, files
        assert files[0]['content'] == '📄 已写入服务器并发送: toolcall_all_test.txt'
        assert files[1]['content'].startswith('📄 fixture.png (')
        assert all(len(message['media']) == 1 and message['media'][0]['kind'] == 'file' for message in files)
        assert all(message.get('web_live', {}).get('message_ids') for message in files)
        replies = [message for message in history if message['msg_type'] == 'ai_reply']
        assert len(replies) == 5, replies
        for message in replies:
            assert message['web_display']['segments'], message
        assert 'local media fixture' in str(replies[0]['web_display'])
        assert source.read_text() == 'status: complete\n'
        assert any(message.get('ask_form', {}).get('status') == 'pending' for message in history)
        return {'frames': frames, 'history': history, 'style': style}
