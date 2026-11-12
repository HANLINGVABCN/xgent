import unittest
import json
from unittest.mock import patch

from tests.test_cli_input import CliProbeMixin


class CliManagementRegressionTests(CliProbeMixin,unittest.TestCase):
    def test_stream_command_and_numbered_button_update_the_shared_switch(self):
        result=self.run_probe('import asyncio\nfrom tests.cli_management_regression_probe import exercise\nprint(json.dumps(asyncio.run(exercise(xgent_cli,"mode_sync"))))')
        self.assertTrue(result['passed'])

    def test_native_calls_with_empty_prose_remain_visible_live_and_in_history(self):
        result=self.run_probe('import asyncio\nfrom tests.cli_management_regression_probe import exercise\nprint(json.dumps(asyncio.run(exercise(xgent_cli,"native"))))')
        self.assertTrue(result['passed'])

    def test_home_menus_and_first_message_create_only_at_admission(self):
        result=self.run_probe('import asyncio\nfrom tests.cli_management_regression_probe import exercise\nprint(json.dumps(asyncio.run(exercise(xgent_cli,"home"))))')
        self.assertTrue(result['passed'])

    def test_update_both_sources_use_current_card(self):
        result=self.run_probe('import asyncio\nfrom tests.cli_management_regression_probe import exercise\nprint(json.dumps(asyncio.run(exercise(xgent_cli,"update"))))')
        self.assertTrue(result['passed'])

    def test_start_menu_stays_above_new_messages_after_history_sync(self):
        result=self.run_probe('import asyncio\nfrom tests.cli_management_regression_probe import exercise\nprint(json.dumps(asyncio.run(exercise(xgent_cli,"ordering"))))')
        self.assertTrue(result['passed'])

    def test_update_token_input_resumes_original_card(self):
        result=self.run_probe('import asyncio\nfrom tests.cli_management_regression_probe import exercise\nprint(json.dumps(asyncio.run(exercise(xgent_cli,"token"))))')
        self.assertTrue(result['passed'])

    def test_provider_models_and_prompt_menu_navigation(self):
        result=self.run_probe('import asyncio\nfrom tests.cli_management_regression_probe import exercise\nprint(json.dumps(asyncio.run(exercise(xgent_cli,"navigation"))))')
        self.assertTrue(result['passed'])

    def test_persisted_message_does_not_jump_above_existing_live_menu(self):
        from xgent_app.cli_tui import PtScreen
        from xgent_app.cli_render import Palette
        screen=PtScreen(Palette(False),width=80)
        screen.select_conversation('test',0)
        screen.replace_history('test',[('h:1',['旧消息'],json.dumps({'timestamp':100}))])
        with patch('xgent_app.cli_tui.time.time',return_value=110):
            screen.print_block(['Start 菜单'],message_id=50)
        screen.replace_history('test',[
            ('h:1',['旧消息'],json.dumps({'timestamp':100})),
            ('h:2',['新消息'],json.dumps({'timestamp':120})),
            ('h:3',['AI 回复'],json.dumps({'timestamp':121})),
        ])
        self.assertEqual(['h:1',50,'h:2','h:3'],[message.key for message in screen.model.messages])
