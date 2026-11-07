"""One saved HTML/SVG page: Web renders it; Telegram receives folded source."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import urlencode,urlsplit,urlunsplit

MAX_SOURCE_BYTES=256*1024


class VisualPageError(ValueError):
    pass


def validate_visual(data):
    if not isinstance(data,dict) or set(data)-{'format','source','width','height','title'}:
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
                      '/chat?'+urlencode({'conversation':cid,'visual':record_id})))


@dataclass
class VisualSourceDownload:
    path:Path
    filename:str
    mime_type:str


async def read_visual(db,cid,record_id,storage_root,*,download=False):
    if not isinstance(cid,str) or not cid or not str(record_id).isascii() or not str(record_id).isdigit() or not 0<int(record_id)<2**63:raise VisualPageError('页面目标无效。')
    row=await db.get_display_message(int(record_id))
    if not row or row.get('withdrawn') or row.get('session_id')!=cid:raise VisualPageError('页面已不存在或已撤回。')
    metadata=row.get('metadata') or {}
    metadata=json.loads(metadata) if isinstance(metadata,str) else metadata
    visual=metadata.get('visual_render')
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


async def create_visual(ns,context,db,cid,chat_id,data):
    from .agent_history import persist_agent_result
    from .presentation import current_turn,message_presentation
    from telegram import InlineKeyboardButton,InlineKeyboardMarkup,WebAppInfo
    spec=validate_visual(data)
    saved=ns['ArtifactManager'].save_generated_media('render.'+spec['format'],spec['source'].encode('utf-8'),
             'image/svg+xml' if spec['format']=='svg' else 'text/html')
    metadata={'visual_render':{'version':2,**{key:spec[key] for key in ('title','format','width','height')},
                              'source_path':saved['abs_path'],'sha256':hashlib.sha256(spec['source'].encode()).hexdigest()}}
    notice='[render结果] 渲染页面已创建：'+spec['title']+'。客户端自动呈现，无需另行发送。'
    row_id=await persist_agent_result(recorder=ns['GlobalRecorder'],message_type=ns['MessageType'].AGENT_RESULT,
          database=db,conversation_id=cid,chat_id=chat_id,notice=notice,display_metadata=metadata)
    await ns['publish_saved_reply'](context,row_id)
    markup=None
    settings=ns['UserDataManager']
    if ns['normalize_bool'](settings.get('web_enabled',False),False) and ns['normalize_bool'](settings.get('_web_has_password',False),False):
        url=webapp_url(settings.get('web_public_url',''),cid,row_id)
        if url:markup=InlineKeyboardMarkup([[InlineKeyboardButton('打开渲染页面',web_app=WebAppInfo(url=url))]])
    body,truncated=telegram_source(spec)
    try:
        with message_presentation({'kind':'agent_result','purpose':'chat','speaker':'tool','model_context':False,
                                   'audience':['telegram','cli'],'record_id':row_id,'telegram_page_html':body,
                                   'telegram_display':{'text':body,'parse_mode':'HTML','remove_stop':True}}):
            sent=await ns['safe_send_message'](context,chat_id,body,parse_mode='HTML',reply_markup=markup)
            if truncated:
                with open(saved['abs_path'],'rb') as source:
                    document=await context.bot.send_document(chat_id=chat_id,document=source,
                        filename='render.'+spec['format'],caption='完整源码：'+spec['title'],reply_markup=markup)
                if sent is not None:sent=[*(sent if isinstance(sent,list) else [sent]),document]
        messages=sent if isinstance(sent,list) else [sent] if sent else []
        ids=[message.message_id for message in messages if getattr(message,'message_id',None) is not None]
        if ids:
            from .telegram_records import bind_record
            row=await db.get_display_message(row_id)
            if row:await bind_record(db,row,ids)
    except Exception as exc:
        ns['logger'].warning('渲染页面已保存，但 Telegram 源码投递失败：%s',type(exc).__name__)
        notice='[render结果] 页面已保存并可在网页查看；Telegram 投递未确认，不要重复创建。'
    turn=current_turn()
    if turn:turn.observe_operation({'success':True})
    await ns['publish_saved_reply'](context,row_id)
    return notice
