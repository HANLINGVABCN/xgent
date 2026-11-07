/* Progressive reply pages. Each fence completes independently of its reply. */
const instances=new Set();
const csp="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
const esc=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const base='<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="'+esc(csp)+'"><style>html,body{margin:0;min-height:0}html{zoom:.8!important}body{width:80%!important;margin-left:auto!important;margin-right:auto!important;font-family:system-ui,sans-serif}svg{max-width:100%}body>svg{display:block;width:100%;height:auto}</style>';
const icon=path=>'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="'+path+'"/></svg>';
const codeIcon=icon('M8 6 2 12l6 6m8-12 6 6-6 6');
const expandIcon=icon('M5 19 19 5M5 13v6h6M13 5h6v6');
const collapseIcon=icon('m5 19 6-6M5 13h6v6m8-14-6 6M13 5v6h6');
function requested(recordId,index=0){const params=new URLSearchParams(location.hash.split('?')[1]||'');return params.get('visual')===String(recordId)&&params.get('visual_full')==='1'&&Number(params.get('visual_index')||0)===index;}

// Runs in the opaque-origin frame. Draft updates keep existing SVG nodes and
// CSS animations alive; unfinished scripts and event handlers remain inert.
function draftRuntime(token){
  const report=()=>parent.postMessage({type:'xgent-visual-size',token,height:Math.ceil(document.body.getBoundingClientRect().height)},'*');
  function attrs(target,source){
    for(const attr of Array.from(target.attributes))if(!source.hasAttribute(attr.name))target.removeAttribute(attr.name);
    for(const attr of source.attributes)if(target.getAttribute(attr.name)!==attr.value)target.setAttribute(attr.name,attr.value);
  }
  function patch(target,source){
    for(let i=0;i<source.childNodes.length;i++){
      const next=source.childNodes[i];let old=target.childNodes[i];
      if(!old){target.append(next.cloneNode(true));continue;}
      if(old.nodeType!==next.nodeType||old.nodeName!==next.nodeName){target.replaceChild(next.cloneNode(true),old);continue;}
      if(next.nodeType===1){attrs(old,next);patch(old,next);}
      else if(old.nodeValue!==next.nodeValue)old.nodeValue=next.nodeValue;
    }
    while(target.childNodes.length>source.childNodes.length)target.lastChild.remove();
  }
  const styles=document.createElement('div');styles.hidden=true;document.head.append(styles);
  addEventListener('message',event=>{
    const data=event.data;if(event.source!==parent||data?.type!=='xgent-visual-draft'||data.token!==token||typeof data.source!=='string'||data.source.length>262144)return;
    const parsed=new DOMParser().parseFromString(data.source,'text/html');
    parsed.querySelectorAll('script,iframe,object,embed,base,link,meta').forEach(node=>node.remove());
    parsed.querySelectorAll('*').forEach(node=>{for(const attr of Array.from(node.attributes))if(/^on/i.test(attr.name)||/^\s*javascript:/i.test(attr.value))node.removeAttribute(attr.name);});
    const head=document.createElement('div');for(const style of parsed.head.querySelectorAll('style'))head.append(style.cloneNode(true));patch(styles,head);
    attrs(document.body,parsed.body);patch(document.body,parsed.body);report();
    parent.postMessage({type:'xgent-visual-painted',token,visible:!!document.body.querySelector('svg,canvas,img,article,main,section,div,button,h1,p')||!!document.body.textContent.trim()},'*');
  });
  new ResizeObserver(report).observe(document.body);report();parent.postMessage({type:'xgent-visual-draft-ready',token},'*');
}

