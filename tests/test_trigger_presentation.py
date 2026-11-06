"""Trigger receipts agree across live delivery, refresh and model continuation."""
import html
import unittest
from pathlib import Path

import pytest

from tests.test_external_sync import ProbeMixin
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session
from xgent_app.protocols import ProtocolParser
from xgent_app.trigger_presentation import build_trigger_result_display


@pytest.fixture(scope='module')
def trigger_receipts():
    class Probe(ProbeMixin, unittest.TestCase):
        pass

    return Probe().run_probe(r'''
import asyncio, json, tempfile, time
from pathlib import Path
import xgent_server as bot
from tests.native_tool_probe import NativeHarness
from xgent_app.web_history import build_history_message
from xgent_app.conversations import bind_conversation
from xgent_app.presentation import metadata_dict

async def main():
    cases=[]
    with tempfile.TemporaryDirectory() as folder:
        for style in ('foreground', 'background', 'nonstream'):
            for kind in ('command', 'child', 'failed'):
                root=Path(folder)/style/kind
                async with NativeHarness(bot, root, 'openai_compatible', style) as h:
                    original='ORIGINAL_REQUEST_FOR_TRIGGER'
                    task={'id':'trg_receipt', 'chat_id':1, 'conversation_id':'global_memory',
                        'command':'NOT_EXECUTED_BY_DELIVERY', 'summary':'原始任务 <tag>',
                        'origin_user_text':original, 'schedule_type':'once', 'timezone':'UTC',
                        'status':'completed', 'created_at':time.time(), 'updated_at':time.time()}
                    await h.db.create_trigger_task(task)
                    run,_=await h.db.create_trigger_run(task['id'], 123, 'process_exit')
                    output=('\n'.join(f'line{i:03d}: '+('中文 & <tag> '*8) for i in range(120))
                        if kind=='command' else json.dumps({'status':'completed', 'complete':True,
                            'reply':'CHILD_ACTUAL_RESULT', 'tool_results':[{'text':'RAW_CHILD_OUTPUT'}]}, ensure_ascii=False)
                        if kind=='child' else 'RAW_FAILURE_STDERR\n<failed>')
                    output+='\n<script>window.triggerExecuted=1</script>\n```run-x\n<<BEGIN_raw\nDO_NOT_EXECUTE\n<<END_raw\n```'
                    archive=root/'storage'/'command_outputs'/'trigger.txt'
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    archive.write_text(output, encoding='utf-8')
                    error='RuntimeError: original failure <detail>' if kind=='failed' else None
                    await h.db.finish_trigger_run(run['run_id'], finished_at=124,
                        status='failed' if error else 'completed', exit_code=9 if error else 0,
                        output=output, output_path=str(archive), error=error)
                    h.responses=[([], 'MODEL_CONTINUED')]
                    await bot.SelfTriggerManager._deliver_run(run['run_id'])
                    await bot.SelfTriggerManager._deliver_run(run['run_id'])
                    frames=h.drain_frames()
                    rows=await h.db.get_display_history(100)
                    saved=[r for r in rows if metadata_dict(r['metadata']).get('trigger_result')]
                    assert len(saved)==1, saved
                    saved=saved[0]
                    history=build_history_message(saved, bot.ArtifactManager.ROOT_DIR, root)
                    raw=saved['content']
                    assert raw.startswith('[后台任务结果]') and output in raw and original in raw
                    assert len(h.requests)==1 and h.executed==[], (h.requests, h.executed)
                    assert any(m.get('content')==raw for m in h.requests[0]['messages'])
                    other=(await h.db.manage_conversation('create',name='OTHER',select=False))['conversation_id']
                    with bind_conversation(await bot.get_conversations().resolve(other)):
                        assert not await h.db.get_display_history(100)
                    receipt_frames=[f for f in frames if f.get('record_id')==saved['id']]
                    cases.append({'name':style+'/'+kind, 'raw':raw, 'output':output, 'error':error,
                        'history':history, 'frames':receipt_frames, 'metadata':metadata_dict(saved['metadata'])})
                    await bot.get_conversations().close()
    print(json.dumps(cases))
asyncio.run(main())
''')


