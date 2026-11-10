import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

from xgent_app.network_environment import apply_instance_network_environment


def test_blank_instance_proxies_remove_both_inherited_variants():
    env={'HTTP_PROXY':'http://127.0.0.1:7890','http_proxy':'http://127.0.0.1:7890',
         'HTTPS_PROXY':'http://127.0.0.1:7890','https_proxy':'http://127.0.0.1:7890',
         'ALL_PROXY':'http://127.0.0.1:7890','all_proxy':'http://127.0.0.1:7890',
         'NO_PROXY':'localhost','BOT_TOKEN':'keep-me'}
    apply_instance_network_environment({'HTTP_PROXY':'','HTTPS_PROXY':'','ALL_PROXY':''},env)
    assert env=={'NO_PROXY':'localhost','BOT_TOKEN':'keep-me'}


def test_instance_proxy_applies_consistently_without_removing_unconfigured_keys():
    env={'HTTPS_PROXY':'old','https_proxy':'old','HTTP_PROXY':'inherited','XGENT_IP_MODE':'old'}
    apply_instance_network_environment({'HTTPS_PROXY':' http://proxy.local:7890 ',
        'NO_PROXY':'localhost,127.0.0.1','XGENT_IP_MODE':'ipv4'},env)
    assert env['HTTPS_PROXY']==env['https_proxy']=='http://proxy.local:7890'
    assert env['HTTP_PROXY']=='inherited'
    assert env['NO_PROXY']==env['no_proxy']=='localhost,127.0.0.1'
    assert env['XGENT_IP_MODE']=='ipv4'


@pytest.mark.parametrize('disabled', [False, True])
def test_actual_cli_startup_uses_instance_direct_setting(tmp_path, disabled):
    root=Path(__file__).resolve().parents[1]
    shutil.copy2(root/'xgent_cli.py',tmp_path/'xgent_cli.py')
    (tmp_path/'.env').write_text('AUTHORIZED_USER_ID=1\nHTTP_PROXY=\nHTTPS_PROXY=\nALL_PROXY=\n',encoding='utf-8')
    env={**os.environ,'PYTHONPATH':str(root),'BOT_TOKEN':'123456:ISOLATED_TEST_ONLY',
        'AUTHORIZED_USER_ID':'1','PYTHONIOENCODING':'utf-8','NO_COLOR':'1','PYTHON_DOTENV_DISABLED':'1' if disabled else '0'}
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        env[key]='http://127.0.0.1:7890'
    code='import xgent_cli,os,json;print(json.dumps({k:os.environ.get(k) for k in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy")}))'
    result=subprocess.run([sys.executable,'-c',code],cwd=tmp_path,env=env,text=True,encoding='utf-8',capture_output=True,timeout=25)
    assert result.returncode==0,result.stderr
    import json
    expected={'http://127.0.0.1:7890'} if disabled else {None}
    assert set(json.loads(result.stdout.strip().splitlines()[-1]).values())==expected


def test_later_instance_file_overrides_legacy_case_variant():
    env = {}
    apply_instance_network_environment({'HTTPS_PROXY': 'http://legacy:7890'}, env)
    apply_instance_network_environment({'https_proxy': ''}, env)
    assert env == {}
