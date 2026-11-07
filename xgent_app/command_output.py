"""Web-only command/result projection and owner-checked, lazy output reads."""
from __future__ import annotations
import asyncio
import html
import json
import re

from .output_archive import OUTPUT_PAGE_BYTES,read_output_page,OutputArchiveError

COMMAND_KINDS=frozenset({'run','shell','stdin','shellkill'})


def command_key(operation):
    if operation.get('command_key'):return operation['command_key']
    if operation.get('native_call_id'):return 'call:'+operation['native_call_id']
    if operation.get('sequence') is not None:return 'sequence:'+str(operation['sequence'])
    return ''


def command_descriptor(operation,record_id=None):
    from .web_display import operation_state
    if operation.get('kind') not in COMMAND_KINDS:return None
    state=operation_state(operation)
    error=''
    if state=='failed':
        first=str(operation.get('output') or operation.get('notice') or '').splitlines()
        reason=first[0][:180] if first and re.search(r'失败|错误|error|denied|traceback',first[0],re.I) else ''
        error='命令执行失败'+('（返回码 '+str(operation['return_code'])+'）' if operation.get('return_code') is not None else '')+('：'+reason if reason else '')
    return {'version':1,'key':command_key(operation),'reply_record_id':operation.get('reply_record_id'),
        'result_record_id':record_id or operation.get('result_record_id'),'sequence':operation.get('sequence'),
        'kind':operation['kind'],'command':operation.get('command',''),'path':operation.get('path',''),
        'state':state,'elapsed_seconds':operation.get('elapsed_seconds'),'return_code':operation.get('return_code'),
        'error':error}


def project_web_frame(frame):
    """Never put output bodies in Web event queues or default history responses."""
    descriptor=frame.get('command_result') or (frame.get('web_display') or {}).get('command_result')
    if not descriptor or descriptor.get('version')!=1:return frame
    from .web_display import web_block_html
    descriptor={**descriptor,'result_record_id':frame.get('record_id',frame.get('id',descriptor.get('result_record_id')))}
    if not descriptor['key']:descriptor['key']='result:'+str(descriptor.get('result_record_id') or 'pending')
    if not descriptor.get('command'):descriptor['command']='（此记录未保存命令正文）'
    display={'version':1,'presentation_mode':'folded','command_result':descriptor,
        'segments':[{'kind':'html','text':web_block_html(descriptor.get('command',''),
            protocol=descriptor['kind']+'-x',state=descriptor['state'],path=descriptor.get('path'),command_key=descriptor['key'])}]}
    result={**frame,'command_result':descriptor,'web_display':display,'parse_mode':None,'operation_details':''}
    for key in ('text','content'):
        if key in result:result[key]=''
    return result


def project_web_payload(payload):
    if not isinstance(payload,dict):return payload
    result=project_web_frame(payload)
    for key in ('messages','frames'):
        if isinstance(result.get(key),list):result={**result,key:[project_web_frame(item) for item in result[key]]}
    if isinstance(result.get('live'),dict):result={**result,'live':project_web_payload(result['live'])}
    return result


def text_page(text,offset):
    if type(offset) is not int or offset<0:raise OutputArchiveError('无效的输出分页位置')
    raw=str(text).encode('utf-8');size=len(raw)
    if offset>size:raise OutputArchiveError('输出已变化，请重新读取')
    end=min(size,offset+OUTPUT_PAGE_BYTES)
    while end<size and end>offset and raw[end]&0xc0==0x80:end-=1
    return {'text':raw[offset:end].decode('utf-8',errors='replace'),'offset':offset,'next_offset':end,'size':size,'eof':end==size,'filename':'命令输出.txt'}


async def load_command_output(db,cid,record_id,offset,storage_root,*,view='output'):
    if not str(record_id).isascii() or not str(record_id).isdigit() or not 0<int(record_id)<2**63:raise OutputArchiveError('输出记录无效')
    row=await db.get_display_message(int(record_id))
    if not row or row.get('session_id')!=cid or row.get('withdrawn'):raise OutputArchiveError('输出已不存在或已撤回')
    metadata=row.get('metadata') or {};metadata=json.loads(metadata) if isinstance(metadata,str) else metadata
    from .message_policy import record_policy
    if not record_policy(row).allows('web'):raise OutputArchiveError('此记录不能在网页查看')
    operation=(metadata.get('presentation') or {}).get('operation') or {}
    if row.get('msg_type')!='agent_result' or operation.get('kind') not in COMMAND_KINDS:raise OutputArchiveError('此记录不是命令输出')
    if view=='info':return text_page(operation.get('notice') or html.unescape(re.sub('<[^>]+>','',row['content'])),offset)
    if view!='output':raise OutputArchiveError('输出视图无效')
    path=operation.get('output_path');warning=''
    if path:
        from pathlib import Path
        try:
            page=await asyncio.to_thread(read_output_page,path,offset,roots=[Path(storage_root)/'command_outputs',Path(storage_root)/'conversation_objects'])
        except OutputArchiveError:
            warning='完整输出存档不可读取，显示已保存的结果。'
            page=text_page(operation.get('output') or operation.get('notice') or html.unescape(re.sub('<[^>]+>','',row['content'])),offset)
    else:page=text_page(operation.get('output') or operation.get('notice') or html.unescape(re.sub('<[^>]+>','',row['content'])),offset)
    if operation.get('archive_truncated'):warning+=' 原存档已标记截断。'
    page['warning']=warning
    page['details']={key:operation[key] for key in ('return_code','elapsed_seconds','session_id','status','running','output_path','waited_seconds','archive_truncated') if operation.get(key) is not None}
    return page
