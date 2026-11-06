import './appearance.js';
import {updateComposerControls} from './composer-controls.js';
import {PageCache} from './page-cache.js';
import {openGlobalSearch} from './global-search.js';
import {$,el,button,fmt,stamp,bytes,message,empty,field,select,check,table,formData,api,wb,download,query,tag,copyText,requestId,safeLocalUrl,inlineState} from './components.js';
import {heading,card,toolbar,actions,icon as sharedIcon,readPreference,writePreference} from './ui.js';
import {setThemeMode} from './theme.js';
import {appPages as pages,settingsSections as SETTINGS_SECTIONS,settingsPanels,panelNames,settingsNavigation} from './navigation.js';
const state={routed:false,authEpoch:0,route:'chat',boot:null,request:null,detailRequest:null,filters:{},scroll:{},dirty:false,authenticated:false,dialogReturn:null};
state.bootUpdatedAt=0;
state.panel='appearance';
try{const saved=sessionStorage.getItem('xgent-settings-panel');if(settingsPanels.some(([id])=>id===saved))state.panel=saved;}catch{}
const root=$('settings-content');
const pageCache=new PageCache(12);
state.pageKey=null;
state.renderSequence=0;
state.pendingKey=null;
state.retryAfter=0;
function pageKey(){return pageCache.key(state.route,state.filters[state.route]||{});}
function rememberPage(){
  const entry=pageCache.get(state.pageKey);
  if(entry && entry.content.parentNode===root){entry.scroll=root.scrollTop;state.scroll[entry.route]=root.scrollTop;}
}
function pageInteracting(){
  const focused=root.contains(document.activeElement) && document.activeElement.matches('input,textarea,select,button');
  const selection=window.getSelection();
  return state.dirty||state.submitting||$('wb-dialog').open||$('conversation-rename-dialog').open||!$('conversation-item-menu').hidden||document.getElementById('global-search-dialog')?.open||!$('wb-detail').hidden||focused||
    !!root.querySelector('input[type=checkbox]:checked:not([name])')||
    !!(selection&&!selection.isCollapsed&&root.contains(selection.anchorNode));
}
root.addEventListener('input',()=>{const entry=pageCache.get(state.pageKey);if(entry)entry.interaction++;});
root.addEventListener('change',()=>{const entry=pageCache.get(state.pageKey);if(entry)entry.interaction++;});
function cacheNotice(text,retry=false){
  root.querySelector(':scope > .wb-cache-notice')?.remove();
  if(!text)return;
  const notice=el('div',{class:'wb-cache-notice',role:'status'},el('span',{},text));
  if(retry)notice.append(button('重试更新',()=>render()));
  root.append(notice);
}
window.addEventListener('xgent-workbench-change',event=>{
  pageCache.invalidate(event.detail.pages);state.retryAfter=0;
  if(event.detail.pages.some(page=>page==='settings'||page==='models'))state.bootUpdatedAt=0;
});
window.addEventListener('xgent-turn-finished',()=>{
  pageCache.invalidate(['tasks','files','usage']);state.retryAfter=0;
  if(['tasks','files','usage'].includes(state.route))backgroundRefresh();
});
function icon(path){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',path);p.setAttribute('stroke-linejoin','round');p.setAttribute('stroke-linecap','round');svg.append(p);return svg;}
for(const container of [$('wb-nav-links')])for(const [id,title,path] of pages.filter(p=>p[0]!=='settings'))container.append(el('a',{href:'#/'+id,class:'wb-nav-item',role:'menuitem','data-route':id,title},icon(path),el('span',{},title)));
const routeName=()=>location.hash.replace(/^#\/?/,'').split('?')[0]||'chat';
// 缓存的页面外壳带着上次挂载时被 route() 改过的导航 class：每次挂载后按当前路由重打高亮。
function markRouteActive(){
  document.querySelectorAll('.wb-settings-nav [data-panel]').forEach(n=>{
    const active=n.dataset.panel===state.panel;n.classList.toggle('active',active);
    n.setAttribute('aria-pressed',String(active));
    if(active)n.setAttribute('aria-current','true');else n.removeAttribute('aria-current');
  });
}
function filter(name,value){
  const route=state.route;state.filters[route]??={};
  if(value!==undefined && state.filters[route][name]!==value){
    // Native controls have already changed their DOM value: that DOM no longer
    // represents the old filter key and must not be restored under it later.
    rememberPage();pageCache.delete(state.pageKey);
    state.filters[route][name]=value;
  }
  return state.filters[route][name];
}
function selectFilter(name,options,defaultValue,fn=render){const input=el('select',{'data-filter':name,'aria-label':({kind:'文件来源',media_type:'文件类型',status:'任务状态',model:'模型筛选',days:'时间范围',trigger:'触发方式'})[name]||name},options.map(o=>el('option',{value:o.value??o},o.label??o)));input.value=filter(name)??defaultValue;input.onchange=()=>{filter(name,input.value);fn();};return input;}
function searchFilter(placeholder,fn=render){const active=state.route;const input=el('input',{type:'search',placeholder,'aria-label':placeholder});input.value=filter('q')||'';let timer;input.oninput=()=>{clearTimeout(timer);filter('q',input.value);timer=setTimeout(()=>{if(state.route!==active||!input.isConnected)return;fn();},300);};return input;}
function showError(node,err){node.querySelector(':scope > .wb-error')?.remove();if(err.name==='AbortError')return;node.append(message(err.message));}
function dirtyForm(form){form.dataset.dirtyTracked="1";form.addEventListener('input',()=>state.dirty=true);form.addEventListener('change',()=>state.dirty=true);}
async function submit(form,fn){
  if(form.dataset.busy)return;
  const values=formData(form),controls=[...form.querySelectorAll('button,input,textarea,select')].map(node=>[node,node.disabled]);
  form.dataset.busy='1';form.setAttribute('aria-busy','true');state.submitting=true;form.querySelector('.wb-error')?.remove();
  controls.forEach(([node])=>node.disabled=true);
  try{await fn(values);state.dirty=false;}catch(e){showError(form,e);}
  finally{state.submitting=false;delete form.dataset.busy;form.removeAttribute('aria-busy');controls.forEach(([node,disabled])=>node.disabled=disabled);}
}
function closeDialog(){if(state.submitting&&state.dirty)return;if(state.dirty&&!confirm('尚有未保存的修改，确定放弃？'))return;state.dirty=false;$('wb-dialog').close();$('wb-dialog-body').replaceChildren();state.dialogReturn?.focus();}
function dialog(title,content){state.dialogReturn=document.activeElement;$('wb-dialog-title').textContent=title;$('wb-dialog-body').replaceChildren(content);$('wb-dialog').showModal();requestAnimationFrame(()=>content.querySelector('input,select,textarea,button')?.focus());}
$('wb-dialog-close').onclick=closeDialog;$('wb-dialog').addEventListener('cancel',e=>{e.preventDefault();closeDialog();});
async function confirmAction(title,explanation,fn,phrase,after){const form=el('form',{},el('p',{class:'wb-note'},explanation));if(phrase)form.append(field(`输入「${phrase}」以确认`,'phrase'));form.append(actions(button('取消',closeDialog),el('button',{class:'wb-btn danger',type:'submit'},'确认操作')));form.onsubmit=e=>{e.preventDefault();submit(form,async data=>{if(phrase&&data.phrase!==phrase)throw new Error('确认文字不匹配');await fn();state.dirty=false;closeDialog();if(after)await after();else await render();});};dialog(title,form);}
function detail(title,content){if(!$('wb-detail').hidden&&!closeDetail())return false;state.detailReturn=document.activeElement;state.detailRequest?.abort();state.detailRequest=new AbortController();state.detailDirty=false;state.detailDocument=null;$('wb-detail-title').textContent=title;$('wb-detail-body').replaceChildren(content);$('wb-detail').hidden=false;$('wb-detail').setAttribute('role',innerWidth<1200?'dialog':'complementary');$('wb-detail').setAttribute('aria-modal',String(innerWidth<1200));if(innerWidth<1200)$('wb-shell').inert=true;document.body.classList.add('wb-detail-open');$('wb-detail-close').focus();return true;}
function closeDetail(force=false){if(!force&&state.detailSaving)return false;if(!force&&state.detailDirty&&!confirm('文档有未保存修改，确定放弃？'))return false;state.detailDirty=false;state.detailDocument=null;state.detailRequest?.abort();$('wb-detail').hidden=true;$('wb-shell').inert=false;document.body.classList.remove('wb-detail-open');state.detailReturn?.focus();return true;}
$('wb-detail-close').onclick=()=>closeDetail();
function errorOr(node,fn){return async()=>{try{await fn();}catch(e){showError(node,e);}};}
async function outputViewer(path,title='完整输出',onBack,source){let current=0,previous=[];const area=el('div');detail(title,area);const signal=state.detailRequest.signal;async function load(offset,back){area.replaceChildren(message('正在读取完整输出…','loading'));try{const page=await api('/api/output/page',{data:{path,offset},signal});current=offset;previous=back;area.replaceChildren(el('p',{class:'wb-note'},`${page.filename} · ${bytes(page.offset)} — ${bytes(page.next_offset)} / ${bytes(page.size)}`),actions(button('上一页',()=>load(previous.at(-1),previous.slice(0,-1))),button('下一页',()=>load(page.next_offset,[...previous,current])),button('复制本页',()=>copyText(page.text).catch(e=>showError(area,e)))),el('pre',{class:'wb-pre wb-output-text'},page.text));area.querySelectorAll('button')[0].disabled=!previous.length;area.querySelectorAll('button')[1].disabled=page.eof;area.append(el('div',{class:'wb-file-path'},el('code',{},page.path||path),button('复制完整路径',()=>copyText(page.path||path).catch(e=>showError(area,e)))));if(source)area.prepend(sourceLink(source));area.prepend(button('收起完整输出',()=>closeDetail()));if(onBack)area.prepend(button('返回任务详情',onBack));}catch(e){area.replaceChildren(message(e.message),button('重试读取',()=>load(offset,back)),onBack?button('返回任务详情',onBack):null);}}await load(0,[]);}
async function refreshBootstrap(){const epoch=state.authEpoch,previous=state.boot?.asset_version;const boot=await wb('bootstrap');if(epoch!==state.authEpoch)throw new DOMException('登录状态已改变','AbortError');if(previous&&boot.asset_version&&previous!==boot.asset_version){const key='xgent-assets-reloaded:'+boot.asset_version;if(sessionStorage.getItem(key)!=='1'){sessionStorage.setItem(key,'1');location.reload();throw new DOMException('前端已更新','AbortError');}}state.boot=boot;state.bootUpdatedAt=Date.now();window.XGentAppearance?.accept(boot.settings);window.XGentChat?.commands(state.boot.commands||[]);chatControls();return state.boot;}
function chatControls(){if(!state.boot)return;window.XGentConversations?.accept(state.boot.conversations);updateComposerControls(state.boot.settings,changeQuick);}
async function changeQuick(key,value){await wb('settings',{data:{key,value}});await refreshBootstrap();}
function logout(){return window.XGentChat?.logout();}
$('btn-search').addEventListener('click',e=>{e.stopImmediatePropagation();openGlobalSearch();},true);
document.addEventListener('keydown',e=>{if(!e.isComposing&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='f'){e.preventDefault();e.stopImmediatePropagation();if(!$('wb-dialog').open)openGlobalSearch();}},true);
window.addEventListener('xgent-search-open',event=>{
  event.preventDefault();
  const item=event.detail;state.sourceReturn=state.route;sourceVisit='';
  if(item.archived){revealArchive(item.conversation_id,item.message_key);return;}
  const hash='#/chat'+query({conversation:item.conversation_id,message:item.message_key});
  if(location.hash===hash)followSource();else location.hash=hash;
});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('wb-dialog').open&&!document.getElementById('global-search-dialog')?.open)closeDetail();});
// Protect form drafts only; ordinary chat drafts survive route changes automatically.
window.addEventListener('beforeunload',e=>{if(state.dirty||state.detailDirty){e.preventDefault();e.returnValue='';}});
let sourceVisit='',sourceNavigationSequence=0;
function clearSourceReader(keepBanner=false){
  if(!keepBanner)$('source-navigation').hidden=true;
}
async function followSource(){
  const params=new URLSearchParams(location.hash.split('?')[1]||''),cid=params.get('conversation'),anchor=params.get('message');
  if(!cid || !anchor){clearSourceReader();sourceVisit='';window.XGentConversations?.followLocation();return;}
  const signature=cid+'|'+(anchor||'');if(sourceVisit===signature)return;sourceVisit=signature;
  const sequence=++sourceNavigationSequence,stillHere=()=>sequence===sourceNavigationSequence&&state.route==='chat'&&sourceVisit===signature;
  const banner=$('source-navigation');
  const close=el('button',{type:'button',class:'wb-source-close','aria-label':'关闭来源定位提示',title:'关闭',onclick:()=>{
    sourceVisit='';sourceNavigationSequence++;history.replaceState(null,'',window.XGentConversations?.href(window.XGentConversations.current)||'#/chat');
    clearSourceReader();window.XGentChat?.dismissLocation();
  }},sharedIcon('close'));
  const showBanner=(...children)=>{banner.hidden=false;banner.replaceChildren(close,el('div',{class:'wb-source-content'},...children));};
  showBanner(el('span',{class:'wb-source-label'},'正在定位来源消息…'));
  try{
    await window.XGentConversations.refresh();if(!stillHere())return;
    const owner=window.XGentConversations.items.find(c=>c.id===cid);if(!owner){await window.XGentConversations.new();return;}
    const back=el('a',{class:'wb-source-return',href:'#/'+(state.sourceReturn||'tasks')},'返回'+(pages.find(p=>p[0]===state.sourceReturn)?.[1]||'设置'));
    clearSourceReader(true);state.navigatingSource=true;
    try{await window.XGentConversations.select(cid);}finally{state.navigatingSource=false;}
    if(!stillHere())return;await window.XGentChat.locate(anchor||null);if(!stillHere())return;
    showBanner(back,el('span',{class:'wb-source-label'},owner.name+(owner.archived?' · 归档对话':'')+(anchor?' · 已定位来源消息':' · 此记录没有对应消息位置')));
  }catch(error){if(stillHere())showBanner(el('span',{class:'wb-source-label wb-source-error'},error.message),el('a',{class:'wb-source-return',href:'#/'+(state.sourceReturn||'tasks')},'返回设置'));}
}
document.addEventListener('click',event=>{const link=event.target.closest('.wb-source-link');if(link&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&event.button===0){state.sourceReturn=state.route;sourceVisit='';if(link.dataset.archiveConversation){event.preventDefault();revealArchive(link.dataset.archiveConversation,link.dataset.archiveMessage);}}});
window.addEventListener('xgent-new-conversation',()=>{sourceNavigationSequence++;sourceVisit='';clearSourceReader();});

