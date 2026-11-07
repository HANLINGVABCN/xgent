/* One isolated page component, reused inline and in the Telegram Web App view. */
const instances=new Set();
const csp="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
const esc=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function requested(recordId){const params=new URLSearchParams(location.hash.split('?')[1]||'');return params.get('visual')===String(recordId);}
export function syncVisualPage(entry,descriptor,recordId){
  if(!descriptor||descriptor.version!==2)return;
  const signature=JSON.stringify(descriptor);
  if(entry.visualPage?.signature===signature){if(requested(recordId))entry.visualPage.expand();return;}
  entry.visualPage?.destroy();
  const card=document.createElement('section');card.className='visual-page';card.setAttribute('aria-label',descriptor.title||'渲染页面');
  const bar=document.createElement('header'),title=document.createElement('strong'),controls=document.createElement('div');
  title.textContent=descriptor.title||'渲染页面';bar.append(title,controls);
  const expand=document.createElement('button');expand.type='button';expand.textContent='展开页面';expand.setAttribute('aria-expanded','false');
  const download=document.createElement('a');download.textContent='源码';download.href=descriptor.source_url;download.download='';
  const retry=document.createElement('button');retry.type='button';retry.textContent='重新加载';retry.hidden=true;controls.append(download,retry,expand);
  const status=document.createElement('p');status.className='visual-page-status';status.textContent='正在渲染页面…';
  const frame=document.createElement('iframe');frame.className='visual-page-frame';frame.title=descriptor.title||'渲染页面';
  frame.setAttribute('sandbox','allow-scripts');frame.referrerPolicy='no-referrer';frame.loading='lazy';
  frame.style.height=Math.max(120,Math.min(1200,descriptor.height||600))+'px';
  card.append(bar,status,frame);entry.body.replaceChildren(card);
  let controller,token='',version=0,expanded=false,previousFocus;
  function setExpanded(value){
    expanded=value;card.classList.toggle('visual-page-expanded',value);card.setAttribute('role',value?'dialog':'region');
    card.setAttribute('aria-modal',String(value));expand.textContent=value?'关闭页面':'展开页面';expand.setAttribute('aria-expanded',String(value));
    if(value){previousFocus=document.activeElement;expand.focus({preventScroll:true});}
    else{previousFocus?.focus({preventScroll:true});if(requested(recordId)){const url=new URL(location.href),params=new URLSearchParams(url.hash.split('?')[1]||'');params.delete('visual');url.hash='/chat?'+params;history.replaceState(null,'',url);}}
  }
  async function load(){
    controller?.abort();controller=new AbortController();const current=++version;
    retry.hidden=true;status.hidden=false;status.textContent='正在渲染页面…';
    try{
      const response=await fetch(descriptor.url,{credentials:'same-origin',signal:controller.signal});const page=await response.json();
      if(!response.ok)throw new Error(page.error||'页面读取失败');
      if(current!==version||!card.isConnected)return;
      if(page.version!==2||typeof page.source!=='string'||page.source.length>262144)throw new Error('页面内容无效');
      token=crypto.randomUUID();
      const bridge=`<script>(()=>{let last=0;const send=()=>{const body=document.body;if(!body)return;const height=Math.ceil(body.getBoundingClientRect().height);if(height===last)return;last=height;parent.postMessage({type:'xgent-visual-size',token:${JSON.stringify(token)},height},'*');};addEventListener('load',send);addEventListener('resize',send);addEventListener('DOMContentLoaded',()=>{new ResizeObserver(send).observe(document.body);send();});})();</script>`;
      const base='<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="'+esc(csp)+'"><style>html,body{margin:0;min-height:0}body{font-family:system-ui,sans-serif}svg{max-width:100%}body>svg{display:block;width:100%;height:auto}</style>';
      frame.srcdoc='<!doctype html>'+base+bridge+page.source;
      frame.onload=()=>{if(current===version){status.hidden=true;}};
    }catch(error){if(error.name==='AbortError')return;status.textContent=error.message;retry.hidden=false;}
  }
  const instance={signature,expand:()=>setExpanded(true),destroy:()=>{controller?.abort();instances.delete(instance);card.remove();},
    frame,receive:data=>{if(data.token!==token||!Number.isFinite(data.height))return;frame.style.height=Math.max(120,Math.min(1600,data.height))+'px';},close:()=>{if(expanded)setExpanded(false);}};
  entry.visualPage=instance;instances.add(instance);
  expand.onclick=()=>setExpanded(!expanded);retry.onclick=load;
  if(requested(recordId))setExpanded(true);load();
}
window.addEventListener('message',event=>{if(event.data?.type!=='xgent-visual-size')return;for(const instance of instances)if(event.source===instance.frame.contentWindow)instance.receive(event.data);});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const instance of instances)instance.close();});
window.addEventListener('xgent-auth-expired',()=>{for(const instance of instances)instance.destroy();});
