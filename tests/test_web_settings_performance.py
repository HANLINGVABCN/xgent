import tempfile
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from xgent_app import data_archives
from xgent_app.data_bundles import DataBundles
from xgent_app.data_paths import DataPaths

from tests.test_thinking_params import run_in_app


def test_regular_config_and_bootstrap_omit_avatar_bytes_and_keep_independent_revision():
    with tempfile.TemporaryDirectory() as root:
        result = run_in_app('''
import asyncio,base64,json
from tests.attachment_request_probe import Harness
from xgent_app.web_branding import DEFAULT_BRANDING,read_branding
from xgent_app.web_appearance import write_appearance
from xgent_app.workbench import Workbench
async def main():
    async with Harness(bot, %r) as h:
        source='data:image/png;base64,'+base64.b64encode(b'x'*1024*1024).decode()
        branding={**DEFAULT_BRANDING,'avatars':[{'id':'large-avatar','name':'large','mode':'upload','source':source}]}
        await bot._web_write_setting('web_branding',branding)
        public_settings=await bot._web_read_settings()
        bootstrap=await Workbench(vars(bot)).handle('GET','bootstrap',{})
        before=await read_branding(h.db)
        await write_appearance(h.db,'web_message_font_size',19)
        after=await read_branding(h.db)
        assert before['branding']==after['branding']==branding
        print(json.dumps({'settings_bytes':len(json.dumps(public_settings)), 'bootstrap_bytes':len(json.dumps(bootstrap)),
            'no_branding_in_general_config':'web_branding' not in public_settings['values'],
            'independent_revision':before['revision']==after['revision'],
            'preserved_image':after['branding']['avatars'][0]['source']==source,
            'no_model_requests':not h.requests}))
asyncio.run(main())
''' % root)
    assert result['settings_bytes'] < 50000 and result['bootstrap_bytes'] < 50000
    assert all(result[key] for key in ('no_branding_in_general_config', 'independent_revision', 'preserved_image', 'no_model_requests'))


def test_backup_estimates_reuse_samples_but_recalculate_changed_file_content(tmp_path):
    source=tmp_path/'memory'/'note.txt';source.parent.mkdir()
    source.write_bytes(b'original contents\n'*12000)
    service=DataBundles(DataPaths(tmp_path,tmp_path))
    with patch.object(data_archives,'_compress_sample',wraps=data_archives._compress_sample) as compress:
        first=service.estimate(categories=['memory'],compare_formats=True)
        second=service.estimate(categories=['memory'],compare_formats=True)
        assert first==second and compress.call_count==1
        previous=source.stat()
        source.write_bytes(b'changed contents!\n'*12000)
        os.utime(source,ns=(previous.st_atime_ns,previous.st_mtime_ns))
        service.estimate(categories=['memory'],compare_formats=True)
        assert compress.call_count==2
        source.write_bytes(b'larger contents\n'*24000)
        changed=service.estimate(categories=['memory'],compare_formats=True)
        assert changed['size']==source.stat().st_size and changed['size']!=first['size']
        assert compress.call_count==3


def test_parallel_estimates_share_compression_and_keep_total_estimates_independent():
    cache=data_archives.CompressionSamples()
    sample=b'same fixture sample\n'*5000
    with patch.object(data_archives,'_compress_sample',wraps=data_archives._compress_sample) as compress:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda size:data_archives.estimate_formats([],size,1,samples=[sample],sample_cache=cache),[100000,200000,300000]))
        assert compress.call_count==1
        assert results[0][0]['estimated_size']<results[1][0]['estimated_size']<results[2][0]['estimated_size']