function currentAppUrl(){return state.route==='chat'?(window.XGentConversations?.href(window.XGentConversations.current)||'#/chat'):'#/settings';}
function panelRoute(panel){return SETTINGS_SECTIONS.some(([id])=>id===panel)?'settings':panel;}
async function activatePanel(panel,chat=false){
  const next=chat?'chat':panelRoute(panel),app=chat?'chat':'settings';
  if(state.routed&&next===state.route&&(chat||panel===state.panel)&&document.body.dataset.page===app){
    if(state.authenticated&&!chat&&!pageCache.get(pageKey()))await render({reuse:true});
    if(state.authenticated&&chat)await followSource();return true;
  }
  if(state.detailSaving||state.submitting)return false;
  if(state.dirty||state.detailDirty){
    if(!confirm('尚有未保存修改，放弃并切换内容？'))return false;
    pageCache.delete(state.pageKey);
  }
  rememberPage();state.request?.abort();state.renderSequence++;state.pendingKey=null;
  state.dirty=false;state.detailDirty=false;
  if(state.route==='settings'&&(chat||panel!=='appearance')){window.XGentAppearance?.cancelPreview();window.XGentBranding?.cancelPreview();}
  if(!chat){
    sourceNavigationSequence++;sourceVisit='';clearSourceReader();
    state.panel=panel;try{sessionStorage.setItem('xgent-settings-panel',panel);}catch{}
    if(next==='settings')state.filters.settings={...(state.filters.settings||{}),section:panel};
  }
  state.route=next;state.retryAfter=0;state.routed=true;document.body.dataset.page=app;
  $('wb-page-title').textContent='设置';$('wb-page-title').hidden=chat;
  $('wb-page').hidden=chat;root.hidden=chat;closeDetail(true);markRouteActive();
  window.XGentWorkspaceMenu?.close();
  if(state.authenticated&&!chat)await render({reuse:true});
  else root.replaceChildren();
  if(chat&&state.authenticated)await followSource();return state.route===next&&(chat||state.panel===panel)&&document.body.dataset.page===app;
}
async function selectSettingsPanel(panel,keyboard=false){
  if(!settingsPanels.some(([id])=>id===panel))return;
  if(!await activatePanel(panel))return;
  if(location.hash!=='#/settings')history.replaceState(null,'','#/settings');
  if(state.panel===panel&&!matchMedia('(prefers-reduced-motion:reduce)').matches&&!document.body.classList.contains('wb-reduce-motion')){
    root.getAnimations().forEach(animation=>animation.cancel());root.animate([{opacity:.65,transform:'translateY(3px)'},{opacity:1,transform:'translateY(0)'}],{duration:130,easing:'cubic-bezier(.2,.7,.2,1)'});
  }
  if(keyboard&&state.panel===panel)document.querySelector('.wb-settings-nav [data-panel="'+panel+'"]').focus({preventScroll:true});
}
async function route(){
  const requestedHash=location.hash;
  const requested=routeName();
  if(requested==='chat'||!pages.some(([id])=>id===requested)){
    const params=new URLSearchParams(location.hash.split('?')[1]||''),id=params.get('conversation')||window.XGentConversations?.current;
    const owner=window.XGentConversations?.items.find(item=>item.id===id);
    if(state.authenticated&&owner?.archived&&!window.XGentConversations?.enteredArchive(id)){await revealArchive(id,params.get('message'));return;}
    if(!await activatePanel(state.panel,true))history.replaceState(null,'',currentAppUrl());return;
  }
  const selected=new URLSearchParams(location.hash.split('?')[1]||'').get('section');
  const panel=requested==='settings'?(settingsPanels.some(([id])=>id===selected)?selected:state.panel):requested;
  if(!await activatePanel(panel)){if(location.hash===requestedHash)history.replaceState(null,'',currentAppUrl());return;}
  if(location.hash!==requestedHash||document.body.dataset.page!=='settings'||state.panel!==panel)return;
  if(location.hash!=='#/settings')history.replaceState(null,'','#/settings');
}
window.addEventListener('hashchange',route);
$('settings-navigation').append(settingsNavigation({onSelect:selectSettingsPanel,onSearch:openGlobalSearch,onLogout:logout}));
markRouteActive();

