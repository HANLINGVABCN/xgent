import {acceptBranding} from './branding.js';
const defaults = {web_message_font_size:16, web_ui_font_size:14, web_terminal_font_size:13};
const limits = {web_message_font_size:[12,24], web_ui_font_size:[12,20], web_terminal_font_size:[10,24]};
let state = {revision:-1, values:{...defaults}}, preview = null;
function apply(values) {
  const names = {web_message_font_size:'--web-message-font-size',web_ui_font_size:'--web-ui-font-size',web_terminal_font_size:'--web-terminal-font-size'};
  for (const key of Object.keys(defaults)) document.documentElement.style.setProperty(names[key], values[key]+'px');
  window.dispatchEvent(new CustomEvent('xgent-fonts-applied',{detail:values}));
  document.getElementById('terminal-iframe')?.contentWindow?.postMessage({type:'xgent-fonts',values},location.origin);
}
function accept(data) {
  acceptBranding(data);
  if (!data?.values || !Number.isSafeInteger(data.revision) || data.revision<state.revision) return;
  const values={...state.values};
  for (const [key,[min,max]] of Object.entries(limits)) {
    const value=data.values[key]; if(Number.isInteger(value)&&value>=min&&value<=max)values[key]=value;
  }
  state={revision:data.revision,values}; if(!preview)apply(values);
}
async function refresh(){
  // 未变化短路：revision 没变时服务端只回几十字节，不再重算完整 settings。
  const suffix=state.revision>=0?'?since='+state.revision:'';
  const response=await fetch('/api/config'+suffix,{credentials:'same-origin',cache:'no-store'});if(response.ok)accept(await response.json());
}
async function save(values){
  const payload={};
  for(const key of Object.keys(defaults)) {
    if(values[key]===undefined||Number(values[key])===state.values[key])continue;
    payload[key]=Number(values[key]);
  }
  if(Object.keys(payload).length) {
    // 一次批量往返；响应已平铺（values 在顶层），保存即时生效。
    const response=await fetch('/api/config',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({values:payload})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'字号保存失败');accept(data);
  }
  preview=null;apply(state.values);return state;
}
window.XGentAppearance={accept,refresh,save,defaults,limits,get state(){return state;},preview(values){preview={...state.values,...values};apply(preview);},cancelPreview(){preview=null;apply(state.values);}};
window.addEventListener('xgent-authenticated',()=>refresh().catch(()=>{}));
window.addEventListener('xgent-auth-expired',()=>{preview=null;state={revision:-1,values:{...defaults}};apply(defaults);});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh().catch(()=>{});});
apply(defaults);
// 未登录时这里是 401，refresh 内部直接忽略；登录后会再由事件触发。
refresh().catch(()=>{});

setInterval(()=>{if(!document.hidden&&state.revision>=0)refresh().catch(()=>{});},60000);
