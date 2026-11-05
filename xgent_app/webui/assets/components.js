import {affectedPages} from './page-cache.js';
import {el,message} from './ui.js';
export {$,el,button,fmt,stamp,bytes,message,empty,field,select,check,table,formData} from './ui.js';
export async function api(path,{data,signal,...options}={}) {
  const cid=window.XGentConversations?.current;
  let requestPath=path;
  if(cid&&!window.XGentConversations?.readOnly&&path.startsWith('/api/workbench/')&&!path.includes('/conversations')){
    if(data===undefined){if(!new URL(path,location.origin).searchParams.has('conversation_id')&&['history','search','tasks','artifacts'].some(name=>path.startsWith('/api/workbench/'+name)))requestPath+= (path.includes('?')?'&':'?')+'conversation_id='+encodeURIComponent(cid);}
    else data={conversation_id:cid,...data};
  }
  const affected=data===undefined?[]:affectedPages(path,Array.isArray(data?.items)?data.items.map(item=>item?.key):data?.key);
  const changed=()=>{if(affected.length)window.dispatchEvent(new CustomEvent('xgent-workbench-change',{detail:{pages:affected}}));};
  // Invalidate both before and after: an in-flight read cannot make partial/late writes fresh.
  changed();
  try {
    const response=await fetch(requestPath,{credentials:'same-origin',...options,signal,method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});
    let body={};try{body=await response.json();}catch{}
    if(!response.ok||body.ok===false){const err=new Error(body.error||`请求失败 (${response.status})`);err.status=response.status;if(response.status===401)window.dispatchEvent(new Event('xgent-auth-expired'));throw err;}
    if(path==='/api/logout')window.dispatchEvent(new Event('xgent-auth-expired'));
    return body;
  } finally { changed(); }
}
export const wb=(name,options)=>api('/api/workbench/'+name,options);
export function download(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=el('a',{href:url,download:name});a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
export function query(values){return '?'+new URLSearchParams(Object.entries(values).filter(([,v])=>v!==null&&v!==undefined&&v!=='')).toString();}
export const statusLabel={scheduled:'已计划',pending:'待执行',running:'运行中',completed:'已完成',failed:'失败',cancelled:'已取消',enabled:'已启用',disabled:'已关闭',hidden:'已隐藏',waiting_delivery:'等待通知',condition_unmatched:'条件未命中',interrupted:'已中断',condition_matched:'条件命中',up:'正常',down:'不可用',degraded:'降级',connecting:'连接中'};
export function tag(status){return el('span',{class:'wb-tag '+(['up','completed','enabled','running'].includes(status)?'good':['failed','down'].includes(status)?'bad':'')},statusLabel[status]||status||'—');}

export async function copyText(text){
  if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(String(text));return;}
  const input=el('textarea',{readonly:''},String(text));input.style.position='fixed';input.style.opacity='0';document.body.append(input);input.select();
  try{if(!document.execCommand('copy'))throw new Error('无法访问剪贴板，请手动选择文本复制');}finally{input.remove();}
}

export function requestId(){
  if(crypto.randomUUID)return crypto.randomUUID().replaceAll('-','');
  return Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
}
export function safeLocalUrl(url){return typeof url==='string' && url.startsWith('/api/') && !url.includes('\\') && !/[\r\n]/.test(url);}
export function inlineState(container,text,kind='success'){container.querySelectorAll(':scope > .wb-success,:scope > .wb-error').forEach(n=>n.remove());container.append(message(text,kind));}