async function render(options={}){
  if(state.route==='chat'||!state.authenticated)return;
  const background=options.background===true;
  const passive=background||options.reuse===true;
  const active=state.route,key=pageKey();
  if(background && (document.hidden||pageInteracting()||state.pendingKey===key))return;
  const previousKey=state.pageKey;
  rememberPage();
  let entry=pageCache.get(key);
  if(entry && (options.reuse===true||previousKey!==key)){
    root.replaceChildren(entry.content);root.scrollTop=entry.scroll;state.pageKey=key;document.body.dataset.loadedPage=active;
    markRouteActive(active);
    if(pageCache.fresh(entry))return;
    if(pageInteracting()){cacheNotice('已有新数据，完成当前操作后更新');return;}
  }
  if(background&&entry&&pageCache.fresh(entry))return;
  if(options.reuse===true&&state.pendingKey===key&&!state.request?.signal.aborted)return;
  const search=root.querySelector('input[type=search]');
  const searchFocused=search===document.activeElement;
  const searchCursor=searchFocused?search.selectionStart:null;
  const previousScroll=entry?.content.parentNode===root?root.scrollTop:(entry?.scroll||0);
  state.request?.abort();
  const controller=new AbortController();state.request=controller;
  const sequence=++state.renderSequence;
  state.pendingKey=key;state.pageKey=key;
  const revision=pageCache.revision(active),interaction=entry?.interaction||0;
  // Initial visits may load; updates leave the usable page in place until data is ready.
  if(!entry && (!root.firstElementChild||document.body.dataset.loadedPage!==active)){
    // 壳先上屏：左导航常驻，右侧显示加载占位，避免首次加载时导航整列消失。
    root.replaceChildren(message('正在读取'+(panelNames[state.panel]||'设置')+'…','loading'));
    root.scrollTop=0;}
  else if(!passive)cacheNotice('正在更新，当前内容仍可查看');
  const assertCurrent=()=>{
    if(controller.signal.aborted||sequence!==state.renderSequence||state.route!==active||pageKey()!==key||!state.authenticated)
      throw new DOMException('Page navigation superseded request','AbortError');
  };
  const dataVersions=[];
  const signature=(name,value)=>{
    // Relative time boundaries aren't content changes. Rows, status, settings and
    // revisions still take part in the signature, including external changes.
    const stable=name.startsWith('usage?')?{...value,start:null,end:null}:value;
    dataVersions.push(JSON.stringify([name.split('?')[0],stable]));
  };
  const read=async name=>{assertCurrent();const value=await wb(name,{signal:controller.signal});assertCurrent();signature(name,value);return value;};
  read.cached=(name,value)=>{assertCurrent();signature(name,value);return value;};
  read.api=async path=>{assertCurrent();const value=await api(path,{signal:controller.signal});assertCurrent();signature(path,value);return value;};
  try{
    let content=await ({tasks:taskPage,files:filePage,models:modelPage,usage:usagePage,settings:settingsPage,archive:archivePage}[active])(read);
    if(entry&&content.deferredPanelsReady)await content.deferredPanelsReady;
    assertCurrent();
    if(revision!==pageCache.revision(active)){
      // 并发失效不能把刚取到的数据丢掉：屏幕上还没有可用内容（首访仍停在
      // 加载提示）时立即上屏，再安排一次静默刷新；已有可用内容才走提示条。
      // 否则一次回合结束/切换会话就能让首访死挂在「正在读取设置内容…」上。
      if(entry&&entry.content.parentNode===root){cacheNotice('已有新数据，完成当前操作后更新');return;}
      setTimeout(()=>{if(state.route===active&&state.authenticated&&!document.hidden)render({background:true});},0);
    }
    const dataVersion=JSON.stringify(dataVersions.sort());
    if(entry && entry.dataVersion===dataVersion&&!content.dataset.deferredPanels){
      entry.updatedAt=Date.now();entry.revision=revision;state.retryAfter=0;cacheNotice('');
      if(entry.content.parentNode!==root){root.replaceChildren(entry.content);root.scrollTop=entry.scroll||0;}
      return;
    }
    if(entry && (state.dirty||entry.interaction!==interaction||passive&&pageInteracting())){
      if(!state.dirty&&entry.content.parentNode!==root){root.replaceChildren(entry.content);root.scrollTop=entry.scroll||0;}
      cacheNotice('已有新数据，完成当前操作后更新');return;
    }
    // Scroll may have moved while a slow request was pending; honor the latest position.
    const scroll=entry?.content.parentNode===root?root.scrollTop:previousScroll;
    entry=pageCache.set(key,active,content,revision,scroll);
    entry.dataVersion=dataVersion;
    root.replaceChildren(content);root.scrollTop=scroll;state.retryAfter=0;document.body.dataset.loadedPage=active;
    markRouteActive(active);
    if(searchFocused){const input=root.querySelector('input[type=search]');if(input){input.focus({preventScroll:true});if(searchCursor!==null)input.setSelectionRange(searchCursor,searchCursor);}}
  }catch(e){
    if(e.name==='AbortError'||sequence!==state.renderSequence||!state.authenticated||state.route!==active)return;
    state.retryAfter=Date.now()+15000;
    if(entry){cacheNotice('更新失败，当前显示上次加载的内容：'+e.message,true);}
    else root.replaceChildren(heading(pages.find(p=>p[0]===active)?.[1]||'','无法读取设置内容'),message(e.message),button('重新加载',()=>render()));
  }finally{
    if(sequence===state.renderSequence){
      state.pendingKey=null;
      const notice=root.querySelector(':scope > .wb-cache-notice');
      if(notice?.textContent==='正在更新，当前内容仍可查看')notice.remove();
    }
  }
}
function backgroundRefresh(){
  if(!state.authenticated||state.route==='chat'||document.hidden||Date.now()<state.retryAfter||pageInteracting())return;
  // boot 超期时先走 refreshBootstrap：它带资产版本检查，服务端更新后
  // 开着的页面会自动 reload 一次，不需要用户手动硬刷新。
  if(state.boot&&Date.now()-state.bootUpdatedAt>60000){refreshBootstrap().then(()=>render({background:true})).catch(()=>{});return;}
  render({background:true});
}

