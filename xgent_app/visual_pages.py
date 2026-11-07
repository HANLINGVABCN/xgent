"""One saved HTML/SVG page: Web renders it; Telegram receives folded source."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlencode,urlsplit,urlunsplit

MAX_SOURCE_BYTES=256*1024


def scan_pages(text,*,generating=False):
    """Top-level Markdown fences are output data, never executable protocols."""
    lines=str(text).splitlines(keepends=True);parts=[];prose=[];index=0;page_index=0
    while index<len(lines):
        opening=re.fullmatch(r'(`{3,16}|~{3,16})([^\r\n]*)\r?\n?',lines[index])
        if not opening:prose.append(lines[index]);index+=1;continue
        fence,info=opening.groups();name=info.strip().split(' ',1)[0]
        end=index+1
        while end<len(lines) and not re.fullmatch(re.escape(fence[0])+'{'+str(len(fence))+r',}\s*',lines[end].rstrip('\r\n')):end+=1
        if name not in {'xgent-html','xgent-svg'}:
            prose.extend(lines[index:min(end+1,len(lines))]);index=end+1;continue
        if prose:parts.append({'kind':'text','text':''.join(prose)});prose=[]
        title=info.strip()[len(name):].strip()[:100] or '渲染页面'
        if end==len(lines):
            if generating:
                source=''.join(lines[index+1:])
                parts.append({'kind':'pending','title':title,'index':page_index,'raw':''.join(lines[index:]),
                              'source':source if page_index<4 and len(source.encode('utf-8'))<=MAX_SOURCE_BYTES else '',
                              'format':name.removeprefix('xgent-')})
            else:parts.append({'kind':'text','text':''.join(lines[index:])})
            break
        source=''.join(lines[index+1:end])
        if not source.strip() or len(source.encode('utf-8'))>MAX_SOURCE_BYTES or page_index>=4:
            parts.append({'kind':'text','text':''.join(lines[index:end+1])})
        else:
            parts.append({'kind':'page','source':source,'format':name.removeprefix('xgent-'),'title':title,'index':page_index,'raw':''.join(lines[index:end+1]),
                          'width':800,'height':600});page_index+=1
        index=end+1
    if prose:parts.append({'kind':'text','text':''.join(prose)})
    return parts


def mask_page_source(text):
    # Even oversized blocks and page examples are data, never Agent protocols.
    lines=str(text).splitlines(keepends=True);output=[];index=0
    while index<len(lines):
        opening=re.fullmatch(r'(`{3,16}|~{3,16})[ \t]*xgent-(?:html|svg)(?:[ \t][^\r\n]*)?\r?\n?',lines[index])
        if not opening:output.append(lines[index]);index+=1;continue
        fence=opening.group(1);end=index+1
        while end<len(lines) and not re.fullmatch(re.escape(fence[0])+'{'+str(len(fence))+r',}\s*',lines[end].rstrip('\r\n')):end+=1
        output.extend('\n' if line.endswith('\n') else '' for line in lines[index:min(end+1,len(lines))]);index=end+1
    return ''.join(output)


def save_reply_pages(text,save_source):
    pages=[]
    for part in scan_pages(text):
        if part['kind']!='page':continue
        raw=part['source'].encode('utf-8');saved=save_source('reply-page.'+part['format'],raw,
                  'image/svg+xml' if part['format']=='svg' else 'text/html')
        pages.append({'version':2,**{key:part[key] for key in ('index','format','title','width','height')},
                      'source_path':saved['abs_path'],'sha256':hashlib.sha256(raw).hexdigest()})
    return pages


def display_parts(text,*,generating=False):
    return [{'kind':'html','text':'<span class="file-write-result">'+html.escape(part['title'])+(' · 生成中…' if part['kind']=='pending' else '')+'</span>',
             'visual_index':part['index'],'visual_title':part['title'],'visual_pending':part['kind']=='pending',
             'visual_source':part['source'],'visual_format':part['format']} if part['kind']!='text'
            else {'kind':'markdown','text':part['text']} for part in scan_pages(text,generating=generating)]


class VisualPageError(ValueError):
    pass


def validate_visual(data):
    if not isinstance(data,dict) or set(data)-{'version','format','source','width','height','title','kind','index','raw'}:
        raise VisualPageError('页面参数应为 format、source、width、height、title。')
    kind=data.get('format','html')
    if kind not in {'svg','html'}:raise VisualPageError('页面格式只支持 svg 或 html。')
    source=data.get('source')
    if not isinstance(source,str) or not source.strip() or len(source.encode('utf-8'))>MAX_SOURCE_BYTES:
        raise VisualPageError('请提供不超过 256 KiB 的完整 SVG／HTML 源码。')
    width,height=data.get('width',800),data.get('height',600)
    if any(type(value) is not int or not 64<=value<=1600 for value in (width,height)):
        raise VisualPageError('页面初始宽高必须为 64–1600 的整数。')
    title=data.get('title','渲染页面')
    if not isinstance(title,str) or len(title)>100 or '\n' in title or '\r' in title:
        raise VisualPageError('页面标题应为不超过 100 字的单行文字。')
    return {'format':kind,'source':source,'width':width,'height':height,'title':title.strip() or '渲染页面'}


def telegram_source(data):
    """Telegram folding doesn't exempt characters from the message limit."""
    data=validate_visual(data)
    source=data['source'];budget=2800
    shortened=len(source.encode('utf-16-le'))//2>budget
    if shortened:
        # Cut on Unicode scalar boundaries and identify the excerpt explicitly.
        used=0;parts=[]
        for char in source:
            size=len(char.encode('utf-16-le'))//2
            if used+size>budget:break
            used+=size;parts.append(char)
        source=''.join(parts)
    label='源码节选 · 完整源码见附件' if shortened else '源码'
    text='<b>'+html.escape(data['title'])+'</b>\n'+label+'\n<blockquote expandable><code>'+html.escape(source)+'</code></blockquote>'
    return text,shortened