export function syncVisualPage(entry,descriptor,recordId,mount=entry.body){
  if(!descriptor||descriptor.version!==2)return;
  if(entry.visualPage){entry.visualPage.update(descriptor,recordId);return;}
  const pending=mount.querySelector('.visual-page-loading');
  const card=pending||document.createElement('section');card.className='visual-page visual-page-loading';card.setAttribute('aria-busy','true');
  const bar=document.createElement('header'),title=document.createElement('strong'),controls=document.createElement('div');
  const identity=document.createElement('span');identity.className='visual-page-identity';identity.append(title);bar.append(identity,controls);
  const expand=document.createElement('button');expand.type='button';expand.className='visual-page-icon';expand.innerHTML=expandIcon;expand.title='展开页面';expand.setAttribute('aria-label','展开页面');expand.setAttribute('aria-expanded','false');
  const sourceToggle=document.createElement('button');sourceToggle.type='button';sourceToggle.className='visual-page-icon';sourceToggle.innerHTML=codeIcon;sourceToggle.title='源码';sourceToggle.setAttribute('aria-label','源码');sourceToggle.setAttribute('aria-pressed','false');
  const copy=document.createElement('button');copy.type='button';copy.textContent='复制';copy.hidden=true;
  const download=document.createElement('a');download.textContent='下载';download.download='';download.hidden=true;
  const retry=document.createElement('button');retry.type='button';retry.textContent='重新加载';retry.hidden=true;controls.append(sourceToggle,copy,download,retry,expand);
  const status=document.createElement('span');status.className='visual-page-phase';identity.append(status);
  const viewport=pending?.querySelector('.visual-page-viewport')||document.createElement('div');viewport.className='visual-page-viewport';
  viewport.style.height=(pending?viewport.getBoundingClientRect().height:360)+'px';
  const skeleton=viewport.querySelector('.visual-page-skeleton')||document.createElement('div');skeleton.className='visual-page-skeleton';skeleton.setAttribute('aria-hidden','true');
  if(!skeleton.children.length)skeleton.innerHTML='<span></span><span></span><span></span>';
  const sourceView=document.createElement('pre');sourceView.className='visual-page-source';sourceView.hidden=true;const code=document.createElement('code');sourceView.append(code);
  let frame=document.createElement('iframe');frame.className='visual-page-frame';frame.setAttribute('sandbox','allow-scripts');frame.referrerPolicy='no-referrer';
  viewport.replaceChildren(frame,skeleton,sourceView);card.replaceChildren(bar,viewport);if(!pending)mount.replaceChildren(card);
  let controller,token='',revision=0,expanded=false,previousFocus,sourceMode=false,pageHeight=360;
  let current,owner=recordId,source=null,complete=false,draftReady=false,draftStarted=false,timer,blobUrl,destroyed=false,renderedSource=null,downloadKey;
  function setSourceMode(value){
    sourceMode=value;sourceView.hidden=!value;viewport.querySelectorAll('iframe').forEach(node=>node.hidden=value);card.classList.toggle('visual-source-mode',value);
    copy.hidden=download.hidden=!value;sourceToggle.title=value?'预览':'源码';sourceToggle.setAttribute('aria-label',sourceToggle.title);sourceToggle.setAttribute('aria-pressed',String(value));
    viewport.style.height=(value?Math.max(240,Math.min(600,pageHeight)):pageHeight)+'px';
  }
  function setExpanded(value){
    expanded=value;card.classList.toggle('visual-page-expanded',value);card.setAttribute('role',value?'dialog':'region');
    card.setAttribute('aria-modal',String(value));expand.innerHTML=value?collapseIcon:expandIcon;expand.title=value?'关闭页面':'展开页面';expand.setAttribute('aria-label',expand.title);expand.setAttribute('aria-expanded',String(value));
    if(value){previousFocus=document.activeElement;expand.focus({preventScroll:true});}
    else{previousFocus?.focus({preventScroll:true});if(requested(owner,current.index||0)){const url=new URL(location.href),params=new URLSearchParams(url.hash.split('?')[1]||'');params.delete('visual_full');url.hash='/chat?'+params;history.replaceState(null,'',url);}}
  }
  function showPreview(){card.classList.remove('visual-page-loading','visual-page-error');card.classList.add('visual-page-ready');card.setAttribute('aria-busy',String(!complete));}
  function updateDownload(){
    const key=current.source_url||(complete?source:null);if(key===downloadKey)return;downloadKey=key;
    if(blobUrl){URL.revokeObjectURL(blobUrl);blobUrl=null;}
    if(current.source_url)download.href=current.source_url;
    else if(complete&&source){blobUrl=URL.createObjectURL(new Blob([source],{type:current.format==='svg'?'image/svg+xml':'text/html'}));download.href=blobUrl;}
    else download.removeAttribute('href');
    download.download='page.'+(current.format||'html');
  }
  function flushDraft(){
    timer=null;if(destroyed||complete||!draftReady)return;
    frame.contentWindow.postMessage({type:'xgent-visual-draft',token,source:source||''},'*');
  }
  function renderDraft(){
    if(!draftStarted){
      draftStarted=true;draftReady=false;token=crypto.randomUUID();
      frame.srcdoc='<!doctype html><html><head>'+base+'</head><body><script>('+draftRuntime.toString()+')('+JSON.stringify(token)+');</script></body></html>';
    }
    if(!timer)timer=setTimeout(flushDraft,120);
  }
  function renderComplete(){
    if(renderedSource===source)return;renderedSource=source;clearTimeout(timer);timer=null;draftReady=false;
    token=crypto.randomUUID();const activeToken=token;
    const bridge=`<script>(()=>{const send=()=>{if(document.body)parent.postMessage({type:'xgent-visual-size',token:${JSON.stringify(token)},height:Math.ceil(document.body.getBoundingClientRect().height)},'*');};addEventListener('load',send);addEventListener('resize',send);addEventListener('DOMContentLoaded',()=>{new ResizeObserver(send).observe(document.body);send();});})();</script>`;
    // Keep the last draft visible until the complete page is ready.
    const next=document.createElement('iframe');next.className='visual-page-frame visual-page-staging';next.title=current.title||'渲染页面';next.setAttribute('sandbox','allow-scripts');next.referrerPolicy='no-referrer';next.hidden=sourceMode;
    const old=frame;frame=next;viewport.insertBefore(next,old);old.className='visual-page-previous';
    next.onload=()=>{if(destroyed||token!==activeToken)return;requestAnimationFrame(()=>{if(destroyed||token!==activeToken)return;next.classList.remove('visual-page-staging');old.remove();showPreview();status.hidden=true;});};
    next.srcdoc='<!doctype html>'+base+bridge+source;
  }
  function accept(page){
    if(typeof page.source!=='string'||page.source.length>262144)throw new Error('页面内容无效');
    const isComplete=page.streaming!==true;
    if(complete&&!isComplete)return;
    const unchanged=source===page.source&&complete===isComplete;
    source=page.source;complete=isComplete;if(code.textContent!==source)code.textContent=source;
    status.textContent=complete?'准备预览…':'生成中…';status.hidden=complete&&renderedSource===source;
    if(!unchanged)card.setAttribute('aria-busy','true');frame.title=current.title||'渲染页面';updateDownload();
    if(!unchanged){if(complete)renderComplete();else renderDraft();}
  }
  async function load(){
    controller?.abort();controller=new AbortController();const activeRevision=++revision;retry.hidden=true;
    try{
      const response=await fetch(current.url,{credentials:'same-origin',signal:controller.signal});const page=await response.json();
      if(!response.ok)throw new Error(page.error||'页面读取失败');
      if(activeRevision!==revision||destroyed||!card.isConnected)return;
      if(page.version!==2)throw new Error('页面内容无效');accept({...page,streaming:false});
    }catch(error){if(error.name==='AbortError')return;status.hidden=false;status.textContent=error.message;retry.hidden=false;card.classList.add('visual-page-error');card.classList.remove('visual-page-loading');card.setAttribute('aria-busy','false');}
  }
  const instance={
    get frame(){return frame;},
    update(page,id){
      current=page;if(id!=null)owner=id;title.textContent=page.title||'渲染页面';card.setAttribute('aria-label',title.textContent);
      if(typeof page.source==='string'){controller?.abort();revision++;accept(page);}
      else if(source===null)load();else updateDownload();
      if(requested(owner,page.index||0))setExpanded(true);
    },
    expand:()=>setExpanded(true),
    destroy:()=>{destroyed=true;clearTimeout(timer);controller?.abort();if(blobUrl)URL.revokeObjectURL(blobUrl);instances.delete(instance);card.remove();},
    receive(data){
      if(data.token!==token)return;
      if(data.type==='xgent-visual-draft-ready'){draftReady=true;flushDraft();}
      else if(data.type==='xgent-visual-painted'&&data.visible)showPreview();
      else if(data.type==='xgent-visual-size'&&Number.isFinite(data.height)&&!sourceMode){pageHeight=Math.max(120,Math.min(1600,data.height));viewport.style.height=pageHeight+'px';}
    },
    close:()=>{if(expanded)setExpanded(false);}
  };
  entry.visualPage=instance;instances.add(instance);
  expand.onclick=()=>setExpanded(!expanded);retry.onclick=()=>{renderedSource=null;if(current.url)load();else if(complete)renderComplete();else{draftStarted=false;renderDraft();}};
  sourceToggle.onclick=()=>setSourceMode(!sourceMode);
  copy.onclick=async()=>{try{await navigator.clipboard.writeText(code.textContent);copy.textContent='已复制';setTimeout(()=>copy.textContent='复制',1600);}catch{copy.textContent='复制失败';}};
  instance.update(descriptor,recordId);
}

