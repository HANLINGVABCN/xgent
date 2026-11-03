"""Exercise the reported media/file/form workflow through the actual Agent loop."""
from unittest.mock import AsyncMock, patch

from PIL import Image

from tests.native_tool_probe import NativeHarness, call
from xgent_app.web_history import build_history_message
from xgent_app.presentation import metadata_dict


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
            ([call('send_file', 'send-text', path=str(source)), call('send_file', 'send', path=str(image))], ''),
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
        assert files[0]['content'].startswith('📄 toolcall_all_test.txt (')
        assert files[1]['content'].startswith('📄 fixture.png (')
        assert all(len(message['media']) == 1 for message in files)
        assert [message['media'][0]['kind'] for message in files] == ['file', 'photo']
        # Web previews by MIME while Telegram still delivers the original document.
        assert all(message['media'][0]['delivery_kind'] == 'file' for message in files)
        assert all(message['media'][0].get('download_url') for message in files)
        assert all(message.get('web_live', {}).get('message_ids') for message in files)
        snapshots = {frame['record_id']: frame for frame in frames if frame.get('type') == 'record_snapshot'}
        for message in files:
            assert snapshots[message['id']]['media'] == message['media']
            assert snapshots[message['id']]['web_live'] == message['web_live']
        written = [message for message in history if 'file-write-result' in str(message.get('web_display'))]
        assert len(written) == 1 and written[0]['media'] == [], written
        assert '✅ 已写入' in written[0]['content']
        assert not written[0].get('file_message')
        replies = [message for message in history if message['msg_type'] == 'ai_reply']
        assert len(replies) == 5, replies
        for message in replies:
            assert message['web_display']['segments'], message
        assert 'local media fixture' in str(replies[0]['web_display'])
        assert source.read_text() == 'status: complete\n'
        assert any(message.get('ask_form', {}).get('status') == 'pending' for message in history)
        return {'frames': frames, 'history': history, 'style': style}


async def write_without_upload(bot, root, mode, style):
    import base64
    import os
    async with NativeHarness(bot, root, 'openai', style) as h:
        await bot.UserDataManager.save_config('agent_call_mode', mode)
        path, binary = h.root/'created.txt', h.root/'created.bin'
        text, raw = 'first line\n  second line', b'\x00\xffbinary payload\x00'
        encoded = base64.b64encode(raw).decode()
        if mode == 'toolcall':
            h.responses = [([call('write_file', 'text', path=str(path), content=text),
                call('write_binary', 'binary', path=str(binary), base64_data=encoded)], ''), ([], 'WRITES_DONE')]
        else:
            fence = f'```file-x:{path}\n<<BEGIN_TEXTWRITE123\n{text}\n<<END_TEXTWRITE123\n```\n\n'
            fence += f'```file-x:base64:{binary}\n<<BEGIN_BINWRITE123\n{encoded}\n<<END_BINWRITE123\n```'
            h.responses = [([], fence), ([], 'WRITES_DONE')]
        await h.turn('create a text and binary file without sending them')
        frames = h.drain_frames()
        assert not [frame for frame in frames if frame['type'] in {'document', 'photo'}], frames
        rows = await h.db.get_display_history(100)
        assert not [row for row in rows if row['msg_type'] == 'runtime_error'], rows
        writes = [row for row in rows if metadata_dict(row.get('metadata')).get('file_write')]
        assert len(writes) == 2
        for row in writes:
            rendered = build_history_message(row, bot.ArtifactManager.ROOT_DIR, root)
            assert rendered['media'] == [] and '✅ 已写入' in rendered['content']
            assert not rendered.get('file_message')
        # Preserve the existing fence writer's platform newline convention.
        expected = text if mode == 'toolcall' else text.replace('\n', os.linesep)
        assert path.read_bytes() == expected.encode()
        assert binary.read_bytes() == raw
        return {'written_exactly': True, 'no_upload': True, 'mode': mode, 'style': style}
