import asyncio
from unittest.mock import AsyncMock
import pytest
from tests.test_thinking_params import run_in_app
from xgent_app.command_output import load_command_output,text_page
from xgent_app.output_archive import OutputArchiveError
from xgent_app.message_policy import stamp_record_metadata

@pytest.mark.parametrize('mode',['toolcall','fence'])
def test_command_output_not_transferred_until_requested_and_identical_commands_do_not_mix(tmp_path,mode):
    result=run_in_app('import asyncio\nfrom tests.command_output_probe import exercise\n'+f'print(json.dumps(asyncio.run(exercise(bot,{str(tmp_path)!r},{mode!r}))))')
    assert result['no_preload'] and result['two_unique_links'] and result['executions']==2

def test_output_record_is_checked_for_owner_withdrawal_and_page_size(tmp_path):
    row={'id':7,'session_id':'A','msg_type':'agent_result','content':'saved',
        'metadata':stamp_record_metadata('agent_result','tool',{'presentation':{'operation':{'kind':'run','output':'完整😀 '*30000}}})}
    db=AsyncMock();db.get_display_message.return_value=row
    async def exercise():
        page=await load_command_output(db,'A',7,0,tmp_path);assert len(page['text'].encode())<=65536 and not page['eof']
        with pytest.raises(OutputArchiveError):await load_command_output(db,'B',7,0,tmp_path)
        for invalid in (0,True,-1,2**80):
            with pytest.raises(OutputArchiveError):await load_command_output(db,'A',invalid,0,tmp_path)
        row['withdrawn']=True
        with pytest.raises(OutputArchiveError):await load_command_output(db,'A',7,0,tmp_path)
    asyncio.run(exercise())
    assert text_page('',0)['eof']
