"""Stdlib private-repository downloads shared with the standalone installer."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_REPOSITORY = 'https://github.com/HANLINGVABCN/xgent'


def deployment_values(path):
    result = {}
    if not Path(path).is_file():
        return result
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.removeprefix('export ').split('=', 1)
        key, value = key.strip(), value.strip()
        if key not in {'UPDATE_ZIP_URL', 'UPDATE_GITHUB_TOKEN', 'GITHUB_TOKEN'}:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].strip()
        if isinstance(value, str):
            result[key] = value
    return result


def archive_url(repository=DEFAULT_REPOSITORY, branch='main'):
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?', repository)
    if match is None:
        raise ValueError('更新仓库必须是有效的 GitHub HTTPS 地址')
    return 'https://api.github.com/repos/' + match[1] + '/' + match[2] + '/zipball/' + urllib.parse.quote(branch, safe='')


def request_for(env_path, repository=DEFAULT_REPOSITORY, branch='main', *, force_repository=False):
    values = deployment_values(env_path)
    def selected(key):
        return os.environ.get(key) or values.get(key) or ''
    url = archive_url(repository, branch) if force_repository else (selected('UPDATE_ZIP_URL') or archive_url(repository, branch))
    if urllib.parse.urlsplit(url).scheme != 'https':
        raise ValueError('更新源必须使用 HTTPS')
    headers = {'User-Agent': 'XGent-private-updater', 'Accept': 'application/vnd.github+json'}
    host = (urllib.parse.urlsplit(url).hostname or '').lower()
    token = selected('UPDATE_GITHUB_TOKEN') or selected('GITHUB_TOKEN')
    if token and (host in {'github.com', 'api.github.com'} or host.endswith('.github.com')):
        headers.update(Authorization='Bearer ' + token, **{'X-GitHub-Api-Version': '2022-11-28'})
    return urllib.request.Request(url, headers=headers)


class ArchiveRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected is not None:
            host = (urllib.parse.urlsplit(newurl).hostname or '').lower()
            if not (host in {'github.com', 'api.github.com'} or host.endswith('.github.com')):
                redirected.remove_header('Authorization')
        return redirected


def download(env_path, repository, branch, target):
    request = request_for(env_path, repository, branch)
    size = 0
    with urllib.request.build_opener(ArchiveRedirect()).open(request, timeout=90) as source, open(target, 'wb') as output:
        while chunk := source.read(65536):
            size += len(chunk)
            if size > 200 * 1024 * 1024:
                raise ValueError('更新包超过 200MB，已中止')
            output.write(chunk)


if __name__ == '__main__':
    try:
        download(*sys.argv[1:])
    except urllib.error.HTTPError as exc:
        print(f'更新源访问失败（HTTP {exc.code}）；私人仓库请配置已授权该仓库的 UPDATE_GITHUB_TOKEN。', file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('更新下载失败，请检查更新源及网络。', file=sys.stderr)
        sys.exit(1)
