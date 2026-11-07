/* One isolated page component, reused inline and in the Telegram Web App view. */
const instances=new Set();
const csp="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
const esc=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function requested(recordId,index=0){const params=new URLSearchParams(location.hash.split('?')[1]||'');return params.get('visual')===String(recordId)&&params.get('visual_full')==='1'&&Number(params.get('visual_index')||0)===index;}
export function syncVisualPage(entry,descriptor,recordId,mount=entry.body){
  if(!descriptor||descriptor.version!==2)return;
  const signature=JSON.stringify(descriptor);
  if(entry.visualPage?.signature===signature){if(requested(recordId,descriptor.index||0))entry.visualPage.expand();return;}
  entry.visualPage?.destroy();
  const pending=mount.querySelector('.visual-page-loading');
  const card=pending||document.createElement('section');card.className='visual-page visual-page-loading';card.setAttribute('aria-label',descriptor.title||'渲染页面');card.setAttribute('aria-busy','true');
  const bar=document.createElement('header'),title=document.createElement('strong'),controls=document.createElement('div');
  const identity=document.createElement('span');identity.className='visual-page-identity';
  title.textContent=descriptor.title||'渲染页面';identity.append(title);bar.append(identity,controls);
  const expand=document.createElement('button');expand.type='button';expand.textContent='展开页面';expand.setAttribute('aria-expanded','false');
  const sourceToggle=document.createElement('button');sourceToggle.type='button';sourceToggle.textContent='源码';sourceToggle.setAttribute('aria-pressed','false');
  const copy=document.createElement('button');copy.type='button';copy.textContent='复制';copy.hidden=true;
  const download=document.createElement('a');download.textContent='下载';download.href=descriptor.source_url;download.download='';download.hidden=true;
  const retry=document.createElement('button');retry.type='button';retry.textContent='重新加载';retry.hidden=true;controls.append(sourceToggle,copy,download,retry,expand);
  const status=document.createElement('span');status.className='visual-page-phase';status.textContent='准备预览…';identity.append(status);
  const viewport=pending?.querySelector('.visual-page-viewport')||document.createElement('div');viewport.className='visual-page-viewport';
  viewport.style.height=(pending?viewport.getBoundingClientRect().height:360)+'px';
  const skeleton=viewport.querySelector('.visual-page-skeleton')||document.createElement('div');skeleton.className='visual-page-skeleton';skeleton.setAttribute('aria-hidden','true');
  if(!skeleton.children.length)skeleton.innerHTML='<span></span><span></span><span></span>';
  const sourceView=document.createElement('pre');sourceView.className='visual-page-source';sourceView.hidden=true;const code=document.createElement('code');sourceView.append(code);
  const frame=document.createElement('iframe');frame.className='visual-page-frame';frame.title=descriptor.title||'渲染页面';
  frame.setAttribute('sandbox','allow-scripts');frame.referrerPolicy='no-referrer';frame.loading='lazy';
  viewport.replaceChildren(frame,skeleton,sourceView);card.replaceChildren(bar,viewport);if(!pending)mount.replaceChildren(card);
  let controller,token='',version=0,expanded=false,previousFocus,sourceMode=false,pageHeight=360;
  function setSourceMode(value){
    sourceMode=value;sourceView.hidden=!value;frame.hidden=value;card.classList.toggle('visual-source-mode',value);
    copy.hidden=download.hidden=!value;sourceToggle.textContent=value?'预览':'源码';sourceToggle.setAttribute('aria-pressed',String(value));
    viewport.style.height=(value?Math.max(240,Math.min(600,pageHeight)):pageHeight)+'px';
  }
  function setExpanded(value){
    expanded=value;card.classList.toggle('visual-page-expanded',value);card.setAttribute('role',value?'dialog':'region');
    card.setAttribute('aria-modal',String(value));expand.textContent=value?'关闭页面':'展开页面';expand.setAttribute('aria-expanded',String(value));
    if(value){previousFocus=document.activeElement;expand.focus({preventScroll:true});}
    else{previousFocus?.focus({preventScroll:true});if(requested(recordId,descriptor.index||0)){const url=new URL(location.href),params=new URLSearchParams(url.hash.split('?')[1]||'');params.delete('visual_full');url.hash='/chat?'+params;history.replaceState(null,'',url);}}
  }
  async function load(){
    controller?.abort();controller=new AbortController();const current=++version;
    retry.hidden=true;status.hidden=false;status.textContent='准备预览…';card.classList.remove('visual-page-ready','visual-page-error');card.classList.add('visual-page-loading');card.setAttribute('aria-busy','true');
    try{
      const response=await fetch(descriptor.url,{credentials:'same-origin',signal:controller.signal});const page=await response.json();
      if(!response.ok)throw new Error(page.error||'页面读取失败');
      if(current!==version||!card.isConnected)return;
      if(page.version!==2||typeof page.source!=='string'||page.source.length>262144)throw new Error('页面内容无效');
      code.textContent=page.source;
      token=crypto.randomUUID();
      const bridge=`<script>(()=>{let last=0;const send=()=>{const body=document.body;if(!body)return;const height=Math.ceil(body.getBoundingClientRect().height);if(height===last)return;last=height;parent.postMessage({type:'xgent-visual-size',token:${JSON.stringify(token)},height},'*');};addEventListener('load',send);addEventListener('resize',send);addEventListener('DOMContentLoaded',()=>{new ResizeObserver(send).observe(document.body);send();});})();</script>`;
      const base='<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="'+esc(csp)+'"><style>html,body{margin:0;min-height:0}body{font-family:system-ui,sans-serif}svg{max-width:100%}body>svg{display:block;width:100%;height:auto}</style>';
      frame.onload=()=>{if(current!==version)return;requestAnimationFrame(()=>requestAnimationFrame(()=>{if(current!==version||!card.isConnected)return;status.hidden=true;card.classList.remove('visual-page-loading');card.classList.add('visual-page-ready');card.setAttribute('aria-busy','false');}));};
      frame.srcdoc='<!doctype html>'+base+bridge+page.source;
    }catch(error){if(error.name==='AbortError')return;status.textContent=error.message;retry.hidden=false;card.classList.add('visual-page-error');card.classList.remove('visual-page-loading');card.setAttribute('aria-busy','false');}
  }
  const instance={signature,expand:()=>setExpanded(true),destroy:()=>{controller?.abort();instances.delete(instance);card.remove();},
    frame,receive:data=>{if(data.token!==token||!Number.isFinite(data.height)||sourceMode)return;pageHeight=Math.max(120,Math.min(1600,data.height));viewport.style.height=pageHeight+'px';},close:()=>{if(expanded)setExpanded(false);}};
  entry.visualPage=instance;instances.add(instance);
  expand.onclick=()=>setExpanded(!expanded);retry.onclick=load;
  sourceToggle.onclick=()=>setSourceMode(!sourceMode);
  copy.onclick=async()=>{try{await navigator.clipboard.writeText(code.textContent);copy.textContent='已复制';setTimeout(()=>copy.textContent='复制',1600);}catch{copy.textContent='复制失败';}};
  if(requested(recordId,descriptor.index||0))setExpanded(true);load();
}
export function syncReplyPages(entry,pages,recordId){
  if(!Array.isArray(pages))return;
  const mounted=entry.visualPages||=new Map(),keep=new Set();
  for(const descriptor of pages){
    const index=descriptor.index;
    if(!Number.isSafeInteger(index)||index<0||index>=4)continue;
    const slot=entry.body.querySelector('[data-visual-index="'+index+'"]');if(!slot)continue;
    keep.add(index);let child=mounted.get(index);
    if(child?.body!==slot){child?.visualPage?.destroy();child={body:slot};mounted.set(index,child);}
    syncVisualPage(child,descriptor,recordId,slot);
  }
  for(const [index,child] of mounted)if(!keep.has(index)){child.visualPage?.destroy();mounted.delete(index);}
}
window.addEventListener('message',event=>{if(event.data?.type!=='xgent-visual-size')return;for(const instance of instances)if(event.source===instance.frame.contentWindow)instance.receive(event.data);});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const instance of instances)instance.close();});
window.addEventListener('xgent-auth-expired',()=>{for(const instance of instances)instance.destroy();});