function sourceLink(source){
  if(!source?.conversation_id)return el('span',{class:'wb-source-unknown'},'来源未关联');
  const params=new URLSearchParams({conversation:source.conversation_id});
  if(source.message_key)params.set('message',source.message_key);
  if(source.archived)params.set('archived','1');
  const link=el('a',{href:'#/chat?'+params,class:'wb-source-link',title:source.message_key?'打开来源对话并定位到消息':source.note||'打开来源对话'},source.conversation_name||'新对话',source.archived?el('small',{},'已归档'):null);
  if(source.archived){link.href='#/settings?section=archive';link.dataset.archiveConversation=source.conversation_id;link.dataset.archiveMessage=source.message_key||'';link.title='在设置的归档列表中查看来源对话';}
  return el('div',{class:'wb-source-cell'},link,!source.message_key?el('small',{},source.note||'无对应消息位置'):null);
}
function filePagination(data){
  const page=data.offset||0,previous=button('上一页',()=>{filter('offset',Math.max(0,page-50));render();}),next=button('下一页',()=>{filter('offset',data.next_offset);render();});previous.disabled=!page;next.disabled=data.next_offset==null;
  return el('div',{class:'wb-pagination'},el('span',{class:'wb-note'},data.total?'共 '+fmt(data.total)+' 项 · '+(page+1)+'–'+(page+data.items.length):'共 0 项'),actions(previous,next));
}

