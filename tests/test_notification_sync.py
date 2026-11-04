import pytest

from tests.test_thinking_params import run_in_app


def probe(name, root, **options):
    return run_in_app('import asyncio\nfrom tests.notification_sync_probe import ' + name + '\n' +
        f'print(json.dumps(asyncio.run({name}(bot, {str(root)!r}, **{options!r}))))')


@pytest.mark.parametrize('silent,selected,callback', [(False, True, False), (True, True, False),
                                                   (True, True, True), (True, False, False)])
def test_unauthorized_alert_scope_history_and_independent_security_log(tmp_path, silent, selected, callback):
    assert all(probe('security_notice', tmp_path, silent=silent, selected=selected, callback=callback).values())


@pytest.mark.parametrize('phase', ['delivered', 'pending', 'inflight', 'reconnect'])
def test_web_user_mirror_withdraw_and_delivery_races(tmp_path, phase):
    assert all(probe('withdraw_mirrored_user', tmp_path, phase=phase).values())


def test_legacy_web_user_mirror_also_keeps_record_identity(tmp_path):
    assert all(probe('withdraw_mirrored_user', tmp_path, queued=False).values())


def test_direct_web_file_and_caption_deliveries_keep_record_association(tmp_path):
    assert all(probe('direct_file_association', tmp_path).values())
