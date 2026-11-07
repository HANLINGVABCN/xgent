"""Copy the reviewed frontend to the requested WSL instance and restart its PM2 app."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


DEPLOY = r'''
import datetime, hashlib, json, pathlib, shutil, subprocess, sys, time, urllib.request
source, requested, process, port = sys.argv[1:]
source = pathlib.Path(source).resolve(strict=True)
target = pathlib.Path(requested).resolve(strict=True)
if str(target) != '/home/hanling/xgent-telegram-test':
    raise SystemExit('Unexpected deployment destination: ' + str(target))
paths = ['README.md', 'docs', 'xgent_app/webui', 'xgent_app/web_server.py', 'xgent_app/workbench.py',
         'xgent_app/web_auth.py',
         'xgent_app/web_access.py', 'xgent_app/sections/callbacks.py', 'xgent_app/sections/ui.py', 'xgent_app/data_parts.py',
         'xgent_app/visual_pages.py', 'xgent_app/tool_calls.py',
         'xgent_app/generated_media.py', 'xgent_app/reply_presentation.py', 'xgent_app/telegram_rich.py', 'xgent_app/web_display.py',
         'xgent_app/sections/rendering.py',
         'xgent_app/web_history.py',
         'xgent_app/native_rendering.py', 'xgent_app/presentation_delivery.py', 'xgent_app/web_bridge.py',
         'xgent_app/protocols.py', 'xgent_app/prompt_defaults.py', 'xgent_app/sections/messages.py',
         'prompts/global_addon.txt', 'prompts/agent_addon.txt', 'prompts/agent_disabled_addon.txt',
         'requirements.txt', 'install.sh',
         'xgent_app/project_updates.py', 'xgent_app/sections/services.py',
         'xgent_app/sections/idle.py', 'xgent_app/queue_store.py', 'xgent_app/message_queue.py',
         'xgent_app/file_transfers.py', 'xgent_app/file_ingress.py',
         'xgent_app/conversations.py', 'xgent_app/conversation_store.py',
         'xgent_app/child_conversations.py', 'xgent_app/archive_conversations.py',
         'xgent_app/conversation_branching.py', 'xgent_app/attachment_version_api.py',
         'xgent_app/telegram_native.py',
         'xgent_app/sections/database.py', 'xgent_app/sections/SOURCE_BASELINE.sha256']
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
backup = target / 'workspace' / 'frontend-deploy' / stamp
backup.resolve().relative_to(target)
backup.mkdir(parents=True)
copied = 0
for name in paths:
    incoming, destination = source / name, target / name
    destination.resolve().relative_to(target)
    if destination.is_dir():
        shutil.copytree(destination, backup / name)
        shutil.copytree(incoming, destination, dirs_exist_ok=True)
        files = [f for f in incoming.rglob('*') if f.is_file()]
    else:
        (backup / name).parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.copy2(destination, backup / name)
        shutil.copy2(incoming, destination)
        files = [incoming]
    for item in files:
        deployed = target / item.relative_to(source)
        if hashlib.sha256(item.read_bytes()).digest() != hashlib.sha256(deployed.read_bytes()).digest():
            raise SystemExit('Deployment checksum mismatch: ' + str(item.relative_to(source)))
        copied += 1
revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
if not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain']):
    version_path = target / '.xgent-version'
    if version_path.is_file():
        shutil.copy2(version_path, backup / '.xgent-version')
    version_path.write_text(revision, encoding='utf-8')
subprocess.run(['/usr/local/bin/pm2', 'restart', process], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
url = 'http://127.0.0.1:' + port
local_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
deadline = time.monotonic() + 35
while True:
    try:
        with local_http.open(url + '/api/session', timeout=2) as response:
            assert response.status == 200
        with local_http.open(url + '/assets/design-system.css', timeout=2) as response:
            assert response.status == 200 and b'--header-h' in response.read()
        with local_http.open(url + '/assets/themes.css', timeout=2) as response:
            assert response.status == 200 and b'data-palette' in response.read()
        break
    except Exception:
        if time.monotonic() >= deadline:
            raise SystemExit('PM2 restarted, but Web verification timed out at ' + url)
        time.sleep(.7)
items = json.loads(subprocess.check_output(['/usr/local/bin/pm2', 'jlist']))
app = next(item for item in items if item['name'] == process)
print(json.dumps({'files_verified': copied, 'pm2': process, 'status': app['pm2_env']['status'],
                 'pid': app['pid'], 'web': url, 'backup': str(backup), 'source_revision': revision}, ensure_ascii=False))
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', default='Debian')
    parser.add_argument('--destination', default='/home/hanling/xgent-telegram-test')
    parser.add_argument('--process', default='xgent-telegram')
    parser.add_argument('--port', type=int, default=8790)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if sys.platform == 'win32':
        source = subprocess.check_output(
            ['wsl.exe', '-d', args.distribution, '--exec', 'wslpath', '-a', '-u', root.as_posix()],
            text=True, encoding='utf-8').strip()
        command = ['wsl.exe', '-d', args.distribution, '--exec', 'python3', '-c', DEPLOY]
    else:
        source = str(root)
        command = ['python3', '-c', DEPLOY]
    subprocess.run(command + [source, args.destination, args.process, str(args.port)], check=True)


if __name__ == '__main__':
    main()
