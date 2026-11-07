"""Pages are reply formatting, not tool execution or extra model requests."""
import asyncio
import hashlib
import html
import json
from unittest.mock import AsyncMock

import pytest

from tests.test_thinking_params import run_in_app
from xgent_app.visual_pages import scan_pages,telegram_source,webapp_url,read_visual,VisualPageError
from xgent_app.tool_calls import definitions
from xgent_app.protocols import ProtocolParser

SOURCE='<html><button onclick="this.textContent=\'已点击\'">点击</button></html>\n'
RAW='正文之前。\n```xgent-html 页面标题\n'+SOURCE+'```\n正文之后。'


def test_special_fence_is_data_and_original_tools_are_unchanged():
    parts=scan_pages(RAW);assert [part['kind'] for part in parts]==['text','page','text']
    assert parts[1]['source']==SOURCE and parts[1]['title']=='页面标题'
    assert not ProtocolParser.extract_protocol_blocks(RAW)
    for provider in ('openai','claude','gemini'):assert 'render_visual' not in json.dumps(definitions(provider))
    nested='```run-x\n<<BEGIN_example_1234\necho should-not-execute\n<<END_example_1234\n```\n'
    page='````xgent-html\n'+nested+'````\n'
    assert not ProtocolParser.extract_protocol_blocks(page)
    assert not ProtocolParser.has_unclosed_block(page)
    assert not ProtocolParser.extract_protocol_blocks('`````text\n'+page+'`````\n')
    assert not ProtocolParser.extract_protocol_blocks('````xgent-html\n'+(' '*262145)+'\n'+nested+'````\n')


def test_examples_incomplete_and_multiple_pages_keep_structural_order():
    assert all(part['kind']=='text' for part in scan_pages('````text\n'+RAW+'````\n'))
    assert scan_pages('```xgent-html\npartial',generating=True)[0]['kind']=='pending'
    assert scan_pages('```xgent-html\npartial')[0]['kind']=='text'
    assert [part['index'] for part in scan_pages(RAW+RAW) if part['kind']=='page']==[0,1]


def test_streaming_pages_carry_independent_sources_without_waiting_for_reply_end():
    from xgent_app.web_display import build_web_display
    svg='<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="20"/></svg>\n'
    raw='```xgent-svg 第一幅\n'+svg+'```\n```xgent-html 第二幅\n<style>h1{color:red}</style><h1>正在写'
    pieces=[s for s in build_web_display(raw,hide_unclosed=True)['segments'] if 'visual_index' in s]
    assert [s['visual_pending'] for s in pieces]==[False,True]
    assert pieces[0]['visual_source']==svg and pieces[0]['visual_format']=='svg'
    assert '<h1>正在写' in pieces[1]['visual_source']
    assert not ProtocolParser.extract_protocol_blocks(raw)


def test_telegram_complete_fold_and_explicit_long_excerpt():
    part=scan_pages(RAW)[1];short,truncated=telegram_source(part)
    assert not truncated and html.escape(SOURCE) in short and '<blockquote expandable>' in short
    long='\n'.join('代码😀 & 原文' for _ in range(1000))
    body,truncated=telegram_source({'format':'html','source':long})
    assert truncated and '源码节选 · 完整源码见附件' in body and '已折叠' not in body
    lines='\n'.join('line'+str(i) for i in range(120))
    complete,truncated=telegram_source({'format':'html','source':lines})
    assert not truncated and 'line119' in ProtocolParser.to_telegram_html(complete)


def test_sources_require_record_owner_and_unchanged_checksum(tmp_path):
    storage=tmp_path/'storage';(storage/'generated_media').mkdir(parents=True)
    path=storage/'generated_media/page.html';path.write_bytes(SOURCE.encode())
    page={'version':2,'index':0,'format':'html','title':'页面','source_path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    record={'id':7,'session_id':'A','withdrawn':0,'metadata':{'rendered_pages':[page]}}
    db=AsyncMock();db.get_display_message.return_value=record
    async def exercise():
        assert (await read_visual(db,'A',7,storage))['source']==SOURCE
        assert (await read_visual(db,'A',7,storage,download=True)).path==path
        with pytest.raises(VisualPageError):await read_visual(db,'B',7,storage)
        record['withdrawn']=1
        with pytest.raises(VisualPageError):await read_visual(db,'A',7,storage)
        record['withdrawn']=0;path.write_text('changed')
        with pytest.raises(VisualPageError):await read_visual(db,'A',7,storage)
    asyncio.run(exercise())


def test_https_webapp_reuses_saved_reply():
    assert webapp_url('http://localhost','A',23) is None
    assert webapp_url('https://xgent.example/app','A',23)=='https://xgent.example/app#/chat?conversation=A&visual=23&visual_full=1'


@pytest.mark.parametrize('provider',['openai','vertex','claude'])
@pytest.mark.parametrize('style',['foreground','background','nonstream'])
def test_one_real_reply_zero_tools_zero_agent_operations(provider,style,tmp_path):
    result=run_in_app('import asyncio\nfrom tests.visual_pages_probe import exercise\n'+f'print(json.dumps(asyncio.run(exercise(bot,{str(tmp_path)!r},{provider!r},{style!r}))))')
    assert all(result.values()),result


@pytest.mark.parametrize('agent_mode',[False,True])
def test_long_fence_reply_keeps_complete_source_and_has_no_extra_model_turn(agent_mode,tmp_path):
    result=run_in_app('import asyncio\nfrom tests.visual_pages_probe import exercise\n'+f'print(json.dumps(asyncio.run(exercise(bot,{str(tmp_path)!r},"openai","nonstream",long_source=True,agent_mode={agent_mode!r},mode="fence"))))')
    assert all(result.values()),result


def test_global_prompt_teaches_special_fence_as_output_format():
    from pathlib import Path
    from xgent_app.prompt_defaults import DEFAULT_GLOBAL_PROMPT
    text=(Path(__file__).resolve().parents[1]/'prompts/global_addon.txt').read_text(encoding='utf-8')
    assert text==DEFAULT_GLOBAL_PROMPT and '不是工具调用' in text and 'xgent-html' in text and 'xgent-svg' in text


def test_real_stream_renderer_does_not_deduplicate_growing_page_sources(tmp_path):
    result=run_in_app('import asyncio\nfrom tests.visual_pages_probe import progressive\n'+
        f'print(json.dumps(asyncio.run(progressive(bot,{str(tmp_path)!r}))))')
    assert all(result.values()),result
