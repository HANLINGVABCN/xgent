"""Compression archives, summaries and notices keep their order after refresh."""
from pathlib import Path

import pytest

from tests import test_compression_display as compression_support
from tests.test_full_output_web import full_output_server  # noqa: F401
from tests.test_web_presentation import browser_session


@pytest.mark.parametrize('width', [390, 1440])
def test_archive_summary_notice_order_and_count_match_after_completion_and_reload(full_output_server, width, tmp_path):
    case = compression_support.CompressionDisplayTests().probe(telegram_mode='background', return_case=True, long_summary=True)['browser_case']
    server = full_output_server[0]
    records = []
    async def history(limit):
        return records
    server.config.read_history = history
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        if not Path(p.chromium.executable_path).exists():
            pytest.skip('Chromium unavailable')
        browser, context, base = browser_session(server, p)
        page = context.new_page()
        page.set_viewport_size({'width': width, 'height': 950})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/#/chat?conversation=global_memory')
        page.wait_for_function('!document.querySelector("#btn-send").disabled')
        for frame in case['frames']:
            if frame['type'] == 'context_reset':
                page.locator('#log').get_by_text(case['partial'], exact=False).first.wait_for()
                records[:] = case['history']
            server.outbox.put(frame)
        archive_id, summary_id, notice_id = map(str, (case['archive_record_id'], case['response']['id'], case['notice_record_id']))
        page.locator(f'.msg-row[data-record-id="{notice_id}"]').wait_for()
        page.locator(f'.msg-row[data-record-id="{summary_id}"]').get_by_text('COMPRESS_COMPLETE_OUTPUT', exact=False).first.wait_for()
        page.wait_for_function('document.querySelector("#history-loading-state").hidden && !document.querySelector("#btn-send").disabled')

        def transcript():
            return page.locator('#log .msg-row[data-record-id]').evaluate_all('(rows) => rows.map(row => [row.dataset.recordId,row.querySelector(".body").innerHTML])')

        before = transcript()
        ids = [value[0] for value in before]
        assert len(set(ids)) == len(ids)
        assert ids.index(archive_id) < ids.index(summary_id) < ids.index(notice_id), ids
        assert page.locator('#log .file-card').count() == 1
        page.screenshot(path=str(tmp_path / f'compression-order-{width}.png'))
        page.reload()
        page.locator(f'.msg-row[data-record-id="{notice_id}"]').wait_for()
        page.wait_for_function('document.querySelector("#history-loading-state").hidden')
        assert transcript() == before
        assert page.locator('#log .file-card').count() == 1
        assert not errors
        browser.close()
