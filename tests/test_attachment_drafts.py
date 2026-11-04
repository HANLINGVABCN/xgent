from tests.test_thinking_params import run_in_app


def test_withdraw_restores_server_references_and_resend_preserves_modes(tmp_path):
    result = run_in_app('import asyncio\nfrom tests.attachment_draft_probe import restore\n' +
        f'print(json.dumps(asyncio.run(restore(bot, {str(tmp_path)!r}))))')
    assert all(result.values())