async function taskPage(read){return (await featureView('tasks')).taskPage(read);}
async function filePage(read){return (await featureView('files')).filePage(read);}
async function fileDetail(file){return (await featureView('files')).fileDetail(file);}
async function attachmentVersions(file){return (await featureView('files')).attachmentVersions(file);}
async function modelPage(read){return (await featureView('models')).modelPage(read);}
// Local skill filters don't fetch the same small catalogue or throw away focused controls.
function localFilters(values){
  const entry=pageCache.get(state.pageKey);pageCache.delete(state.pageKey);
  Object.assign(state.filters[state.route]??={},values);state.pageKey=pageKey();
  if(entry){pageCache.set(state.pageKey,entry.route,entry.content,entry.revision,root.scrollTop);Object.assign(pageCache.get(state.pageKey),entry);}
}
async function managementModule(name){
  try{return await import('./'+name+'.js?v='+encodeURIComponent(state.boot?.asset_version||'current'));}
  catch{throw new Error('设置组件暂时无法加载，请刷新后重试。');}
}
const featureViews=new Map();
async function featureView(name){
  if(!featureViews.has(name)){
    const pending=managementModule('workbench-'+name).then(module=>module.createViews({state,pageCache,filter,render,selectFilter,searchFilter,sourceLink,filePagination,outputViewer,showError,detail,closeDetail,confirmAction,dialog,closeDialog,submit,dirtyForm,errorOr,refreshBootstrap,chatControls,localFilters,managementModule,taskSourceSearch}));
    featureViews.set(name,pending);pending.catch(()=>featureViews.delete(name));
  }
  return featureViews.get(name);
}
async function archivePage(read){const {archiveView}=await managementModule('settings-archive');return archiveView(read,{render,state,localFilters});}
async function revealArchive(id,message){
  state.archiveReveal={id,message:message||null,at:Date.now()};
  await selectSettingsPanel('archive');
  window.dispatchEvent(new CustomEvent('xgent-archive-reveal',{detail:state.archiveReveal}));
}
async function usagePage(read){const {usageView}=await managementModule('usage');return usageView(read,{filter,render,heading,card,actions,priceSettings,state});}
function priceSettings(){
  const form=el('form',{class:'wb-price-form'}),priceRows=el('div',{class:'wb-price-rows'}),mergeRows=el('div',{class:'wb-merge-rows'});
  function priceRow(name='',value={}){const row=el('div',{class:'wb-price-row'},field('模型名称','model',name),...['input','output','cached'].map((key,i)=>{const node=field(['输入单价','输出单价','缓存单价'][i],key,value[key]??0,'number');node.querySelector('input').min='0';node.querySelector('input').step='any';return node;}));row.append(button('移除',()=>{row.remove();form.dispatchEvent(new Event('input',{bubbles:true}));},'danger'));priceRows.append(row);}
  function mergeRow(name='',aliases=[]){const row=el('div',{class:'wb-merge-row'},field('合并后的模型名','model',name),field('原始名称（每行一个）','aliases',aliases.join('\n'),'textarea'));row.append(button('移除',()=>{row.remove();form.dispatchEvent(new Event('input',{bubbles:true}));},'danger'));mergeRows.append(row);}
  for(const [name,price] of Object.entries(state.boot?.settings.values.model_price_table||{}))priceRow(name,price);
  for(const [name,names] of Object.entries(state.boot?.settings.values.model_merge_map||{}))mergeRow(name,names);
  form.append(el('h3',{},'模型价格'),el('p',{class:'wb-note'},'单位：USD / 百万 Token。default 用作默认价格。'),priceRows,button('添加模型价格',()=>priceRow()),el('h3',{class:'wb-section-title'},'模型名称合并'),mergeRows,button('添加合并规则',()=>mergeRow()),el('div',{class:'wb-form-save'},el('button',{type:'submit',class:'wb-btn primary'},'保存规则')));dirtyForm(form);
  form.onsubmit=e=>{e.preventDefault();submit(form,async()=>{const prices={},merge={};for(const row of priceRows.children){const name=row.querySelector('[name=model]').value.trim();if(!name)throw new Error('请填写模型名称');if(prices[name])throw new Error('模型价格名称重复：'+name);prices[name]=Object.fromEntries(['input','output','cached'].map(key=>{const n=Number(row.querySelector('[name='+key+']').value);if(!Number.isFinite(n)||n<0)throw new Error('单价必须是非负数');return [key,n];}));}for(const row of mergeRows.children){const name=row.querySelector('[name=model]').value.trim();if(!name||merge[name])throw new Error('合并名称为空或重复');merge[name]=row.querySelector('[name=aliases]').value.split('\n').map(s=>s.trim()).filter(Boolean);}await wb('settings',{data:{items:[{key:'model_price_table',value:prices},{key:'model_merge_map',value:merge}]}}).then(saved=>{if(state.boot&&saved?.values)state.boot={...state.boot,settings:saved};});state.dirty=false;closeDialog();render();});};dialog('价格与合并规则',form);
}

