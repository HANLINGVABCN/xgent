import tempfile
import unittest
from tests.test_compression_requests import probe


class ToolContextTests(unittest.TestCase):
    def check(self, name, count):
        with tempfile.TemporaryDirectory() as directory:
            result = probe(name, directory, "lossless_context_probe")
            self.assertEqual(count, len(result))
            self.assertTrue(all(result.values()))

    def test_ui_records_do_not_consume_effective_history_depth(self):
        self.check("depth", 2)

    def test_read_text_and_native_payload_replay_preserves_originals_across_providers(self):
        self.check("tool_replay", 5)

    def test_all_standard_tool_results_replay_instead_of_display_cards(self):
        self.check("standard_results", 6)

    def test_files_shell_sendfile_and_ask_replay_the_actual_model_messages(self):
        self.check('nonstandard_results', 8)

    def test_retained_native_binary_survives_restart_and_compression(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(all(probe('replay_saved', directory, 'lossless_context_probe').values()))
            self.assertTrue(all(probe('replay_restarted', directory, 'lossless_context_probe').values()))
            self.assertTrue(all(probe('compressed_restarted', directory, 'lossless_context_probe').values()))


class ToolContextSnapshotTests(unittest.TestCase):
    def test_retained_attachment_outside_depth_keeps_its_caller_and_other_results(self):
        from xgent_app.tool_context import freeze_tool_message, messages_from_metadata, restore_tool_context
        import base64
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def save(name, raw):
                path = root / name
                path.write_bytes(raw)
                return {'abs_path': str(path)}
            calls = [{'id': cid, 'name': 'read_file', 'arguments': {'path': 'old.pdf'},
                      'run_id': 'run', 'response_id': 'response'} for cid in ('first', 'second')]
            messages = [{'role': 'assistant', 'content': '', 'native_calls': calls,
                         'native_binding': ['openai', 'p', 'm', 'run']},
                {'role': 'user', 'content': [{'type': 'binary', 'mime_type': 'application/pdf', 'filename': 'old.pdf',
                    'data': base64.b64encode(b'%PDF-1.4 retained').decode('ascii')}], 'native_result': {
                    'id': 'first', 'run_id': 'run', 'response_id': 'response'}},
                {'role': 'user', 'content': 'OTHER_ACTUAL_RESULT', 'native_result': {
                    'id': 'second', 'run_id': 'run', 'response_id': 'response'}}]
            rows = [{'id': index + 1, 'metadata': {'model_context': freeze_tool_message(message, save)}}
                    for index, message in enumerate(messages)]
            recent = [{'role': 'user', 'content': 'RECENT_ONLY'}]
            restored = restore_tool_context(recent, rows, root)
            self.assertEqual(4, len(restored))
            self.assertEqual(2, len(restored[0]['native_calls']))
            self.assertEqual('OTHER_ACTUAL_RESULT', restored[2]['content'])
            self.assertEqual('RECENT_ONLY', restored[-1]['content'])
            self.assertNotIn('_tool_context_part', str(restored))

    def test_native_bytes_round_trip_and_readable_archive_reference(self):
        import base64
        import json
        from pathlib import Path
        from xgent_app.tool_context import freeze_tool_message, messages_from_metadata, restore_tool_context
        from xgent_app.compression import attachment_index, format_records
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def save(name, raw):
                path = root / name
                path.write_bytes(raw)
                return {'abs_path': str(path)}
            raw = b'%PDF-1.7 native binary content'
            message = {'role': 'user', 'content': [
                {'type': 'text', 'text': 'actual tool result'},
                {'type': 'binary', 'filename': 'source.pdf', 'mime_type': 'application/pdf',
                 'data': base64.b64encode(raw).decode()},
            ]}
            payload = freeze_tool_message(message, save)
            self.assertNotIn(base64.b64encode(raw).decode(), json.dumps(payload))
            self.assertEqual(raw, Path(payload['assets'][0]['path']).read_bytes())
            row = {'id': 1, 'msg_type': 'agent_result', 'content': 'UI CARD',
                   'metadata': {'model_context': payload}}
            replay = restore_tool_context(messages_from_metadata(row['metadata'], 1), [row], root)
            self.assertEqual(message['content'], replay[0]['content'])
            self.assertIn('actual tool result', format_records([row]))
            self.assertEqual(payload['assets'][0]['path'], attachment_index([row])[0]['path'])

    def test_invalid_metadata_or_changed_payload_is_not_silently_dropped(self):
        from xgent_app.tool_context import messages_from_metadata
        from xgent_app.attachments import AttachmentContextError
        for payload in ({'version': 99}, {'version': 1, 'messages': None},
                        {'version': 1, 'messages': [{'role': 'user'}]}):
            with self.assertRaises(AttachmentContextError):
                messages_from_metadata({'model_context': payload})
