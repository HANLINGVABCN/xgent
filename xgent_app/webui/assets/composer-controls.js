/* Compact, retained composer controls. No native dropdown overlays or extra mobile rows. */
import {$,el} from './components.js';
let settings=null,onChange=null,active=null,saving=false,query='';
const compact=matchMedia('(max-width: 767px)');
const host=$('wb-chat-controls'),popover=$('composer-options-popover'),error=$('composer-option-error');
function icon(id){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('class','icon');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');const use=document.createElementNS(svg.namespaceURI,'use');use.setAttribute('href','#i-'+id);svg.append(use);return svg;}
function choice(id,label){return el('button',{id,type:'button',class:'composer-choice',role:'combobox','aria-label':label,'aria-haspopup':'listbox','aria-expanded':'false','aria-controls':'composer-choice-list'},el('span',{class:'composer-choice-label'}),icon('chev'));}
const thinking=choice('composer-thinking','思考深度'),model=choice('composer-model','对话模型');
const options=el('button',{id:'composer-generation-options',type:'button',class:'composer-choice composer-options-button','aria-label':'生成选项','aria-haspopup':'dialog','aria-expanded':'false','aria-controls':'composer-options-popover'},icon('settings'));
host.replaceChildren(thinking,model,options);
const labels={off:'关闭',none:'关闭',auto:'自动',low:'简短',medium:'标准',high:'深入',xhigh:'很高',ultra:'超高',max:'最高'};
function values(){return settings?.values||{};}
const responseModes=[{value:'foreground',label:'前台流式'},{value:'nonstream',label:'非流式'}];
const callModes=[{value:'toolcall',label:'Tool call'},{value:'fence',label:'正则围栏'}];
const numericSettings={agent_max_iterations:{label:'Agent 轮数',default:10},global_depth:{label:'记忆深度',default:30}};
function responseMode(){return values().web_response_mode||values().response_mode||(!values().stream_mode?'nonstream':'foreground');}
function choices(key){const source=key==='chat_model'?(settings?.options?.chat_model||[]):(settings?.options?.thinking_level||['auto','low','medium','high']);return source.map(value=>typeof value==='object'?{value:String(value.value),label:key==='thinking_level'?(labels[value.value]||String(value.label??value.value)):String(value.label??value.value)}:{value:String(value),label:labels[value]||String(value)});}
function label(key){const selected=choices(key).find(option=>option.value===String(values()[key]??''));return selected?.label||(key==='chat_model'?'选择模型':'自动');}
function setChoice(node,key){const text=label(key);node.querySelector('.composer-choice-label').textContent=text;node.title=text;node.dataset.value=String(values()[key]??'');}
function refreshCurrentModel(){const node=popover.querySelector('.composer-current-model');if(!node)return;const selected=String(values().chat_model||''),separator=selected.indexOf('|');const name=separator<0?'':selected.slice(0,separator)+' / '+selected.slice(separator+1);node.textContent=name;node.title=name;node.hidden=!name;}
function refresh(){setChoice(model,'chat_model');setChoice(thinking,'thinking_level');refreshCurrentModel();options.classList.toggle('agent-on',!!values().agent_mode);options.title='生成选项 · '+responseModes.find(item=>item.value===responseMode()).label;for(const node of [thinking,model,options])node.disabled=saving||!settings;}
function close(restore=false){if(!active)return;const trigger=active.trigger,lineage=$('conversation-lineage');trigger.setAttribute('aria-expanded','false');active=null;popover.hidden=true;if(lineage)lineage.hidden=true;popover.replaceChildren(...(lineage?[lineage]:[]));query='';if(restore&&trigger.isConnected&&trigger.getClientRects().length)trigger.focus({preventScroll:true});}
function position(){if(!active)return;const composer=$('composer').getBoundingClientRect(),trigger=active.trigger.getBoundingClientRect(),viewport=window.visualViewport,lineage=$('conversation-lineage');const top=viewport?.offsetTop||0;const width=Math.min((active.kind==='chat_model'||active.kind==='generation'&&lineage&&!lineage.hidden)?360:300,composer.width);popover.style.width=width+'px';popover.style.left=Math.max(0,Math.min(trigger.left-composer.left,composer.width-width))+'px';popover.style.maxHeight=Math.max(60,Math.min(420,composer.top-top-8))+'px';}
async function save(key,value){if(saving)return;const previous=active;saving=true;error.hidden=true;refresh();popover.setAttribute('aria-busy','true');popover.querySelectorAll('button,input').forEach(node=>node.disabled=true);try{await onChange(key,value);if(active===previous)close(true);}catch(exception){error.textContent=exception.message||'选项保存失败，请重试';error.hidden=false;}finally{saving=false;popover.removeAttribute('aria-busy');refresh();if(active)render();}}
function list(key){const list=el('div',{id:'composer-choice-list',class:'composer-choice-list',role:'listbox','aria-label':key==='chat_model'?'对话模型':'思考深度'});const selected=String(values()[key]??'');let count=0;for(const item of choices(key)){if(query&&!item.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()))continue;const button=el('button',{type:'button',class:'composer-option',role:'option','aria-selected':item.value===selected,'data-value':item.value,onclick:()=>save(key,item.value)},el('span',{},item.label),item.value===selected?icon('check'):null);list.append(button);count++;}if(!count)list.append(el('p',{class:'composer-options-empty'},query?'没有匹配的模型':'尚未配置模型，请在设置中添加提供商。'));return list;}
function showSetting(kind){active={...active,kind,numberValue:undefined};render();}
function settingButton(key,label,value,onclick,attrs={}){return el('button',{type:'button',class:'composer-setting-button','data-setting':key,'aria-label':label,onclick,...attrs},el('span',{class:'composer-setting-label'},label),el('span',{class:'composer-setting-value'},String(value)));}
function render(){
  if(!active)return;
  const kind=active.kind,lineage=$('conversation-lineage');
  const submenu=kind==='response_mode'||kind==='agent_call_mode'||!!numericSettings[kind];
  const title=kind==='chat_model'?'选择模型':kind==='generation'?'生成选项':kind==='response_mode'?'回复方式':kind==='agent_call_mode'?'工具调用方式':numericSettings[kind]?.label||'思考深度';
  const header=el('div',{class:'composer-options-head'},submenu?el('button',{type:'button','aria-label':'返回生成选项',onclick:()=>showSetting('generation')},'‹'):null,el('strong',{},title),kind==='chat_model'?el('span',{class:'composer-current-model'}):null,el('button',{type:'button','aria-label':'关闭选项',onclick:()=>close(true)},icon('close')));
  popover.replaceChildren(header,...(lineage?[lineage]:[]));
  refreshCurrentModel();
  if(lineage)lineage.hidden=kind!=='generation'||!lineage.childNodes.length;
  popover.setAttribute('role',kind==='generation'?'dialog':'group');
  if(kind==='generation'){
    const grid=el('div',{class:'composer-setting-grid'},
      settingButton('response_mode','回复方式',responseModes.find(item=>item.value===responseMode()).label,()=>showSetting('response_mode')),
      settingButton('agent_call_mode','工具调用方式',callModes.find(item=>item.value===(values().agent_call_mode||'fence')).label,()=>showSetting('agent_call_mode')),
      settingButton('agent_mode','Agent 模式',values().agent_mode?'开启':'关闭',()=>save('agent_mode',!values().agent_mode),{role:'switch','aria-checked':String(!!values().agent_mode)}));
    for(const [key,setting] of Object.entries(numericSettings))grid.append(settingButton(key,setting.label,values()[key]??setting.default,()=>showSetting(key)));
    popover.append(grid);
  }else if(kind==='response_mode'||kind==='agent_call_mode'){
    const selected=kind==='response_mode'?responseMode():values().agent_call_mode||'fence';
    const group=el('div',{class:'composer-choice-list',role:'radiogroup','aria-label':title});
    for(const item of kind==='response_mode'?responseModes:callModes)group.append(el('button',{type:'button',class:'composer-option',role:'radio',
      'data-value':item.value,'aria-checked':String(item.value===selected),onclick:()=>save(kind,item.value)},el('span',{},item.label),item.value===selected?icon('check'):null));
    popover.append(group);
  }else if(numericSettings[kind]){
    const setting=numericSettings[kind];
    const input=el('input',{type:'number',min:1,step:1,inputmode:'numeric','aria-label':setting.label,value:active.numberValue??values()[kind]??setting.default});
    input.oninput=()=>active.numberValue=input.value;
    const form=el('form',{class:'composer-number-setting'},input,el('button',{type:'submit',class:'composer-number-save'},'保存'));
    form.onsubmit=event=>{event.preventDefault();const value=Number(input.value);if(!Number.isSafeInteger(value)||value<1){error.textContent='请输入大于 0 的整数';error.hidden=false;return;}save(kind,value);};
    popover.append(form);
  }
  if(kind==='chat_model'&&choices(kind).length>6){const search=el('input',{type:'search',class:'composer-model-search','aria-label':'搜索模型',placeholder:'搜索模型…',value:query});search.oninput=()=>{query=search.value;popover.querySelector('.composer-choice-list')?.replaceWith(list('chat_model'));position();};popover.append(search);}
  if(kind==='chat_model'||kind==='thinking_level')popover.append(list(kind));
  position();
}
function open(kind,trigger,fromKeyboard=false){if(!settings||saving)return;if(active?.trigger===trigger){close(true);return;}close();active={kind,trigger};trigger.setAttribute('aria-expanded','true');popover.hidden=false;render();if(fromKeyboard)(popover.querySelector('[role=option][aria-selected=true]')||popover.querySelector('[role=option]')||popover.querySelector('input,button'))?.focus({preventScroll:true});}
model.onclick=event=>open('chat_model',model,event.detail===0);thinking.onclick=event=>open('thinking_level',thinking,event.detail===0);options.onclick=event=>open('generation',options,event.detail===0);
for(const [node,kind] of [[model,'chat_model'],[thinking,'thinking_level'],[options,'generation']])node.addEventListener('keydown',event=>{if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();open(kind,node,true);}});
popover.addEventListener('keydown',event=>{if(event.isComposing)return;if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return;}if(event.target.matches('input'))return;const items=[...popover.querySelectorAll('[role=option]:not(:disabled),[role=radio]:not(:disabled),.composer-setting-button:not(:disabled)')];if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)&&items.length){event.preventDefault();let index=items.indexOf(document.activeElement);index=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowUp'?-1:1)+items.length)%items.length;items[index].focus();items[index].scrollIntoView({block:'nearest'});}if(event.key==='Tab'&&active?.kind!=='generation'&&!numericSettings[active?.kind])close(false);});
document.addEventListener('click',event=>{const path=event.composedPath();if(active&&!path.includes(popover)&&!path.includes(active.trigger))close(false);});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&active){event.preventDefault();close(true);}});
compact.addEventListener('change',()=>close(false));window.addEventListener('hashchange',()=>close(false));window.addEventListener('xgent-conversation-changed',()=>close(false));window.addEventListener('resize',position);window.visualViewport?.addEventListener('resize',position);window.visualViewport?.addEventListener('scroll',position);
if(window.ResizeObserver)new ResizeObserver(position).observe($('composer'));
window.addEventListener('xgent-auth-expired',()=>{close(false);settings=null;error.hidden=true;refresh();});
refresh();
export function updateComposerControls(data,change){settings=data;onChange=change;refresh();if(active&&!saving){const focus=popover.contains(document.activeElement);if(!focus)render();}}
