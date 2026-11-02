"""CLI acceptance in a copied temporary instance, without services or keys."""
import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ChildConversationCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xgent-child-cli-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('xgent_app', 'prompts'):
            shutil.copytree(ROOT / name, self.root / name, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy(ROOT / 'xgent_conversation.py', self.root)
        skill = self.root / 'skill-public'
        shutil.copytree(ROOT / 'skill-public/script/background-assistant', skill / 'script/background-assistant')
        shutil.copy(ROOT / 'skill-public/background-assistant.md', skill)

    def run_cli(self, *args, wrapper=False):
        entry = self.root / ('skill-public/script/background-assistant/background_assistant.py' if wrapper else 'xgent_conversation.py')
        process = subprocess.run([sys.executable, str(entry), *args], cwd=self.root,
            env={**os.environ, 'BOT_TOKEN': '', 'AUTHORIZED_USER_ID': '1', 'PYTHON_DOTENV_DISABLED': '1',
                 'PYTHONIOENCODING': 'utf-8', 'XGENT_CONVERSATION_ID': 'global_memory'},
            capture_output=True, text=True, encoding='utf-8', timeout=90)
        return process, json.loads((process.stdout.strip() or process.stderr.strip()).splitlines()[-1])

    def test_create_and_submit_do_not_require_web_or_execute_models(self):
        process, child = self.run_cli('create', '--name', '独立的子对话')
        self.assertEqual(0, process.returncode, process.stderr)
        process, job = self.run_cli('send', '--conversation', child['conversation_id'], '--message', '仅登记任务', '--request-id', 'send-retry')
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual('pending', job['status'])
        process, retry = self.run_cli('send', '--conversation', child['conversation_id'], '--message', '仅登记任务', '--request-id', 'send-retry')
        self.assertEqual(job, retry)
        with closing(sqlite3.connect(self.root / 'xgent_memory.db')) as conn:
            self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM global_messages').fetchone()[0])
            self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM chat_sessions').fetchone()[0])
            self.assertEqual('global_memory', json.loads(conn.execute("SELECT value FROM config WHERE key='current_chat_id'").fetchone()[0]))

    def test_delegate_registers_trigger_and_keeps_multiline_prompt_exact(self):
        prompt = self.root / '任务.txt'
        text = '完整任务\r\n  $a = "test|pipe"\n单引号\'、反引号`与中文\r\n'
        prompt.write_bytes(text.encode('utf-8'))
        process, job = self.run_cli('delegate', '--message-file', str(prompt), '--request-id', 'delegate-retry', wrapper=True)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertTrue(job['trigger_task_id'])
        with closing(sqlite3.connect(self.root / 'xgent_memory.db')) as conn:
            self.assertEqual(text, conn.execute('SELECT text FROM conversation_jobs').fetchone()[0])
            command, parent = conn.execute('SELECT command,conversation_id FROM trigger_tasks').fetchone()
            self.assertIn('wait', command)
            self.assertIn('delegate-retry', command)
            self.assertEqual('global_memory', parent)
        process, status = self.run_cli('wait', '--request-id', job['request_id'], '--timeout', '0')
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertFalse(status['complete'])
        self.assertTrue(status['timed_out'])
        process, cancelled = self.run_cli('cancel', '--request-id', job['request_id'])
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual('cancelled', cancelled['status'])
        process, failure = self.run_cli('wait', '--request-id', job['request_id'], '--timeout', '0')
        self.assertEqual(1, process.returncode)
        self.assertEqual('cancelled', json.loads(process.stdout)['status'])

    def test_disabled_public_skill_does_not_disable_the_shared_command(self):
        process, _ = self.run_cli('create', '--name', '初始化')
        self.assertEqual(0, process.returncode)
        with closing(sqlite3.connect(self.root / 'xgent_memory.db')) as conn:
            conn.execute('INSERT OR REPLACE INTO config(key,value) VALUES(?,?)', ('disabled_skills', '["background-assistant.md"]'))
            conn.commit()
        process, error = self.run_cli('delegate', '--message', '不应该创建', wrapper=True)
        self.assertEqual(1, process.returncode)
        self.assertFalse(error['ok'])
        process, job = self.run_cli('send', '--message', '通用命令仍可使用')
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual('pending', job['status'])

    def test_system_python_uses_the_project_runtime_and_keeps_the_skill_tag(self):
        subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages', '--without-pip', str(self.root / 'venv')],
                       check=True, capture_output=True, timeout=90)
        process, job = self.run_cli('delegate', '--message', '使用项目运行环境', wrapper=True)
        self.assertEqual(0, process.returncode, process.stderr)
        with closing(sqlite3.connect(self.root / 'xgent_memory.db')) as conn:
            command = conn.execute('SELECT command FROM trigger_tasks WHERE id=?', (job['trigger_task_id'],)).fetchone()[0]
            python = self.root / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python3')
            self.assertIn(str(python), command)
            self.assertEqual('background-assistant.md', conn.execute('SELECT source_skill FROM conversation_jobs').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
