#!/usr/bin/env python3
"""Common child-conversation CLI. No Web server or Telegram login required."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid


def parser():
    root = argparse.ArgumentParser(description='XGent 子对话：创建、后台发送、读取真实结果。')
    sub = root.add_subparsers(dest='action', required=True)
    for action in ('create', 'send', 'delegate', 'status', 'wait', 'cancel', 'list'):
        command = sub.add_parser(action)
        command.add_argument('--parent', default=os.environ.get('XGENT_CONVERSATION_ID'), help='父对话；默认当前对话')
        if action in {'create', 'send', 'delegate'}:
            command.add_argument('--name', help='子对话名称')
            command.add_argument('--generation', type=int, default=os.environ.get('XGENT_CONVERSATION_GENERATION'))
        if action in {'send', 'delegate'}:
            command.add_argument('--conversation', help='复用已有子对话；省略则创建')
            message = command.add_mutually_exclusive_group(required=True)
            message.add_argument('--message', help='完整任务文字')
            message.add_argument('--message-file', help='从 UTF-8 文件读取完整任务')
        if action in {'create', 'send', 'delegate', 'status', 'wait', 'cancel'}:
            command.add_argument('--request-id', required=action in {'status', 'wait', 'cancel'}, help='重试时复用原请求 ID')
        if action == 'wait':
            command.add_argument('--timeout', type=float, default=None, help='只限制等待，不重发任务；默认持续等候')
    return root


def load_runtime(entry):
    from xgent_app.bootstrap import load_sections, migrate_legacy_runtime_paths
    migrate_legacy_runtime_paths(entry.parent)
    namespace = {'__file__': str(entry)}
    if os.environ.get('XGENT_CLI_DEBUG'):
        load_sections(namespace)
    else:
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                load_sections(namespace)
        except Exception:
            sys.stdout.write(captured.getvalue())
            raise
    return namespace


def shell_command(arguments):
    return subprocess.list2cmdline(arguments) if os.name == 'nt' else shlex.join(arguments)


def use_project_python(script):
    # A service launched with venv/bin/python need not activate that venv in
    # PATH. Keep an explicitly active environment, otherwise use the installed
    # project runtime. Re-execute the wrapper too, preserving its skill tag.
    runtime = Path(__file__).resolve().parent / 'venv'
    python = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python3')
    if sys.prefix == sys.base_prefix and (runtime / 'pyvenv.cfg').is_file() and python.is_file():
        os.execv(str(python), [str(python), str(Path(script).resolve()), *sys.argv[1:]])


async def execute(args, namespace, entry, *, source_skill=None):
    await namespace['UserDataManager'].init()
    db = await namespace['BotMemoryDB'].get_instance()
    parent_id = args.parent or (await db.get_conversation_state())['current_chat_id']
    try:
        if args.action == 'list':
            items = [item for item in await db.get_all_sessions() if item.get('owner_conversation_id') == parent_id]
            return {'ok': True, 'parent_conversation_id': parent_id, 'items': items}
        if args.action == 'create':
            return await db.create_child_conversation(parent_id, args.name, generation=args.generation,
                                                       request_id=args.request_id)
        if args.action in {'status', 'wait', 'cancel'}:
            if args.action == 'cancel':
                await db.cancel_conversation_job(args.request_id, parent_id)
                return await db.conversation_job_result(args.request_id, parent_id)
            deadline = time.monotonic() + max(0, args.timeout) if args.action == 'wait' and args.timeout is not None else None
            while True:
                result = await db.conversation_job_result(args.request_id, parent_id,
                    include_content=args.action == 'status')
                if args.action == 'status' or result['complete']:
                    return result if args.action == 'status' else await db.conversation_job_result(args.request_id, parent_id)
                if deadline is not None and time.monotonic() >= deadline:
                    return {**result, 'timed_out': True}
                await asyncio.sleep(min(1, max(0, deadline - time.monotonic())) if deadline is not None else 1)
        text = Path(args.message_file).read_bytes().decode('utf-8') if args.message_file else args.message
        request_id = args.request_id or uuid.uuid4().hex
        callback = None
        if args.action == 'delegate':
            command = shell_command([sys.executable, str(entry), 'wait', '--parent', parent_id, '--request-id', request_id])
            definition = namespace['SelfTriggerManager']._compute_definition({
                'command': command, 'task': args.name or '子对话：' + ' '.join(text.split())[:60],
            })
            now = time.time()
            callback = {'id': 'trg_' + uuid.uuid4().hex[:12], 'chat_id': namespace['BotConfig'].AUTHORIZED_USER_ID,
                        'conversation_id': parent_id, **definition,
                        'status': 'scheduled' if definition['schedule_type'] in {'once', 'cron'} else 'pending',
                        'origin_user_text': text, 'created_at': now, 'updated_at': now}
        job = await db.submit_conversation_job(parent_id, text, request_id=request_id,
            conversation_id=args.conversation, name=args.name, generation=args.generation,
            source_skill=source_skill, callback=callback)
        if job['status'] not in {'pending', 'queued'}:
            return await db.conversation_job_result(job['id'], parent_id)
        # Admission happens in the serving process; do not start queue/model
        # runners here or wait for the model from the parent's command.
        return {'ok': True, 'request_id': job['id'], 'parent_conversation_id': parent_id,
                'conversation_id': job['conversation_id'], 'trigger_task_id': job['trigger_task_id'],
                'status': job['status'], 'complete': False}
    finally:
        await db.close()


def main(argv=None, *, source_skill=None):
    args = parser().parse_args(argv)
    if argv is None:
        use_project_python(sys.argv[0])
    entry = Path(__file__).resolve()
    namespace = {}
    try:
        namespace = load_runtime(entry)
        result = asyncio.run(execute(args, namespace, entry, source_skill=source_skill))
    except Exception as exc:
        redact = namespace.get('redact_sensitive_text', str)
        print(json.dumps({'ok': False, 'error': redact(str(exc)), 'error_type': type(exc).__name__},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 1 if args.action in {'wait', 'send', 'delegate'} and result.get('complete') and not result.get('ok') else 0


if __name__ == '__main__':
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
