from tests.test_thinking_params import run_in_app


def test_telegram_image_documents_received_while_busy_are_stitched_not_rejected(tmp_path):
    result=run_in_app('import asyncio\nfrom tests.telegram_stitch_probe import busy_image_rejection\n'+f'print(json.dumps(asyncio.run(busy_image_rejection(bot,{str(tmp_path)!r}))))')
    assert not result['errors'],result
    assert result['buffered']==2 and result['model_started']==0


def test_mixed_telegram_attachments_reuse_stitch_and_delete_prompts_only_after_manual_send(tmp_path):
    result=run_in_app('import asyncio\nfrom tests.telegram_stitch_probe import manual_files\n'+f'print(json.dumps(asyncio.run(manual_files(bot,{str(tmp_path)!r}))))')
    assert all(result.values())


def test_manual_send_deletes_every_prompt_even_after_an_edit_required_a_new_prompt(tmp_path):
    result=run_in_app('import asyncio\nfrom tests.telegram_stitch_probe import manual_files\n'+f'print(json.dumps(asyncio.run(manual_files(bot,{str(tmp_path)!r},fallback=True))))')
    assert all(result.values())


def test_stitch_originals_and_buttons_restore_without_sending_after_process_restart(tmp_path):
    for restore in (False,True):
        result=run_in_app('import asyncio\nfrom tests.telegram_stitch_probe import unfinished_restart\n'+f'print(json.dumps(asyncio.run(unfinished_restart(bot,{str(tmp_path)!r},restore={restore!r}))))')
        assert all(result.values())


def test_slow_download_failed_file_and_failed_submission_do_not_lose_stitch(tmp_path):
    result=run_in_app('import asyncio\nfrom tests.telegram_stitch_probe import downloads_and_failure\n'+f'print(json.dumps(asyncio.run(downloads_and_failure(bot,{str(tmp_path)!r}))))')
    assert all(result.values())


def test_native_entry_with_interleaved_ai_replies_keeps_files_and_text_then_queues_and_deletes_prompts(tmp_path):
    result=run_in_app('import asyncio\nfrom tests.telegram_stitch_probe import interleaved_native_messages\n'+f'print(json.dumps(asyncio.run(interleaved_native_messages(bot,{str(tmp_path)!r}))))')
    assert all(result.values())