def test_trigger_live_and_history_keep_one_receipt_and_original_model_context(trigger_receipts):
    assert len(trigger_receipts) == 9
    for case in trigger_receipts:
        message = case['history']
        assert message['role'] == 'assistant'
        assert message['message_policy']['speaker'] == 'assistant'
        assert message['message_policy']['model_context'] is True
        assert 'conversation_actions' not in message
        assert '[后台任务结果]' not in message['content']
        assert '后台任务已产生结果' in message['content']
        assert '系统已记录完整执行结果，正在检查是否继续唤醒 AI。' in message['content']
        assert html.escape(case['output'], quote=False) in message['web_display']['segments'][1]['text']
        if case['error']:
            assert html.escape(case['error'], quote=False) in message['content']
            assert 'data-state="failed"' in message['web_display']['segments'][1]['text']
        else:
            assert 'data-state="success"' in message['web_display']['segments'][1]['text']
        sent = [f for f in case['frames'] if f['type'] == 'message']
        snapshots = [f for f in case['frames'] if f['type'] == 'record_snapshot']
        assert len(sent) == len(snapshots) == 1, case['name']
        assert sent[0]['text'] == snapshots[0]['text'] == message['content']
        assert sent[0]['web_display'] == snapshots[0]['web_display'] == message['web_display']
        assert case['metadata']['web_live']['message_ids'] == [sent[0]['message_id']]


def test_trigger_output_reuses_telegram_preview_budget_and_keeps_full_web_result():
    raw = '\n'.join(f'{i:03d}: ' + ('中<&> ' * 40) for i in range(200))
    result = build_trigger_result_display('🔔 后台任务已产生结果', {
        'output': raw, 'exit_code': 0, 'status': 'completed', 'output_path': '/archive/trigger.txt',
    })
    assert html.escape(raw, quote=False) in result['display']['content']
    bounded = ProtocolParser.to_telegram_html(result['display']['content'])
    assert '199:' not in bounded and '000:' in bounded
    assert len(bounded.encode('utf-16-le')) // 2 < 4096


def test_trigger_browser_refresh_keeps_receipt_fold_and_no_extra_message(full_output_server, trigger_receipts):
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
            for case in trigger_receipts:
                records = []

                async def history(limit):
                    return records

                server.config.read_history = history
                server.outbox.put({'type': 'history_reset'})
                if page.url!='about:blank':page.evaluate('sessionStorage.removeItem("xgent-fold-state")')
                target=base+'/#/chat?conversation=global_memory'
                if page.url==target:page.reload()
                else:page.goto(target)
                page.wait_for_function('!document.getElementById("btn-send").disabled')
                for frame in case['frames']:
                    server.outbox.put(frame)
                selector = f'.msg-row[data-record-id="{case["history"]["id"]}"]'
                receipt = page.locator(selector)
                receipt.wait_for()
                assert page.locator('.msg-row').count() == 1, case['name']
                block = receipt.locator('blockquote[expandable]')
                assert block.count() == 1
                assert 'expanded' not in (block.get_attribute('class') or '')
                assert receipt.locator('.pb-head').count() == 1
                before = receipt.locator('.body').inner_html()
                records.append(case['history'])
                page.reload()
                receipt.wait_for()
                assert receipt.locator('.body').inner_html() == before, case['name']
                assert page.locator('.msg-row').count() == 1
                receipt.locator('.pb-head').click()
                page.wait_for_function('document.querySelector(".execution-block").classList.contains("expanded")')
                assert case['output'] in receipt.inner_text()
                assert page.evaluate('window.triggerExecuted') is None
            assert errors == []
        finally:
            browser.close()
