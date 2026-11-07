"""Shared rendered pages, truthful Telegram excerpts, and authorized source reads."""
import asyncio
import hashlib
import html
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.test_thinking_params import run_in_app
from xgent_app.visual_pages import validate_visual,telegram_source,webapp_url,read_visual,VisualPageError
from xgent_app.tool_calls import operation,definitions
from xgent_app.protocols import ProtocolParser

SVG='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" rx="28" fill="#E5A85A"/><g fill="none" stroke="#18181B" stroke-linecap="round" stroke-linejoin="round"><path d="M22 34L46 51L22 68" stroke-width="7.5"/><path d="M94 40L80 51L94 62" stroke-width="6"/><rect x="44" y="82" width="32" height="7.5" rx="3" fill="#18181B" stroke="none"/></g></svg>'


@pytest.mark.parametrize('change',[{'width':True},{'width':10},{'height':2000},{'format':'javascript'},{'source':''},{'source':'a'*300000},{'title':'bad\nname'},{'url':'file:///etc/passwd'}])
def test_invalid_page_is_rejected_before_execution(change):
    with pytest.raises(VisualPageError):validate_visual({'format':'svg','source':SVG,'width':240,'height':240,**change})


def test_native_and_fence_keep_complete_source_and_offer_tool_to_all_providers():
    data={'format':'svg','source':SVG,'width':240,'height':240,'title':'终端图标'}
    block=operation({'id':'render-1','name':'render_visual','arguments':data})
    assert block['type']=='render' and json.loads(block['body'])==data
    raw='```render-x\n<<BEGIN_render_test_1234\n'+json.dumps(data)+'\n<<END_render_test_1234\n```'
    blocks=ProtocolParser.extract_protocol_blocks(raw)
    assert len(blocks)==1 and json.loads(blocks[0]['body'])==data
    assert '已折叠' not in ProtocolParser.render_folded_html(raw) and 'viewBox' not in ProtocolParser.render_folded_html(raw)
    for provider in ('openai','claude','gemini'):assert 'render_visual' in json.dumps(definitions(provider))


def test_short_code_is_complete_folded_long_code_is_explicit_excerpt():
    short,truncated=telegram_source({'format':'svg','source':SVG,'width':240,'height':240})
    assert not truncated and '<blockquote expandable>' in short and html.escape(SVG) in short
    source='\n'.join('<div>😀 中文 & 长源码</div>' for _ in range(1000))
    body,truncated=telegram_source({'format':'html','source':source,'width':800,'height':600})
    assert truncated and '源码节选 · 完整源码见附件' in body
    assert '已折叠' not in body and '行' not in body
    plain=html.unescape(__import__('re').sub('<[^>]+>','',body))
    assert len(plain.encode('utf-16-le'))//2<4096
    lines='\n'.join('line'+str(i) for i in range(120))
    complete,truncated=telegram_source({'format':'html','source':lines,'width':800,'height':600})
    adapted=ProtocolParser.to_telegram_html(complete)
    assert not truncated and 'line119' in adapted and '已折叠' not in adapted


def test_webapp_reuses_chat_page_and_only_uses_https_public_entry():
    assert webapp_url('http://localhost:8790','A',23) is None
    url=webapp_url('https://xgent.example/app','A',23)
    assert url=='https://xgent.example/app#/chat?conversation=A&visual=23'


def test_source_reads_validate_record_conversation_withdrawal_path_and_hash(tmp_path):
    root=tmp_path/'storage';(root/'generated_media').mkdir(parents=True)
    path=root/'generated_media/page.html';path.write_text('<b>页面</b>',encoding='utf-8')
    visual={'version':2,'source_path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'format':'html','title':'演示','width':800,'height':600}
    row={'id':7,'session_id':'A','withdrawn':0,'metadata':json.dumps({'visual_render':visual})}
    db=AsyncMock();db.get_display_message.return_value=row
    async def exercise():
        assert (await read_visual(db,'A',7,root))['source']=='<b>页面</b>'
        assert (await read_visual(db,'A',7,root,download=True)).path==path
        with pytest.raises(VisualPageError):await read_visual(db,'B',7,root)
        row['withdrawn']=1
        with pytest.raises(VisualPageError):await read_visual(db,'A',7,root)
        row['withdrawn']=0;path.write_text('changed')
        with pytest.raises(VisualPageError):await read_visual(db,'A',7,root)
    asyncio.run(exercise())


@pytest.mark.parametrize('long_source',[False,True])
def test_native_tool_telegram_fold_webapp_and_no_picture(long_source,tmp_path):
    result=run_in_app('import asyncio\nfrom tests.visual_pages_probe import exercise\n'+f'print(json.dumps(asyncio.run(exercise(bot,{str(tmp_path)!r},{long_source!r}))))')
    assert all(result.values()),result


def test_global_prompt_has_presentation_guidance_and_no_tool_parameter_manual():
    from xgent_app.prompt_defaults import DEFAULT_GLOBAL_PROMPT
    source=(Path(__file__).resolve().parents[1]/'prompts/global_addon.txt').read_text(encoding='utf-8')
    assert source==DEFAULT_GLOBAL_PROMPT
    assert '优先直接展示渲染页面' in source and 'Web App' in source and '也不另行要求发送图片' in source
    assert 'render-x' not in source and 'render_visual(' not in source


def test_real_http_page_and_download_require_login_owner_and_live_record(tmp_path):
    result=run_in_app('import asyncio\nfrom tests.visual_pages_probe import http_read\n'+f'print(json.dumps(asyncio.run(http_read(bot,{str(tmp_path)!r}))))')
    assert all(result.values())