def webapp_url(public_url,cid,record_id):
    parsed=urlsplit(str(public_url or ''))
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:return None
    return urlunsplit((parsed.scheme,parsed.netloc,parsed.path or '/',parsed.query,
                      '/chat?'+urlencode({'conversation':cid,'visual':record_id,'visual_full':'1'})))


@dataclass
class VisualSourceDownload:
    path:Path
    filename:str
    mime_type:str


async def read_visual(db,cid,record_id,storage_root,*,download=False,index=0):
    if not isinstance(cid,str) or not cid or not str(record_id).isascii() or not str(record_id).isdigit() or not 0<int(record_id)<2**63:raise VisualPageError('页面目标无效。')
    row=await db.get_display_message(int(record_id))
    if not row or row.get('withdrawn') or row.get('session_id')!=cid:raise VisualPageError('页面已不存在或已撤回。')
    metadata=row.get('metadata') or {}
    metadata=json.loads(metadata) if isinstance(metadata,str) else metadata
    pages=metadata.get('rendered_pages')
    if not str(index).isascii() or not str(index).isdigit():raise VisualPageError('页面序号无效。')
    visual=next((page for page in pages if page.get('index')==int(index)),None) if isinstance(pages,list) else metadata.get('visual_render')
    if not isinstance(visual,dict) or visual.get('version')!=2:raise VisualPageError('这条消息没有渲染页面。')
    root=(Path(storage_root)/'generated_media').resolve()
    path=Path(visual.get('source_path','')).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size>MAX_SOURCE_BYTES:
        raise VisualPageError('页面源码暂不可用。')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=visual.get('sha256'):raise VisualPageError('页面源码发生变化，请重新生成。')
    spec=validate_visual({key:value for key,value in {**visual,'source':raw.decode('utf-8')}.items()
                          if key in {'format','source','title','width','height'}})
    if download:return VisualSourceDownload(path,'render.'+spec['format'],'image/svg+xml' if spec['format']=='svg' else 'text/html')
    return {'version':2,**spec}


async def deliver_reply_pages(ns,context,row,facts):
    """Only client delivery; no tool result, Agent operation or model continuation."""
    from .presentation import message_presentation,metadata_dict
    from telegram import InlineKeyboardButton,InlineKeyboardMarkup,WebAppInfo
    pages=metadata_dict(row.get('metadata')).get('rendered_pages') or []
    if not pages or facts.get('pages_delivered'):return
    facts['pages_delivered']=True;db=await ns['BotMemoryDB'].get_instance()
    controls=[];cid=row['session_id'];settings=ns['UserDataManager'];ids=[];chat_id=row.get('chat_id') or ns['BotConfig'].AUTHORIZED_USER_ID
    for page in pages:
        public=settings.get('web_public_url','')
        if ns['normalize_bool'](settings.get('web_enabled',False),False) and ns['normalize_bool'](settings.get('_web_has_password',False),False):
            url=webapp_url(public,cid,row['id'])
            if url:
                url+='&visual_index='+str(page['index'])
                controls.append([InlineKeyboardButton('打开渲染页面'+(' · '+page['title'] if len(pages)>1 else ''),web_app=WebAppInfo(url=url))])
    markup=InlineKeyboardMarkup(controls) if controls else None
    with message_presentation({'kind':'ai_reply','purpose':'chat','audience':['telegram','cli'],'model_context':False}):
        if markup:
            mid=next(iter(facts.get('message_ids') or []),None)
            if mid:
                await context.bot.edit_message_reply_markup(chat_id=chat_id,message_id=mid,reply_markup=markup)
        for page in pages:
            spec=await read_visual(db,cid,row['id'],ns['ArtifactManager'].ROOT_DIR,index=page['index'])
            _,truncated=telegram_source(spec)
            if not truncated:continue
            with open(page['source_path'],'rb') as source:
                sent=await context.bot.send_document(chat_id=chat_id,document=source,filename='page.'+page['format'],
                    caption='完整源码：'+page['title'],reply_markup=markup)
            if sent:ids.append(sent.message_id)
    if ids:
        from .telegram_records import bind_record
        await bind_record(db,row,ids)