export function syncReplyPages(entry,pages,recordId,display=entry.webDisplay){
  const descriptors=new Map((Array.isArray(pages)?pages:[]).map(page=>[page.index,page]));
  for(const segment of display?.segments||[]){
    if(!Number.isSafeInteger(segment.visual_index)||typeof segment.visual_source!=='string')continue;
    const index=segment.visual_index;
    descriptors.set(index,{...descriptors.get(index),version:2,index,title:segment.visual_title,format:segment.visual_format,source:segment.visual_source,streaming:segment.visual_pending===true});
  }
  const mounted=entry.visualPages||=new Map(),keep=new Set();
  for(const [index,descriptor] of descriptors){
    if(!Number.isSafeInteger(index)||index<0||index>=4)continue;
    const slot=entry.body.querySelector('[data-visual-index="'+index+'"]');if(!slot)continue;
    keep.add(index);let child=mounted.get(index);
    if(child?.body!==slot){child?.visualPage?.destroy();child={body:slot};mounted.set(index,child);}
    syncVisualPage(child,descriptor,recordId,slot);
  }
  for(const [index,child] of mounted)if(!keep.has(index)){child.visualPage?.destroy();mounted.delete(index);}
}
window.addEventListener('message',event=>{if(!event.data?.type?.startsWith('xgent-visual-'))return;for(const instance of instances)if(event.source===instance.frame.contentWindow)instance.receive(event.data);});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const instance of instances)instance.close();});
window.addEventListener('xgent-auth-expired',()=>{for(const instance of instances)instance.destroy();});
