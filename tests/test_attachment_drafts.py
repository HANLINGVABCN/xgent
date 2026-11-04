from tests.test_thinking_params import run_in_app
import pytest
import tempfile


def test_withdraw_restores_server_references_and_resend_preserves_modes(tmp_path):
    result = run_in_app('import asyncio\nfrom tests.attachment_draft_probe import restore\n' +
        f'print(json.dumps(asyncio.run(restore(bot, {str(tmp_path)!r}))))')
    assert all(result.values())


@pytest.mark.parametrize('phase',['delivered','pending','inflight','reconnect'])
def test_resend_original_files_and_withdraw_bot_copies(tmp_path,phase):
    result=run_in_app('import asyncio\nfrom tests.attachment_resend_delivery_probe import verify\n'+
        f'print(json.dumps(asyncio.run(verify(bot,{str(tmp_path)!r},phase={phase!r}))))')
    assert all(result.values())


def test_restored_files_and_new_upload_sync_together_without_duplicate_delivery():
    # Version object names add two hashes; keep the fixture below Windows MAX_PATH.
    with tempfile.TemporaryDirectory(prefix='xgr-') as directory:
        result=run_in_app('import asyncio\nfrom tests.attachment_resend_delivery_probe import verify\n'+
            f'print(json.dumps(asyncio.run(verify(bot,{directory!r},new_file=True))))')
    assert all(result.values())


def test_long_resend_caption_and_original_files_withdraw_together(tmp_path):
    result=run_in_app('import asyncio\nfrom tests.attachment_resend_delivery_probe import verify\n'+
        f'print(json.dumps(asyncio.run(verify(bot,{str(tmp_path)!r},long_caption=True))))')
    assert all(result.values())


def test_queued_original_file_sync_keeps_cloud_and_local_transport_limits(tmp_path):
    result=run_in_app('import asyncio\nfrom tests.attachment_resend_delivery_probe import transport_limits\n'+
        f'print(json.dumps(asyncio.run(transport_limits(bot,{str(tmp_path)!r}))))')
    assert all(result.values())
