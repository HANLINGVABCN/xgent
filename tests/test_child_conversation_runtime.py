"""Runtime integration in a temporary instance; no real credentials or network."""
import unittest
from tests.test_external_sync import ProbeMixin


PREAMBLE = '''
import types
from xgent_app.bootstrap import load_sections
bot=types.ModuleType('xgent_server')
bot.__file__='xgent_server.py'
sys.modules['xgent_server']=bot
load_sections(vars(bot))
'''


class ChildConversationRuntimeTests(ProbeMixin, unittest.TestCase):
    def scenario(self, body):
        return self.run_probe(PREAMBLE + body, extra_env={'PYTHON_DOTENV_DISABLED': '1', 'BOT_TOKEN': ''})

    def test_native_and_fence_modes_keep_existing_engine_and_return_exactly_once(self):
        result = self.scenario('''
import asyncio
from tests.child_conversation_probe import queue_and_callback
async def main():
    results=[]
    for index,(mode,style) in enumerate([('toolcall','nonstream'),('toolcall','foreground'),('fence','nonstream')]):
        results.append(await queue_and_callback(bot,'run-'+str(index),mode,style))
    return results
print(json.dumps(asyncio.run(main())))
''')
        self.assertEqual(3, len(result))
        self.assertTrue(all(row['isolated'] and row['ordered_tools'] and row['callback_once'] for row in result))

    def test_cancelled_child_form_cannot_execute_remaining_tools(self):
        result = self.scenario('''
import asyncio
from tests.child_conversation_probe import cancel_form_job
print(json.dumps(asyncio.run(cancel_form_job(bot,'form-run'))))
''')
        self.assertTrue(all(result.values()))

    def test_delete_parent_stops_the_tree_and_never_revives_late_results(self):
        result = self.scenario('''
import asyncio
from tests.child_conversation_probe import delete_running_tree
print(json.dumps(asyncio.run(delete_running_tree(bot,'delete-run'))))
''')
        self.assertTrue(all(result.values()))

    def test_finish_task_keeps_real_outputs_even_without_an_assistant_summary(self):
        result = self.scenario('''
import asyncio
from tests.child_conversation_probe import finish_without_prose
print(json.dumps(asyncio.run(finish_without_prose(bot,'finish-run'))))
''')
        self.assertTrue(all(result.values()))


if __name__ == '__main__':
    unittest.main()
