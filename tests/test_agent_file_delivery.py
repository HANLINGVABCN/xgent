from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from xgent_app.agent_file_delivery import present_written_agent_file


class AgentFileDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "out.txt"
        self.path.write_text("hello", encoding="utf-8")
        self.context = Mock()
        self.context.bot.send_document = AsyncMock()
        self.safe_send = AsyncMock()

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def _written(self, *, size=5, filename="out.txt", existed=False):
        return {
            "path": str(self.path),
            "filename": filename,
            "size": size,
            "existed": existed,
        }

    async def test_text_file_shows_write_result_without_sending_file(self):
        notice = await present_written_agent_file(
            self._written(),
            protocol="file",
            context=self.context,
            chat_id=1,
            safe_send_message=self.safe_send,
            safe_text=str,
            html_parse_mode="HTML",
        )
        self.assertIn("[file结果]", notice)
        self.assertIn("新建", notice)
        self.context.bot.send_document.assert_not_awaited()
        self.safe_send.assert_awaited_once()
        self.assertEqual(self.safe_send.await_args.args[2], f'✅ 已写入 · {self.path}')
        self.assertEqual(self.path.read_text(), 'hello')

    async def test_base64_file_does_not_upload_or_expose_encoded_content(self):
        await present_written_agent_file(
            self._written(),
            protocol="file:base64",
            context=self.context,
            chat_id=1,
            safe_send_message=self.safe_send,
            safe_text=str,
            html_parse_mode="HTML",
        )
        self.context.bot.send_document.assert_not_awaited()
        self.assertEqual(self.safe_send.await_args.args[2], f'✅ 已写入 · {self.path}')

    async def test_large_write_has_the_same_brief_result_and_no_upload_limit_warning(self):
        notice = await present_written_agent_file(
            self._written(size=100),
            protocol="file:base64",
            context=self.context,
            chat_id=1,
            safe_send_message=self.safe_send,
            safe_text=str,
            html_parse_mode="HTML",
        )
        self.assertIn("[file:base64结果]", notice)
        self.context.bot.send_document.assert_not_awaited()
        self.safe_send.assert_awaited_once()
        self.assertEqual(self.safe_send.await_args.args[2], f'✅ 已写入 · {self.path}')
        self.assertNotIn('超过', self.safe_send.await_args.args[2])


if __name__ == "__main__":
    unittest.main()
