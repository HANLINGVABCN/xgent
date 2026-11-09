import unittest
from pathlib import Path

import pytest

from tests.test_external_sync import ProbeMixin
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session


@pytest.fixture(scope='module')
def sendfile_cases():
    class Probe(ProbeMixin, unittest.TestCase):
        pass

    return Probe().run_probe(r'''
import asyncio,json,tempfile
from pathlib import Path
import xgent_server as bot
from tests.native_tool_probe import NativeHarness
from xgent_app.web_history import build_history_message
from xgent_app.presentation import metadata_dict
async def main():
    cases=[]
    with tempfile.TemporaryDirectory() as folder:
        for style in ('foreground','background','nonstream'):
            async with NativeHarness(bot,Path(folder)/style,'openai_compatible',style) as h:
                path=h.root/'交付文件.txt';path.write_text('ORIGINAL_FILE',encoding='utf-8')
                h.responses=[([{'id':'filecall','name':'send_file','arguments':{'path':str(path)}}],'给你文件'),([], '文件已交付')]
                await h.turn('发送文件')
                rows=await h.db.get_display_history(100)
                result=next(r for r in rows if r['msg_type']=='agent_result' and '[sendfile结果]' in r['content'])
                history=build_history_message(result,bot.ArtifactManager.ROOT_DIR,h.root)
                frames=h.drain_frames()
                live=[f for f in frames if f['type']=='record_snapshot' and f.get('record_id')==result['id']]
                assert live, (style,frames)
                snapshot=live[-1]
                assert snapshot['media']==history['media'] and snapshot['text']==history['content'],(style,snapshot,history)
                assert len(snapshot['media'])==1 and snapshot['media'][0]['filename']=='交付文件.txt'
                assert snapshot['media'][0]['download_url'] and '已加入 Telegram' not in snapshot['text']
                assert metadata_dict(result['metadata'])['web_live']['message_ids']
                assert snapshot['replace_message_ids'], snapshot
                media_ids=metadata_dict(result['metadata'])['web_live']['message_ids']
                cases.append({'name':style,'history':history,'snapshots':live,
                    'frames':[f for f in frames if f.get('message_id') in media_ids and f['type'] in {'document','photo'}]})
    print(json.dumps(cases))
asyncio.run(main())
''')


def test_native_send_file_publishes_same_card_before_refresh(sendfile_cases):
    assert len(sendfile_cases) == 3


def test_sendfile_browser_receives_card_once_and_keeps_it_after_refresh(full_output_server, sendfile_cases):
    server, _, _, _ = full_output_server
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        try:
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            for case in sendfile_cases:
                records = []
                async def history(limit):
                    return records
                server.config.read_history = history
                server.outbox.put({'type': 'history_reset'})
                target = base + '/#/chat?conversation=global_memory'
                if page.url == target:
                    page.reload()
                else:
                    page.goto(target)
                page.wait_for_function('!document.getElementById("btn-send").disabled')
                for frame in case['frames']:
                    server.outbox.put(frame)
                page.locator('.file-card').wait_for()
                for frame in case['snapshots']:
                    # Explicit sender IDs must work even after relay epoch changes.
                    frame = {**frame, 'web_live': {**frame.get('web_live', {}), 'epoch': 'old-relay-epoch'}}
                    server.outbox.put(frame)
                owner = page.locator(f'.msg-row[data-record-id="{case["history"]["id"]}"]')
                owner.wait_for()
                assert owner.locator('.file-card').count() == page.locator('.file-card').count() == 1
                assert '交付文件.txt' in owner.inner_text() and '已加入 Telegram' not in owner.inner_text()
                before = owner.locator('.body').inner_html()
                records.append(case['history'])
                page.reload()
                owner.wait_for()
                assert owner.locator('.file-card').count() == 1
                assert owner.locator('.body').inner_html() == before
            assert not errors
        finally:
            context.close()
            browser.close()
