import {el,button,fmt,stamp,empty,message} from './components.js';
import {heading,toolbar,actions,icon,readPreference,writePreference} from './ui.js';

window.addEventListener('xgent-archive-reveal',event=>document.querySelector('#settings-content .settings-archive-panel')?._reveal?.(event.detail));
const name=item=>item.display_title||item.name||'新对话';
const activity=item=>Number(item.activity_at??item.last_active??item.created_at)||0;
function origin(item){
  const value=item.archive_origin;
  try{return typeof value==='string'?JSON.parse(value):value||{};}catch{return {};}
}

export async function archiveView(read,{render,state,localFilters}){
  await window.XGentConversations.refresh();
  const data=await read('conversations'),all=new Map((data.items||[]).map(item=>[item.id,item]));
  const archived=(data.items||[]).filter(item=>item.archived===true||Number(item.archived)===1);
  const index=new Map(archived.map(item=>[item.id,item])),children=new Map();
  for(const item of archived){
    if(item.owner_conversation_id&&index.has(item.owner_conversation_id)){
      const list=children.get(item.owner_conversation_id)||[];list.push(item);children.set(item.owner_conversation_id,list);
    }
  }
  for(const list of children.values())list.sort((a,b)=>activity(b)-activity(a)||a.id.localeCompare(b.id));
  const expanded=new Set();
  try{for(const id of JSON.parse(readPreference('xgent-archive-expanded','[]')))expanded.add(id);}catch{}
  const search=el('input',{type:'search',placeholder:'搜索归档对话','aria-label':'搜索归档对话'});
  search.value=state.filters.archive?.q||'';
  const summary=el('span',{class:'wb-note',role:'status'}),list=el('div',{class:'archive-list','aria-label':'归档对话列表'});
  const page=el('div',{class:'settings-archive-panel'},heading('归档对话','归档是隐藏的系统分组。对话可以继续使用；恢复后返回原分组，父对话与子对话一起恢复。',[button('刷新',render)]),toolbar(search,summary));
  const rows=new Map(),branches=new Map(),toggles=new Map(),visited=new Set();
  const saveExpansion=()=>writePreference('xgent-archive-expanded',JSON.stringify([...expanded]));
  const ancestors=id=>{const result=[],seen=new Set([id]);let owner=index.get(id)?.owner_conversation_id;while(owner&&index.has(owner)&&!seen.has(owner)){result.push(owner);seen.add(owner);owner=index.get(owner)?.owner_conversation_id;}return result;};
  function syncExpansion(id){const open=expanded.has(id);const branch=branches.get(id),toggle=toggles.get(id);if(branch)branch.hidden=!open;if(toggle){toggle.setAttribute('aria-expanded',String(open));toggle.title=(open?'收起':'展开')+name(index.get(id))+'的子对话';}}
  function tree(item,depth=0){
    if(visited.has(item.id))return null;visited.add(item.id);
    const descendants=children.get(item.id)||[],restoreInfo=origin(item);
    const toggle=el('button',{type:'button',class:'archive-tree-toggle','aria-label':(descendants.length?'展开或收起子对话：':'没有子对话：')+name(item),
      'aria-controls':'archive-children-'+item.id,disabled:!descendants.length,onclick:()=>{if(expanded.has(item.id))expanded.delete(item.id);else expanded.add(item.id);syncExpansion(item.id);saveExpansion();}},icon('chevron'));
    if(!descendants.length)toggle.classList.add('is-leaf');
    const information=el('div',{class:'archive-row-info'},el('div',{class:'archive-row-title'},
      item.owner_conversation_id?icon('M3 17h5l8-10h5M17 3l4 4-4 4M3 7h5M17 14v7h-7'):icon('archive'),el('strong',{},name(item))),
      el('div',{class:'archive-row-meta'},el('span',{},'原分组：'+(restoreInfo.group_name||'默认分组')),
        restoreInfo.pinned?el('span',{},'原分组置顶'):null,
        data.runs?.[item.id]?el('span',{class:'archive-run-state',role:'status'},'正在生成'):null,
        item.owner_conversation_id&&!index.has(item.owner_conversation_id)?el('span',{},'父对话：'+name(all.get(item.owner_conversation_id)||{})):null,
        el('time',{datetime:new Date(activity(item)*1000).toISOString()},stamp(activity(item)))));
    const enter=button('进入对话',async()=>{
      enter.disabled=true;
      try{await window.XGentConversations.enter(item.id,state.archiveReveal?.id===item.id?state.archiveReveal.message:null);}
      catch(error){page.append(message(error.message));}
      finally{enter.disabled=false;}
    },'primary');
    const restore=button('恢复',async()=>{restore.disabled=true;try{await window.XGentConversations.restore(item.id);}finally{restore.disabled=false;}});
    restore.title=descendants.length?'恢复此对话及全部子对话，并进入对话':'恢复到原分组并进入对话';
    const more=el('button',{type:'button',class:'archive-more icon-btn','aria-label':'更多归档操作：'+name(item),'aria-haspopup':'menu','aria-expanded':'false',onclick:event=>window.XGentConversations.menu(item.id,event.currentTarget)},icon('M5 12h.01M12 12h.01M19 12h.01'));
    const row=el('div',{class:'archive-row'+(depth?' is-child':''),'data-conversation-id':item.id},toggle,information,actions(enter,restore,more));
    rows.set(item.id,row);toggles.set(item.id,toggle);
    const wrapper=el('div',{class:'archive-thread','data-archive-thread':item.id},row);
    if(descendants.length){const branch=el('div',{id:'archive-children-'+item.id,class:'archive-children'},descendants.map(child=>tree(child,depth+1)));branches.set(item.id,branch);wrapper.append(branch);syncExpansion(item.id);}
    return wrapper;
  }
  const roots=archived.filter(item=>!index.has(item.owner_conversation_id)).sort((a,b)=>activity(b)-activity(a)||a.id.localeCompare(b.id));
  for(const item of [...roots,...archived]){const root=tree(item);if(root)list.append(root);}
  const noMatch=empty('没有匹配的归档对话','试试其他关键词，或清除搜索。',button('清除搜索',()=>{search.value='';filter();}));
  function filter(save=true){
    if(save)localFilters({q:search.value});const q=search.value.trim().toLowerCase(),visible=new Set();let matches=0;
    for(const item of archived){
      if(q&&![name(item),origin(item).group_name,item.id].join(' ').toLowerCase().includes(q))continue;
      matches++;visible.add(item.id);for(const owner of ancestors(item.id)){visible.add(owner);if(q)expanded.add(owner);}
    }
    for(const [id,row] of rows){const wrapper=row.parentElement;wrapper.hidden=!!q&&!visible.has(id);if(q&&visible.has(id)&&children.has(id))expanded.add(id);syncExpansion(id);}
    summary.textContent=fmt(archived.length)+' 个归档对话'+(q?' · '+fmt(matches)+' 个匹配':' · '+fmt(roots.length)+' 个父对话');
    noMatch.hidden=!archived.length||!!matches;list.hidden=!archived.length||!matches;
  }
  search.oninput=()=>filter();filter(false);
  page.append(archived.length?list:empty('没有归档对话','在对话菜单中选择归档，它会移到这里并保留原分组信息。'),noMatch);
  function reveal(value){
    if(!value?.id||!page.isConnected||!rows.has(value.id))return;
    search.value='';filter();for(const id of ancestors(value.id)){expanded.add(id);syncExpansion(id);}saveExpansion();
    const row=rows.get(value.id);row.classList.add('is-target');row.scrollIntoView({block:'center'});
    row.querySelector('.wb-btn.primary')?.focus({preventScroll:true});
    setTimeout(()=>row.classList.remove('is-target'),2500);
  }
  page._reveal=reveal;
  if(state.archiveReveal)setTimeout(()=>reveal(state.archiveReveal),0);
  return page;
}