$('workspace-settings')?.addEventListener('click',()=>{
  window.XGentWorkspaceMenu?.close();if(location.hash!=='#/settings')location.hash='#/settings';else route();
  // 移动端抽屉里点「设置」：委托 conversations.js 自己的关闭按钮收起抽屉，别挡住设置页。
  if(document.body.classList.contains('conv-drawer-open'))$('conversation-drawer-close')?.click();
});
async function settingsPage(read){
  const qs=new URLSearchParams(location.hash.split('?')[1]||'').get('section');
  if(qs&&SETTINGS_SECTIONS.some(([id])=>id===qs)){
    if(filter('section')!==qs)filter('section',qs);
  }
  // 快照复用：boot 未失效（60s 内）直接同步渲染，切换子分区 0 次网络请求；
  // 一旦失效（写入/外部变更/登出）立即重拉，绝不渲染过期配置。
  const cached=state.boot&&Date.now()-state.bootUpdatedAt<60000;
  const [{settingsView},boot]=await Promise.all([managementModule('settings'),cached?Promise.resolve(read.cached('bootstrap',state.boot)):read('bootstrap')]);
  state.boot=boot;if(!cached)state.bootUpdatedAt=Date.now();
  return settingsView({logout,boot,health:{},state,render,dialog,closeDialog,submit,dirtyForm,confirmAction,refreshBootstrap,setTheme,filter,heading,card,actions,read,localFilters,detail,closeDetail,toolbar,managementModule,sideNav:null});
}
function setTheme(value){pageCache.invalidate(['settings']);setThemeMode(value);}
document.body.classList.toggle('wb-reduce-motion',readPreference('xgent-reduce-motion')==='1');
// Desktop inspector width. No modal blocking background reading on wide screens.
const resize=$('wb-resizer');let resizing=false;resize.onpointerdown=e=>{resizing=true;resize.setPointerCapture(e.pointerId);};resize.onpointermove=e=>{if(!resizing)return;const width=Math.max(320,Math.min(700,window.innerWidth-e.clientX));document.documentElement.style.setProperty('--detail-width',width+'px');};resize.onpointerup=()=>{resizing=false;writePreference('xgent-detail-width',getComputedStyle(document.documentElement).getPropertyValue('--detail-width'));};resize.onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const width=parseInt(getComputedStyle(document.documentElement).getPropertyValue('--detail-width'))+(e.key==='ArrowLeft'?20:-20);document.documentElement.style.setProperty('--detail-width',Math.max(320,Math.min(700,width))+'px');}};const width=readPreference('xgent-detail-width');if(/^\d+px$/.test(width||''))document.documentElement.style.setProperty('--detail-width',width);
// Terminal is retained when hidden, so switching panels never sends a kill operation.
new MutationObserver(()=>document.body.classList.toggle('wb-terminal-open',$('terminal-modal').classList.contains('open'))).observe($('terminal-modal'),{attributes:true,attributeFilter:['class']});
// Composer measurement also handles software keyboards and multiline drafts.
new ResizeObserver(()=>document.documentElement.style.setProperty('--footer-height',($('composer').parentElement.offsetHeight||118)+'px')).observe($('composer').parentElement);
window.visualViewport?.addEventListener('resize',()=>{const keyboard=window.innerHeight-window.visualViewport.height>140;document.body.classList.toggle('wb-keyboard',keyboard);$('wb-shell').style.height=keyboard?window.visualViewport.height+'px':'';});
let started=false;async function start(){if(started)return;const epoch=state.authEpoch;started=true;try{await refreshBootstrap();if(epoch!==state.authEpoch)return;state.authenticated=true;await route();}catch(e){if(epoch!==state.authEpoch)return;started=false;if(e.status!==401&&e.name!=='AbortError')$('wb-history-state').textContent='设置读取失败：'+e.message;}}
window.addEventListener('xgent-authenticated',start);
window.addEventListener('xgent-auth-expired',()=>{
  state.authEpoch++;started=false;state.authenticated=false;state.request?.abort();state.renderSequence++;
  state.boot=null;state.bootUpdatedAt=0;state.pendingKey=null;state.pageKey=null;state.dirty=false;state.retryAfter=0;
  pageCache.clear();root.replaceChildren();closeDetail(true);
  if($('wb-dialog').open)$('wb-dialog').close();$('wb-dialog-body').replaceChildren();
  $('login').showModal();
});
api('/api/session').then(data=>{if(data.authenticated)start();}).catch(()=>{});route();
// Refresh only the visible stale page. Fast navigation reuses warm DOM without requests.
setInterval(backgroundRefresh,15000);

