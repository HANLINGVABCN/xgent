/* File and attachment views. Paging, versions and downloads use the existing API. */
import {$,el,button,fmt,stamp,bytes,message,empty,field,select,check,table,formData,api,wb,download,query,tag,copyText,requestId,safeLocalUrl,inlineState} from './components.js';
import {heading,card,toolbar,actions} from './ui.js';
export function createViews(context) {
const {state,pageCache,filter,render,selectFilter,searchFilter,sourceLink,filePagination,outputViewer,showError,detail,closeDetail,confirmAction,dialog,closeDialog,submit,dirtyForm,errorOr,refreshBootstrap,chatControls,localFilters,managementModule,taskSourceSearch}=context;
async function filePage(read){
  const kind=filter('kind')||'files',source=filter('source')||'all';
  const data=await read('artifacts'+query({kind,source_conversation_id:source,q:filter('q'),media_type:filter('media_type'),availability:filter('availability'),execution_status:filter('execution_status'),start_date:filter('start_date'),end_date:filter('end_date'),sort:filter('sort')||'newest',offset:filter('offset')||0}));
  const page=el('div',{class:'wb-file-page'},heading('文件与输出','按来源对话查找附件、生成文件和完整命令日志。'));
  const change=()=>{filter('offset',0);render();};
  const tabs=el('div',{class:'wb-tabs',role:'tablist','aria-label':'文件来源'},[['files','附件与生成文件'],['outputs','命令输出']].map(([value,label])=>el('button',{type:'button',role:'tab','aria-selected':kind===value,class:kind===value?'active':'',onclick:()=>{filter('kind',value);filter('media_type','');filter('execution_status','');change();}},label)));
  const origin=selectFilter('source',[{value:'all',label:'全部来源对话'},{value:'current',label:'当前对话'},...(data.sources||[]).map(c=>({value:c.id,label:c.name+(c.archived?'（已归档）':'')}))],source,change);origin.setAttribute('aria-label','文件来源对话');
  const origins=el('div',{class:'wb-source-picker'},origin,button('搜索对话',taskSourceSearch));
  const clear=()=>{for(const key of ['q','media_type','availability','execution_status','start_date','end_date'])filter(key,'');filter('source','all');filter('sort','newest');change();};
  const typeChips=kind==='files'?el('div',{class:'wb-chip-row',role:'group','aria-label':'文件类型'},[{value:'',label:'全部文件类型'},{value:'photo',label:'图片'},{value:'video',label:'视频'},{value:'audio',label:'音频'},{value:'file',label:'文档'}].map(option=>el('button',{type:'button',class:'wb-chip'+((filter('media_type')||'')===option.value?' active':''),onclick:()=>{filter('media_type',option.value);change();}},option.label))):null;
  const tools=toolbar(searchFilter(kind==='outputs'?'搜索日志、命令或任务':'按文件名搜索',change),origins,
    kind==='files'?null:selectFilter('execution_status',[{value:'',label:'全部执行状态'},...['completed','failed','interrupted','running'].map(value=>({value,label:tag(value).textContent}))],'',change),
    selectFilter('availability',[{value:'',label:'全部文件状态'},{value:'available',label:'可读取'},{value:'missing',label:'不可读取'}],'',change),selectFilter('sort',[{value:'newest',label:'时间：从新到旧'},{value:'oldest',label:'时间：从旧到新'},{value:'name',label:'名称'},{value:'size',label:'大小：从大到小'}],'newest',change));
  const dates=el('form',{class:'wb-file-dates'},field('开始日期','start_date',filter('start_date')||'','date'),field('结束日期','end_date',filter('end_date')||'','date'),el('button',{type:'submit',class:'wb-btn'},'应用时间'),button('清除筛选',clear),button('刷新',()=>render()));
  dates.onsubmit=e=>{e.preventDefault();const values=formData(dates);filter('start_date',values.start_date);filter('end_date',values.end_date);change();};page.append(tabs,tools,...(typeChips?[typeChips]:[]),dates);
  if(!data.items.length)page.append(empty('没有匹配的文件','可调整来源、类型或时间范围。',button('清除筛选',clear)));
  else if(kind==='files'){
    // 附件浏览：表格 → 封面卡片网格（封面仍走 artifacts/cover 懒加载管道）。
    const grid=el('div',{class:'wb-file-grid'});
    for(const file of data.items){
      grid.append(el('article',{class:'wb-file-card'},
        fileCover(file),
        el('div',{class:'wb-file-card-main'},
          el('h3',{},el('button',{class:'link',type:'button',onclick:()=>fileDetail(file)},file.filename||'文件')),
          file.ingress_mode?el('small',{class:'media-ingress-badge','data-mode':file.ingress_mode},file.ingress_mode==='server_upload'?'↑ 上传 · 仅路径':'📎 附件'):null,
          file.path?el('div',{class:'wb-file-path'},el('code',{},file.path),button('复制路径',()=>copyText(file.path).catch(e=>showError(page,e)))):null,
          file.command?el('code',{class:'wb-file-command',title:file.command},file.command):null,
          file.error?el('small',{class:'wb-danger-text'},file.error):null),
        el('div',{class:'wb-file-card-meta'},
          el('span',{},({photo:'图片',video:'视频',audio:'音频',output:'命令输出',file:'文档'})[file.kind]||'文件',el('small',{},bytes(file.size))),
          el('span',{},stamp(file.timestamp)),sourceLink(file.source)),
        el('div',{class:'wb-card-footer'},actions(button('预览',()=>fileDetail(file)),file.versions_id?button('版本',()=>attachmentVersions(file)):null))));
    }
    page.append(grid);
  }
  else {
    const labels=['命令 / 日志','来源对话','类型 / 大小','时间','操作'];
    const tableNode=table(labels,data.items.map(file=>[
      el('div',{class:'wb-file-primary'},fileCover(file),el('div',{class:'wb-file-title'},el('h3',{},el('button',{class:'link',type:'button',onclick:()=>fileDetail(file)},file.filename||'文件')),file.ingress_mode?el('small',{class:'media-ingress-badge','data-mode':file.ingress_mode},file.ingress_mode==='server_upload'?'↑ 上传 · 仅路径':'📎 附件'):null,file.path?el('div',{class:'wb-file-path'},el('code',{},file.path),button('复制路径',()=>copyText(file.path).catch(e=>showError(page,e)))):null,file.command?el('code',{class:'wb-file-command',title:file.command},file.command):null,file.error?el('small',{class:'wb-danger-text'},file.error):null)),
      sourceLink(file.source),el('div',{},({photo:'图片',video:'视频',audio:'音频',output:'命令输出',file:'文档'})[file.kind]||'文件',el('small',{},bytes(file.size)),file.status?tag(file.status):null),stamp(file.timestamp),actions(button(file.kind==='output'?'查看完整输出':'预览',()=>fileDetail(file)),file.versions_id?button('版本',()=>attachmentVersions(file)):null)]));
    tableNode.classList.add('wb-file-table');for(const row of tableNode.querySelectorAll('tbody tr'))[...row.children].forEach((cell,index)=>cell.dataset.label=labels[index]);page.append(tableNode);
  }
  page.append(filePagination(data));return page;
}
const coverQueue=[];let coverActive=0;
const coverObserver=new IntersectionObserver(entries=>{
  for(const entry of entries)if(entry.isIntersecting){coverObserver.unobserve(entry.target);coverQueue.push(entry.target);}
  pumpCovers();
},{rootMargin:'200px'});
function pumpCovers(){
  while(coverActive<3&&coverQueue.length){
    const node=coverQueue.shift();if(!node.isConnected)continue;
    coverActive++;const epoch=state.authEpoch;
    wb('artifacts/cover'+query({id:node._file.id,kind:node._file.kind==='output'?'outputs':'files',conversation_id:node._file.source?.conversation_id})).then(data=>{
      if(epoch!==state.authEpoch)return;
      node.replaceChildren();node.classList.add('is-ready');
      if(data.image?.startsWith('data:image/jpeg;base64,'))node.append(el('img',{src:data.image,alt:node._file.filename+' · 轻量封面',decoding:'async'}));
      else if(data.kind==='text')node.append(el('pre',{},data.text||'空文本文件'));
      else node.append(el('span',{},data.label||'点击查看'));
      if(node._file.kind==='video')node.append(el('span',{class:'wb-cover-play','aria-hidden':'true'},'▶'));
    }).catch(()=>{node.textContent='点击查看';}).finally(()=>{coverActive--;pumpCovers();});
  }
}
function fileCover(file){
  const node=el('button',{type:'button',class:'wb-file-cover','aria-label':'预览 '+file.filename,onclick:()=>{
    const url=libraryMediaUrl(file);
    if(['photo','video','audio'].includes(file.kind)&&safeLocalUrl(url))window.XGentChat.previewMedia(url,file.filename,file.kind);
    else fileDetail(file);
  }},file.error?'文件不可读取':'预览加载中…');
  node._file=file;if(!file.error)coverObserver.observe(node);return node;
}
async function attachmentVersions(file){
  const id=file.versions_id,cid=file.source?.conversation_id||file.conversation_id||window.XGentConversations?.current;
  const box=el('div',{class:'attachment-versions'});
  if(!detail('附件版本',box))return;
  const signal=state.detailRequest.signal;
  let snapshot=null,sequence=0;
  const parameters={id,conversation_id:cid};
  const versionUrl=(v,inline=false)=>'/api/workbench/artifacts/version_download'+query({...parameters,version_id:v,inline:inline?'1':undefined});
  async function preview(item,area){
    const seq=++sequence;
    area.replaceChildren();
    if(item.kind==='image'&&item.mime_type!=='image/svg+xml'){
      area.append(el('img',{src:versionUrl(item.id,true),alt:'保存版本预览',onerror:()=>{if(seq===sequence)area.replaceChildren(message('版本图片不可读取，请刷新或下载核验'));}}));return;
    }
    if(item.kind!=='text'){area.append(message('此版本不支持在线预览，可下载查看。','note'));return;}
    async function loadPage(offset,previous){
      area.replaceChildren(message('读取保存版本…','loading'));
      try{
        const page=await wb('artifacts/version_preview'+query({...parameters,version_id:item.id,offset}),{signal});
        if(seq!==sequence||signal.aborted)return;
        if(page.version_id!==item.id)throw new Error('预览版本已改变，请重新打开');
        const prev=button('上一页',()=>loadPage(previous.at(-1),previous.slice(0,-1))),next=button('下一页',()=>loadPage(page.next_offset,[...previous,offset]));
        prev.disabled=!previous.length;next.disabled=page.eof;
        area.replaceChildren(el('p',{class:'wb-note'},`${page.encoding} · 字符 ${offset}–${page.next_offset} / ${page.characters} · ${bytes(page.size)}`),actions(prev,next),el('pre',{class:'wb-pre wb-document-preview',tabindex:'0'},page.text));
      }catch(error){if(!signal.aborted&&seq===sequence)area.replaceChildren(message(error.message),button('重试读取',()=>loadPage(offset,previous)));}
    }
    await loadPage(0,[]);
  }
  async function restore(item){
    const expected=snapshot;
    await confirmAction('恢复附件版本？',`将「${expected.filename}」的当前文件替换为 ${item.id.slice(0,12)}。当前可读取内容会先保存为版本；不会发送新消息或自动运行 AI。`,async()=>{
      state.detailSaving=true;
      try{
        const result=await wb('artifacts/restore_version',{data:{...parameters,version_id:item.id,generation:expected.generation,fingerprint:expected.current_file.fingerprint,confirm:true}});
        window.XGentChat?.attachmentChanged({conversation_id:cid,generation:expected.generation,record_id:result.message.id,message:result.message});
        window.dispatchEvent(new CustomEvent('xgent-workbench-change',{detail:{pages:['files']}}));
      }finally{state.detailSaving=false;}
    },null,async()=>{await load();if(box.isConnected)inlineState(box,'已恢复指定版本；下一次模型请求读取当前文件。');});
  }
  async function load(){
    const loadSequence=++sequence;box.replaceChildren(message('读取版本记录…','loading'));
    try{
      const loaded=await wb('artifacts/versions'+query(parameters),{signal});
      if(signal.aborted||loadSequence!==sequence||!box.isConnected)return;
      snapshot=loaded;
      const current=snapshot.current_file,area=el('div',{class:'version-preview'});
      box.replaceChildren(...[el('h2',{class:'wb-detail-filename'},snapshot.filename),el('p',{class:'wb-note'},'保留上传原件（旧附件为升级后基准）及最近 10 个不同内容版本；只记录已观察到的内容，未观察到的外部改写无法还原。'),
        el('p',{class:'version-current'},'当前磁盘：'+({available:'可读取',missing:'文件缺失',damaged:'格式损坏或不支持',unreadable:'不可读取'})[current.state]+(current.id?' · '+current.id.slice(0,12):'')),
        current.warning?message(current.warning):null,current.error?message(current.error):null,
        snapshot.restore_reason?el('p',{class:'wb-note'},snapshot.restore_reason):null,button('刷新版本',load)].filter(node=>node!==null));
      const list=el('div',{class:'version-list'});
      for(const item of snapshot.versions){
        const seed=item.id===snapshot.seed,label=seed?(snapshot.seed_kind==='original'?'上传原件':'升级后首次保存版本'):'已保存版本';
        const disabled=!snapshot.can_restore||!current.fingerprint||item.id===current.id;
        const restoreButton=button('恢复此版本',()=>restore(item));restoreButton.disabled=disabled;
        restoreButton.title=item.id===current.id?'当前文件已是此版本':snapshot.restore_reason||(!current.fingerprint?'当前文件不可读，不能覆盖':'');
        list.append(el('section',{class:'version-card','data-version-id':item.id},el('strong',{},label+(item.id===current.id?' · 当前':'')),el('code',{},item.id.slice(0,16)),el('p',{class:'wb-note'},`${stamp(item.saved_at)} · ${bytes(item.size)} · ${item.mime_type}`),actions(button('预览版本',()=>preview(item,area)),el('a',{href:versionUrl(item.id),download:snapshot.filename,class:'wb-btn'},'下载版本'),restoreButton)));
      }
      if(!snapshot.versions.length)list.append(message('尚无已保存版本；当前文件恢复可读后会自动留版。','note'));
      box.append(list,area);
    }catch(error){if(!signal.aborted&&loadSequence===sequence&&box.isConnected)box.replaceChildren(message(error.message),button('重试读取版本',load));}
  }
  await load();
}
window.addEventListener('xgent-attachment-changed',()=>{pageCache.invalidate(['files']);state.retryAfter=0;});

function libraryMediaUrl(file){
  if(!safeLocalUrl(file.download_url))return '';
  const url=new URL(file.download_url,location.origin),cid=file.source?.conversation_id||file.conversation_id;
  if(cid)url.searchParams.set('conversation_id',cid);
  return url.pathname+url.search;
}

async function fileDetail(file) {
  if(file.kind==='output'){await outputViewer(file.path,file.filename,null,file.source);return;}
  const box=el('div',{},el('h2',{class:'wb-detail-filename'},file.filename||'文件'));
  const url=libraryMediaUrl(file);
  if(!detail('文件详情',box))return;const signal=state.detailRequest.signal;
  const metadata=el('dl',{class:'wb-file-facts'},...Object.entries({'类型':file.mime_type||file.kind||'未知','大小':bytes(file.size),'时间':stamp(file.timestamp),'完整路径':file.path||'路径未记录'}).map(([k,v])=>el('div',{class:'wb-detail-row'},el('dt',{},k),el('dd',{},v))));
  if(file.path)box.append(button('复制完整路径',()=>copyText(file.path).catch(error=>showError(box,error))));
  box.append(sourceLink(file.source),metadata);
  if(file.versions_id)box.append(button('版本 · 查看或恢复',()=>attachmentVersions(file)));
  if(file.error){box.append(message(file.error));return;}
  if(!safeLocalUrl(url)){box.append(message('文件地址无效或已缺失，请重新加载记录。'));return;}
  const tools=actions(el('a',{href:url,download:file.filename,class:'wb-btn primary'},'下载原文件'));
  if(file.source?.conversation_id){const jump=sourceLink(file.source);jump.classList.add('wb-file-source-action');tools.append(jump);}
  box.append(tools,el('div',{class:'wb-spacer'}));
  if(file.kind==='photo'&&file.mime_type!=='image/svg+xml'){
    const retryArea=el('div',{class:'wb-image-error',hidden:true});
    const image=el('img',{src:url,alt:file.filename,decoding:'async',onload:()=>{retryArea.hidden=true;},onerror:()=>{
      if(signal.aborted)return;
      retryArea.hidden=false;
      retryArea.replaceChildren(message('图片暂时加载失败，可重试或下载原文件。'),button('重试图片',()=>{
        retryArea.hidden=true;const retry=new URL(url,location.origin);retry.searchParams.set('preview_retry',Date.now());image.src=retry.pathname+retry.search;
      }));
    }});box.append(image,retryArea);
  }
  else if(['video','audio'].includes(file.kind))box.append(el(file.kind,{src:url,controls:'',preload:'metadata'}));
  else {
    const preview=el('div');box.append(preview);let previous=[];
    async function load(offset,back){preview.replaceChildren(message('读取文件预览…','loading'));try{
      const page=await wb('artifacts/preview'+query({id:file.id,offset,conversation_id:file.source?.conversation_id}),{signal});previous=back;
      const pre=el('pre',{class:'wb-pre wb-document-preview',tabindex:'0','aria-label':'文件文本预览'},page.text);
      const prev=button('上一页',()=>load(previous.at(-1),previous.slice(0,-1)));
      const next=button('下一页',()=>load(page.next_offset,[...previous,offset]));prev.disabled=!back.length;next.disabled=page.eof;
      preview.replaceChildren(el('p',{class:'wb-note'},`${page.encoding} · ${bytes(offset)}–${bytes(page.next_offset)} / ${bytes(page.size)}`),
        actions(prev,next,button('复制本页',async()=>{try{await copyText(page.text);inlineState(preview,'本页已复制');}catch(e){showError(preview,e);}}),button('切换换行',()=>pre.classList.toggle('nowrap'))),pre);
    }catch(e){if(e.name==='AbortError')return;preview.replaceChildren(e.status===415?empty('原文件可下载',e.message):message(e.message));}}
    await load(0,[]);
  }
}


return {filePage,fileDetail,attachmentVersions};
}
