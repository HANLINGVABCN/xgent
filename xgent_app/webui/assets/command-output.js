/* Output bytes are requested only when the user opens their command's output. */
const icon=name=>'<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-'+name+'"/></svg>';
const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
const states={pending:'待执行',generating:'生成中',running:'运行中',success:'已运行',failed:'失败',stopped:'已停止',unknown:'执行记录'};
function button(label,fn,cls='command-text-button'){const b=node('button',cls,label);b.type='button';b.addEventListener('click',e=>{e.stopPropagation();fn();});return b;}
const copy=value=>navigator.clipboard.writeText(value);

export function enhanceCommandBlock(bq,text,{api,toast,saveFold,copyText=copy}){
  const raw=bq.getAttribute('data-raw')||'';let result=null,page=null,request=null,version=0,previous=[],open=false,inputOpen=true,foldTimer=null;
  bq.classList.add('pb','execution-block','command-with-output');bq._pbText=text;bq.dataset.webFold='1';
  const head=node('div','command-card-head'),toggle=button('',()=>setExpanded(!bq.classList.contains('expanded')),'pb-head pb-toggle execution-row command-main-toggle');
  const status=node('span','execution-label'),preview=node('span','execution-preview');
  toggle.innerHTML=icon('terminal');toggle.append(status,preview);toggle.insertAdjacentHTML('beforeend',icon('chev'));
  const out=button('查看输出',()=>setOutput(!(bq.classList.contains('expanded')&&open)),'command-output-button');out.title='按需读取命令输出';out.setAttribute('aria-expanded','false');head.append(toggle,out);
  const input=node('div','execution-code command-input');const inputHead=node('div','code-header'),actions=node('div','code-actions');
  const inputFold=button('',()=>{inputOpen=!inputOpen;drawPanels();},'command-input-toggle');inputFold.innerHTML=icon('chev')+'<span>命令</span>';inputHead.append(inputFold,actions);
  const copyCommand=button('复制命令',()=>copyText(text).then(()=>toast('已复制命令')).catch(()=>toast('复制失败',true)));copyCommand.setAttribute('aria-label','复制代码正文');
  actions.append(copyCommand,button('换行',()=>input.classList.toggle('command-wrap')));
  if(raw)actions.append(button('复制完整协议',()=>copyText(raw).then(()=>toast('已复制完整协议')).catch(()=>toast('复制失败',true))));
  const code=node('pre','execution-pre');code.dataset.enhanced='1';input.append(inputHead,code);
  bindBodyFold(code,'命令',()=>{inputOpen=false;drawPanels();});
  const error=node('div','command-error');error.hidden=true;
  const controls=node('div','command-live-controls');
  const output=node('section','command-output-section');output.hidden=true;
  const outputHead=node('div','command-output-head');const fold=button('',()=>setOutput(!open),'command-output-toggle');fold.innerHTML=icon('chev')+'<span>输出</span>';fold.setAttribute('aria-expanded','true');
  outputHead.append(fold);const outputBody=node('div','command-output-body');output.append(outputHead,outputBody);bq.replaceChildren(head,controls,input,error,output);
  function drawPanels(){
    const expanded=bq.classList.contains('expanded');input.hidden=!expanded;output.hidden=!expanded;code.hidden=!inputOpen;outputBody.hidden=!open;
    toggle.setAttribute('aria-expanded',String(expanded));toggle.setAttribute('aria-label',(expanded?'收起':'展开')+'命令与输出');
    inputFold.setAttribute('aria-expanded',String(inputOpen));inputFold.setAttribute('aria-label',(inputOpen?'收起':'展开')+'命令正文');
    fold.setAttribute('aria-expanded',String(open));fold.setAttribute('aria-label',(open?'收起':'展开')+'输出正文');
    out.setAttribute('aria-expanded',String(expanded&&open));out.textContent=expanded&&open?'收起输出':'查看输出';
    if(expanded&&inputOpen&&code.textContent!==text)code.textContent=text;
  }
  function cancelRead(){request?.abort();request=null;version++;}
  function bindBodyFold(pre,label,collapse){
    pre.title='点击收起'+label+'，拖动可选择文字';
    pre.addEventListener('click',event=>{
      clearTimeout(foldTimer);
      if(event.detail>1||getSelection()?.toString())return;
      foldTimer=setTimeout(()=>{if(pre.isConnected&&!getSelection()?.toString())collapse();},240);
    });
    pre.addEventListener('dblclick',()=>clearTimeout(foldTimer));
  }
  function setExpanded(value){
    bq.classList.toggle('expanded',value);drawPanels();saveFold?.(bq);
    if(value&&open&&!page)load(0);else if(!value)cancelRead();
  }
  function update(value){
    const changed=value?.result_record_id!=null&&result?.result_record_id!==value.result_record_id;
    if(value){const knownId=result?.result_record_id;result={...result,...value};if(result.result_record_id==null&&knownId!=null)result.result_record_id=knownId;}
    const state=result?.state||bq.dataset.state||'pending';bq.dataset.state=state;
    bq.classList.toggle('command-failed',state==='failed');bq.classList.toggle('command-running',state==='running');
    status.textContent=(bq.dataset.protocol||'命令')+' '+(states[state]||state)+(Number.isFinite(result?.elapsed_seconds)?' · '+result.elapsed_seconds.toFixed(1)+'s':'');
    preview.textContent=(bq.dataset.preview?bq.dataset.preview+' · ':'')+(text.split('\n').find(line=>line.trim())||'命令');
    error.textContent=result?.error||'';error.hidden=!error.textContent;
    out.disabled=state==='generating';
    out.title=result?.result_record_id?'按需读取命令输出':'输出尚未保存，点击查看执行状态';
    if(changed){page=null;previous=[];if(open&&bq.classList.contains('expanded'))load(0);}drawPanels();
  }
  function setOutput(value){
    open=value;
    if(value){bq.classList.add('expanded');saveFold?.(bq);}
    drawPanels();if(value){if(!page)load(0);}else cancelRead();
  }
  function drawPage(){
    if(!page)return;
    const tools=node('div','command-output-tools'),label=node('span','output-page-label',`${page.offset}–${page.next_offset} / ${page.size} 字节`),actions=node('div','command-page-actions');
    const prev=button('上一页',()=>{const next=previous.pop();load(next);});prev.disabled=!previous.length;
    const next=button('下一页',()=>{previous.push(page.offset);load(page.next_offset);});next.disabled=page.eof;
    actions.append(prev,next,button('复制本页',()=>copyText(page.text).then(()=>toast('已复制输出')).catch(()=>toast('复制失败',true))),button('下载完整输出',download));tools.append(label,actions);
    const pre=node('pre','output-page-text',page.text||'(无输出)');pre.dataset.enhanced='1';
    bindBodyFold(pre,'输出',()=>setOutput(false));
    outputBody.replaceChildren(tools,...(page.warning?[node('p','command-output-warning',page.warning)]:[]),pre);
    const details=node('details','command-result-details');details.append(node('summary',null,'执行信息'));
    const names={return_code:'返回码',elapsed_seconds:'耗时（秒）',session_id:'终端会话',status:'状态',running:'运行中',output_path:'存档路径',waited_seconds:'等待（秒）',archive_truncated:'存档截断',notice:'执行说明'};
    for(const [key,value] of Object.entries(page.details||{})){const pre=node('pre','command-result-detail',(names[key]||key)+'：'+String(value));pre.dataset.enhanced='1';details.append(pre);}
    const notice=node('div');let infoLoaded=false;details.append(notice);
    async function loadInfo(offset=0){
      try{const cid=bq.closest('[data-record-id]')?.dataset.presentationConversationId;
        const info=await api('/api/workbench/command-output?record_id='+result.result_record_id+'&conversation_id='+encodeURIComponent(cid||'')+'&view=info&offset='+offset);
        if(!details.isConnected)return;const pre=node('pre','command-result-detail',info.text);pre.dataset.enhanced='1';notice.replaceChildren(pre);
        if(!info.eof)notice.append(button('继续查看执行说明',()=>loadInfo(info.next_offset)));
      }catch(e){notice.replaceChildren(node('p','command-error',e.message));}}
    details.addEventListener('toggle',()=>{if(details.open&&!infoLoaded){infoLoaded=true;loadInfo();}});
    outputBody.append(details);
  }
  async function load(offset){
    request?.abort();request=new AbortController();const own=++version;const cid=bq.closest('[data-record-id]')?.dataset.presentationConversationId;
    if(!result?.result_record_id){outputBody.replaceChildren(node('p','output-page-label','命令正在执行，输出保存后显示。'));return;}
    outputBody.replaceChildren(node('p','output-page-label','正在读取输出…'));
    try{
      const data=await api('/api/workbench/command-output?record_id='+result.result_record_id+'&conversation_id='+encodeURIComponent(cid||'')+'&offset='+offset,{signal:request.signal});
      if(own!==version||!bq.isConnected||!open||!bq.classList.contains('expanded'))return;page=data;drawPage();
    }catch(e){if(e.name!=='AbortError'&&own===version)outputBody.replaceChildren(node('p','command-error','读取输出失败：'+e.message),button('重试',()=>load(offset)));}
  }
  async function download(){
    if(!result?.result_record_id)return;const cid=bq.closest('[data-record-id]')?.dataset.presentationConversationId;
    try{
      const parts=[];let offset=0;
      while(true){const part=await api('/api/workbench/command-output?record_id='+result.result_record_id+'&conversation_id='+encodeURIComponent(cid||'')+'&offset='+offset);parts.push(part.text);if(part.eof)break;if(part.next_offset<=offset)throw new Error('输出分页没有前进');offset=part.next_offset;}
      const url=URL.createObjectURL(new Blob(parts,{type:'text/plain;charset=utf-8'}));const a=node('a');a.href=url;a.download='命令输出.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){toast('下载失败：'+e.message,true);}
  }
  bq._commandUI={update,controls,restore:drawPanels,destroy:()=>{clearTimeout(foldTimer);cancelRead();}};update(null);
}

export function installCommandResults(log){
  const results=new Map();
  function reconcile(){
    for(const [entry,result] of results){
      if(!entry.row.isConnected){entry.btns?.remove();results.delete(entry);continue;}
      const cid=entry.row.dataset.presentationConversationId||'';
      const owner=Array.from(log.children).find(row=>row.dataset.recordId===String(result.reply_record_id)&&row.dataset.presentationConversationId===cid);
      const target=owner?.querySelector('[data-command-key="'+CSS.escape(result.key)+'"]');
      const attached=!!target?._commandUI;entry.row.classList.toggle('command-result-attached',attached);
      (attached?target:entry.body.querySelector('[data-command-key]'))?._commandUI?.update(result);
      // Move the original bound controls, retaining their run/phase identity.
      // A hidden result row must never hide its stop button or other actions.
      if(entry.btns){const host=attached?target._commandUI.controls:entry.bubble;if(entry.btns.parentNode!==host)host.append(entry.btns);}
    }
  }
  return {sync(entry,frame){updateCommandCards(entry,frame);const value=frame.command_result||frame.web_display?.command_result;if(value){entry.commandResult=value;results.set(entry,value);}reconcile();},
    remove(entry){
      if(results.has(entry)&&entry.btns?.parentNode!==entry.bubble)entry.btns?.remove();
      results.delete(entry);
      for(const source of results.keys())if(source.btns&&entry?.body?.contains(source.btns))source.bubble.append(source.btns);
      entry?.body?.querySelectorAll('[data-command-key]').forEach(bq=>bq._commandUI?.destroy());
    },reconcile};
}

export function updateCommandCards(entry,frame){
  for(const part of frame.web_display?.segments||[]){const info=part.command_info;if(!info?.key)continue;entry.body.querySelector('[data-command-key="'+CSS.escape(info.key)+'"]')?._commandUI?.update(info);}
  const result=frame.command_result||frame.web_display?.command_result;
  if(result)entry.body.querySelector('[data-command-key]')?._commandUI?.update(result);
}