document.addEventListener('visibilitychange',()=>{if(document.hidden){state.request?.abort();state.pendingKey=null;}else backgroundRefresh();});
document.addEventListener('keydown',e=>{if(e.key!=='Tab'||$('wb-detail').hidden||innerWidth>=1200||$('wb-dialog').open)return;const nodes=[...$('wb-detail').querySelectorAll('button,a,input,select,textarea,[tabindex]')].filter(n=>!n.disabled&&n.offsetParent);if(!nodes.length)return;const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}});

new MutationObserver(()=>{$('terminal-iframe')?.contentWindow?.postMessage({type:'xgent-theme',dark:document.body.classList.contains('dark')},location.origin);}).observe(document.body,{attributes:true,attributeFilter:['class']});

// Basic chat actions have their own handlers; enhance them only after this
// entire optional workbench initialized successfully.
window.XGentWorkbench={
  revealArchive,
  showSettingsPanel:selectSettingsPanel,
  get panel(){return state.panel;},
  attachmentVersions,
  previewFile:fileDetail,
  dialog,closeDialog,
  prepareChat:async()=>{if(state.route!=='chat'||new URLSearchParams(location.hash.split('?')[1]||'').has('message')){location.hash=window.XGentConversations?.href(window.XGentConversations.current)||'/chat';await route();}return state.route==='chat';},
  commands:()=>state.boot?.commands,
  confirmCommand:cmd=>confirmAction('执行 '+cmd,'此命令可能改变共享数据或重启服务，是否继续？',async()=>window.XGentChat.command(cmd)),
  beforeLogout:()=>{if(state.submitting||state.detailSaving)return false;if((state.dirty||state.detailDirty)&&!confirm('尚有未保存修改，确定退出登录？'))return false;state.dirty=false;state.detailDirty=false;return true;}
};
window.dispatchEvent(new Event('xgent-workbench-ready'));

window.addEventListener('xgent-conversation-changed',()=>{
  if(state.navigatingSource){pageCache.invalidate(['tasks','files']);return;}
  if(['models','settings'].includes(state.route))return; // Shared document/configuration drafts are not chat-bound.
  state.request?.abort();state.detailRequest?.abort();state.renderSequence++;
  pageCache.clear();state.pageKey=null;state.pendingKey=null;state.retryAfter=0;
  closeDetail();if(state.route!=='chat'&&state.authenticated)render();
});
let archiveSignature='';
window.addEventListener('xgent-conversation-state',event=>{
  const signature=JSON.stringify((event.detail.items||[]).filter(item=>item.archived).map(item=>[item.id,item.name,item.group_id,item.pinned]));
  if(signature===archiveSignature)return;archiveSignature=signature;pageCache.invalidate(['archive']);
  if(state.route==='archive'&&state.authenticated)backgroundRefresh();
});

window.addEventListener('xgent-fonts-applied',()=>{
  if(state.dirty||state.submitting)return;
  const values=window.XGentAppearance?.state.values||{};
  for(const input of document.querySelectorAll('.font-settings input[name]'))if(input.name in values)input.value=values[input.name];
  for(const slider of document.querySelectorAll('.font-settings [data-font-key]'))if(slider.dataset.fontKey in values)slider.value=values[slider.dataset.fontKey];
});

function taskSourceSearch(){
  const input=el('input',{type:'search',placeholder:'搜索对话名称或历史内容…','aria-label':'搜索来源对话'}),results=el('div',{class:'wb-source-results'});
  const box=el('div',{class:'wb-source-dialog'},el('label',{class:'wb-field'},el('span',{},'对话名称或历史内容'),input),el('p',{class:'wb-note'},'选择结果只筛选来源，不切换当前聊天。'),results);
  let controller,timer,sequence=0;
  async function search(){
    controller?.abort();controller=new AbortController();const current=++sequence;results.replaceChildren(message('正在搜索…','loading'));
    try{
      const data=await wb('conversations/search'+query({q:input.value}),{signal:controller.signal});
      if(current!==sequence||!box.isConnected)return;
      results.replaceChildren();
      for(const item of data.items){const choose=button('',()=>{filter('source',item.id);filter('offset',0);state.dirty=false;closeDialog();render();});choose.classList.add('wb-source-result');choose.append(el('strong',{},item.name||'新对话'),el('span',{class:'wb-note'},item.id.slice(0,6)+(item.archived?' · 已归档':'')));if(item.snippet)choose.append(el('p',{},item.snippet));results.append(choose);}
      if(!data.items.length)results.append(empty('没有找到对话','试试会话名称或消息中的关键词。'));
    }catch(error){if(error.name!=='AbortError'&&current===sequence)results.replaceChildren(message(error.message),button('重新搜索',search));}
  }
  input.oninput=()=>{clearTimeout(timer);controller?.abort();sequence++;results.replaceChildren(message('正在搜索…','loading'));timer=setTimeout(search,250);};
  dialog('搜索来源对话',box);search();
  $('wb-dialog').addEventListener('close',()=>{clearTimeout(timer);controller?.abort();},{once:true});
}
