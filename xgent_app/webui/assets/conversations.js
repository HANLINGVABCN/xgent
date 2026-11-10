/* Conversation navigation is independent of optional workbench pages. */
import {ConversationSearch} from './global-search.js';
import {preventAutofill,guardSearchAutofill} from './input-policy.js';
const $ = id => document.getElementById(id);
const sidebar = $('wb-nav');
const list = $('conversation-list');
const scroll = $('conversation-scroll');
const search = $('conversation-search');
const searchAutofill=guardSearchAutofill(search);
const globalResults = new ConversationSearch(list, {compact: true});
const menu = $('conversation-item-menu');
const renameDialog = $('conversation-rename-dialog');
const mobile = matchMedia('(max-width: 767px)');
const rows = new Map();
const knownRuns=new Map(),completedRuns=new Set(),completionTimers=new Set();
let itemIndex = new Map();
const paths = {
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  rename: 'm15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14z',
  archive: 'M4 8h16v12H4zM3 4h18v4H3zM10 12h4',
  restore: 'M4 8h16v12H4zM3 4h18v4H3zM12 17v-6m-3 3 3-3 3 3',
  close: 'm6 6 12 12M6 18 18 6',
  export: 'M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4',
  branch: 'M3 17h5l8-10h5M17 3l4 4-4 4M3 7h5M17 14v7h-7',
};
let state = {current_chat_id: null, telegram_conversation_id: null, revision: -1, items: [], running: null};
let authenticated = false, authEpoch = 0, request = null, mutation = null;
let listSignature = '', menuTarget = null, menuTrigger = null;
let groupView = 'ungrouped';
let moveSubmenu = null, moveTrigger = null, moveHideTimer = null;
const exporting = new Set();
const expansionKey = 'xgent-conversation-children';
const expandedChildren = new Set();
const enteredArchives=new Set();
try{for(const id of JSON.parse(sessionStorage.getItem('xgent-entered-archives')||'[]'))if(typeof id==='string')enteredArchives.add(id);}catch{}
try { for (const id of JSON.parse(localStorage.getItem(expansionKey) || '[]')) if (typeof id === 'string') expandedChildren.add(id); } catch {}
let drawerOpen = false, drawerReturn = null, previousInert = null;
let renameTarget = null, renameReturn = null, renameSaving = false;
let feedbackTimer = null;
const controllers = new Set();
const locationParams = () => new URLSearchParams(location.hash.split('?')[1] || '');
const chatLocation = () => !location.hash || (location.hash.replace(/^#\/?/, '').split('?')[0] || 'chat') === 'chat';
let localCurrent = locationParams().has('message') ? null : locationParams().get('conversation');
let listReady = false, draftToken = null;
let draftVisible = false, draftGroup = 'ungrouped', draftEntry = null;
const draftMenuTarget = '@new';
try{if(!chatLocation())localCurrent=sessionStorage.getItem('xgent-selected-conversation');draftToken=sessionStorage.getItem('xgent-new-conversation-token');}catch{}
function newToken(){
  if(!draftToken){draftToken=globalThis.crypto?.randomUUID?.()||('new'+Date.now().toString(36)+Math.random().toString(36).slice(2));try{sessionStorage.setItem('xgent-new-conversation-token',draftToken);}catch{}}
  return draftToken;
}
function conversationHref(id) { return id ? '#/chat?conversation=' + encodeURIComponent(id) : '#/chat'; }
function keepConversationUrl() {
  if (locationParams().has('message')) return;
  const route = location.hash.replace(/^#\/?/, '').split('?')[0] || 'chat';
  try{if(localCurrent)sessionStorage.setItem('xgent-selected-conversation',localCurrent);else sessionStorage.removeItem('xgent-selected-conversation');}catch{}
  if(route!=='chat')return;
  if(!localCurrent){if(location.hash!=='#/chat')history.replaceState(null,'','#/chat');return;}
  const params = locationParams(); params.set('conversation', localCurrent);
  const hash = '#/' + route + '?' + params.toString();
  if (location.hash !== hash) history.replaceState(null, '', hash);
}
function selectLocal(id, writeUrl = true, detail = {}) {
  id = id || null;
  const previous = state.current_chat_id;
  localCurrent = id;
  if(!id)newToken();
  try{if(id)sessionStorage.setItem('xgent-selected-conversation',id);else sessionStorage.removeItem('xgent-selected-conversation');}catch{}
  state = {...state, current_chat_id: id, running: runningFor(id)};
  if (writeUrl && location.hash !== conversationHref(id)) history[writeUrl==='replace'?'replaceState':'pushState'](null, '', conversationHref(id));
  if (!writeUrl) keepConversationUrl();
  revealAncestors(id); render();
  window.dispatchEvent(new CustomEvent('xgent-conversation-state', {detail: state}));
  if (previous !== id) window.dispatchEvent(new CustomEvent('xgent-conversation-changed', {
    detail: {previous, conversation_id: id, ...detail},
  }));
  if(!id)window.dispatchEvent(new Event('xgent-new-conversation'));
  return true;
}
function followConversationLocation() {
  if(!chatLocation())return;
  const id = locationParams().get('conversation');
  if(id&&listReady&&!itemById(id)){selectLocal(null,'replace');return;}
  if (locationParams().has('message')) return;
  if (id !== localCurrent && (!id || listReady)) selectLocal(id, false);
  else keepConversationUrl();
}
window.addEventListener('hashchange', followConversationLocation);
window.addEventListener('popstate', followConversationLocation);

function node(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value != null) element.setAttribute(key, String(value));
  }
  preventAutofill(element);
  for (const child of children.flat()) {
    if (child != null) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', paths[name]);
  if (name === 'more') path.setAttribute('stroke-width', '3.5');
  svg.append(path);
  return svg;
}
function button(text, fn, attributes = {}) {
  const element = node('button', {type: 'button', ...attributes}, text);
  element.addEventListener('click', fn);
  return element;
}
function title(item) { return item?.display_title || item?.name || '新对话'; }
function timestamp(item) { return Number(item.activity_at ?? item.last_active ?? item.created_at) || 0; }
function itemById(id) { return itemIndex.get(id); }
function activeRuns() { return (state.runs ? Object.values(state.runs) : state.running ? [state.running] : []).filter(run=>!completedRuns.has(run.run_id)); }
function runningFor(id) { const run=state.runs ? state.runs[id] || null : state.running?.conversation_id === id ? state.running : null;return run&&!completedRuns.has(run.run_id)?run:null; }
function groups() {
  const values=(Array.isArray(state.groups)?state.groups:[]).filter(group=>group.id!=='__archived__');
  return [{...(values.find(group=>group.id==='ungrouped')||{}),id:'ungrouped',name:'默认分组'},...values.filter(group=>group.id!=='ungrouped')];
}
function groupName(id) { return groups().find(group => group.id === id)?.name || '默认分组'; }
function isArchived(item) { return item?.archived === true || Number(item?.archived) === 1; }
function isBranch(item) { return Boolean(item?.parent_conversation_id || item?.branch_mode); }
function saveExpandedChildren() {
  try { localStorage.setItem(expansionKey, JSON.stringify([...expandedChildren])); } catch {}
}
function revealAncestors(id) {
  const seen = new Set();
  let parent = itemById(id)?.owner_conversation_id;
  while (parent && !seen.has(parent)) {
    seen.add(parent); expandedChildren.add(parent);
    parent = itemById(parent)?.owner_conversation_id;
  }
  saveExpandedChildren();
}
function groupFor(item) {
  const now = new Date(), date = new Date(timestamp(item) * 1000);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((today - day) / 86400000);
  return days <= 0 ? '今天' : days === 1 ? '昨天' : days < 7 ? '过去 7 天' : days < 30 ? '过去 30 天' : '更早';
}

async function api(resource, data) {
  const controller = new AbortController(), epoch = authEpoch;
  controllers.add(controller);
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
  try {
    const response = await fetch(resource, {
      credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      method: data === undefined ? 'GET' : 'POST',
      headers: {'Content-Type': 'application/json'}, body: data === undefined ? undefined : JSON.stringify(data),
    });
    let payload = {};
    try { payload = await response.json(); } catch { /* Report the HTTP failure below. */ }
    if (epoch !== authEpoch) throw new DOMException('登录状态已改变', 'AbortError');
    if (!response.ok || payload.ok === false) {
      if (response.status === 401 && authenticated) {
        window.dispatchEvent(new Event('xgent-auth-expired'));
        throw new DOMException('登录已失效', 'AbortError');
      }
      const error = new Error(payload.error || '请求失败（' + response.status + '）');
      error.status = response.status;
      throw error;
    }
    return payload;
  } catch (error) {
    if (timedOut) throw new Error('请求超时，请重试。');
    throw error;
  } finally { clearTimeout(timer); controllers.delete(controller); }
}

async function groupMutation(resource, data = {}) {
  const result = await api(resource, {...data, revision: state.revision});
  accept(result);
  return result;
}

function accept(next) {
  if (!Array.isArray(next?.items) || Number(next.revision) < state.revision) return;
  $('conversation-sync-error').hidden = true;
  const previous = state.current_chat_id;
  itemIndex = new Map(next.items.map(item => [item.id, item]));
  listReady = true;
  const linked = next.telegram_new_conversation;
  const adopted = !localCurrent && draftToken && linked?.token === draftToken && itemById(linked.conversation_id);
  if(adopted){
    const token=draftToken;
    localCurrent=linked.conversation_id;draftToken=null;draftVisible=false;
    try{sessionStorage.removeItem('xgent-new-conversation-token');}catch{}
    window.dispatchEvent(new CustomEvent('xgent-conversation-materialized',{detail:{conversation_id:localCurrent,generation:adopted.generation,token,adopted:true}}));
  }
  const missing = localCurrent && !itemById(localCurrent) || chatLocation() && locationParams().get('conversation') && !itemById(locationParams().get('conversation'));
  if(missing){localCurrent=null;newToken();if(chatLocation())history.replaceState(null,'','#/chat');}
  const combined = {...state, ...next, server_current_chat_id:next.current_chat_id, current_chat_id: localCurrent};
  if (JSON.stringify(combined) === JSON.stringify(state)) return;
  state = {...combined, running: combined.runs ? combined.runs[combined.current_chat_id] || null : combined.running};
  activeRuns().forEach(run=>knownRuns.set(run.run_id,run));
  keepConversationUrl();
  for (const id of expandedChildren) if (!itemIndex.has(id)) expandedChildren.delete(id);
  saveExpandedChildren();
  if (previous !== state.current_chat_id || !rows.size) revealAncestors(state.current_chat_id);
  render();
  window.dispatchEvent(new CustomEvent('xgent-conversation-state', {detail: state}));
  if (previous !== state.current_chat_id || missing) {
    window.dispatchEvent(new CustomEvent('xgent-conversation-changed', {
      detail: {previous, conversation_id: state.current_chat_id, ...(adopted?{materialized:true,generation:adopted.generation}: {})},
    }));
  }
  if(missing)window.dispatchEvent(new Event('xgent-new-conversation'));
}
async function refresh() {
  if (request) return request;
  const pending = api('/api/workbench/conversations').then(next=>{if(request===pending)accept(next);}).catch(error => {
    if(request!==pending)return;
    if (error.name === 'AbortError' || error.status === 401) return;
    if (!state.current_chat_id) renderLoadError(error);
    else {
      const notice = $('conversation-sync-error');
      notice.replaceChildren(node('span', {}, '同步暂停，保留已加载的对话。'), button('重试', refresh));
      notice.hidden = false;
    }
  }).finally(() => { if (request === pending) request = null; });
  request = pending;
  return pending;
}
function renderLoadError(error) {
  list.setAttribute('aria-busy', 'false');
  list.replaceChildren(node('div', {class: 'conv-list-empty'},
    node('strong', {}, '对话列表暂时不可用'), node('p', {}, error.message), button('重新加载', refresh)));
  listSignature = '';
}
async function mutate(name, data = {}) {
  if (mutation) return null;
  mutation = {name, id: data.id};
  render();
  try {
    const result = await api('/api/workbench/conversations/' + name, data);
    accept(result);
    if (name === 'create' || name === 'create_child'&&!isArchived(itemById(result.conversation_id))) selectLocal(result.conversation_id || result.current_chat_id);
    else if ((name === 'archive' && (result.archived_conversation_ids||[data.id]).includes(localCurrent)) ||
             (name === 'delete' && (result.deleted_conversation_ids || [data.id]).includes(localCurrent))) {
      selectLocal(result.current_chat_id || result.items?.[0]?.id);
    }
    return result;
  } finally { mutation = null; render(); }
}
async function prepareChat() {
  if (window.XGentWorkbench) return window.XGentWorkbench.prepareChat();
  document.body.dataset.page = 'chat';
  location.hash = conversationHref(localCurrent || state.current_chat_id);
  return true;
}
async function selectConversation(id) {
  if(isArchived(itemById(id))&&!enteredArchives.has(id)){await window.XGentWorkbench?.revealArchive(id);return false;}
  if (mutation || !await prepareChat()) return false;
  try {
    selectLocal(id);
    closeMenu(false);
    setDrawer(false);
    return true;
  } catch (error) { if (error.name !== 'AbortError') notify('切换失败：' + error.message, {error: true, retry: () => selectConversation(id)}); }
}
async function createConversation() {
  if (mutation || !await prepareChat()) return;
  try {
    search.value = '';
    draftVisible = true;draftGroup = groupView === 'all' ? 'ungrouped' : groupView;
    selectLocal(null);
    scroll.scrollTop = 0;
    closeMenu(false); setDrawer(false, false);
    requestAnimationFrame(() => $('input')?.focus({preventScroll: true}));
  } catch (error) { if (error.name !== 'AbortError') notify('新建失败：' + error.message, {error: true, retry: createConversation}); }
}
async function createChildConversation(id) {
  const parent = itemById(id);
  if (mutation || !parent) return;
  const archived=isArchived(parent);
  if(!archived&&!await prepareChat())return;
  closeMenu(false);
  try {
    search.value = ''; expandedChildren.add(id); saveExpandedChildren();
    if(!isArchived(parent))groupView = parent.group_id || 'ungrouped';
    const requestId = crypto.randomUUID();
    const result = await mutate('create_child', {id, generation: parent.generation, request_id: requestId});
    if (!result) return;
    if(archived){await window.XGentWorkbench?.revealArchive(result.conversation_id);return;}
    setDrawer(false, false);
    requestAnimationFrame(() => $('input')?.focus({preventScroll: true}));
  } catch (error) { if (error.name !== 'AbortError') notify('新建子对话失败：' + error.message, {error: true, retry: refresh}); }
}
async function archiveConversation(id) {
  const item = itemById(id);
  if (!item || mutation) return;
  closeMenu(false);
  try {
    const result = await mutate('archive', {id});
    if (!result) return;
    notify('已归档「' + title(item) + '」', {label: '撤销', undo: async () => {
      await restoreConversation(id);
    }});
  } catch (error) { if (error.name !== 'AbortError') notify('归档失败：' + error.message, {error: true, retry: () => archiveConversation(id)}); }
}
async function restoreConversation(id, open = true) {
  if (mutation) return;
  closeMenu(false);
  try {
    if (!await mutate('restore', {id})) return;
    if (open) { search.value = '';groupView=itemById(id)?.group_id||'ungrouped'; await selectConversation(id); render(); }
    else notify('已恢复到最近对话');
  } catch (error) { if (error.name !== 'AbortError') notify('恢复失败：' + error.message, {error: true, retry: () => restoreConversation(id, open)}); }
}
function notify(text, options = {}) {
  clearTimeout(feedbackTimer);
  const feedback = $('conversation-feedback');
  const message = node('span', {class: 'conv-feedback-text'}, text);
  feedback.classList.toggle('is-error', !!options.error);
  feedback.replaceChildren(message);
  const fn = options.undo || options.retry;
  if (fn) feedback.append(button(options.label || '重试', async event => {
    event.currentTarget.disabled = true;
    try { await fn(); if (!options.undo) feedback.hidden = true; }
    catch (error) { notify(error.message, {error: true}); }
  }, {class: 'conv-feedback-action'}));
  feedback.append(button(icon('close'), () => { feedback.hidden = true; }, {class: 'conv-icon-button', 'aria-label': '关闭提示'}));
  feedback.hidden = false;
  if (!options.error) feedbackTimer = setTimeout(() => { feedback.hidden = true; }, options.undo ? 10000 : 4500);
}

function createRow(item) {
  const row = node('div', {class: 'conv-row', 'data-conversation-id': item.id});
  const branch = node('span', {class: 'conv-branch-badge', hidden: '', title: '分支对话', 'aria-label':'分支对话'}, icon('branch'));
  const childBadge = node('span', {class: 'conv-child-badge', hidden: '', title:'子对话','aria-label':'子对话'}, icon('branch'));
  const name = node('span', {class: 'conv-row-title'});
  const bot = node('span', {class: 'conv-bot-badge', hidden: '', title: 'Telegram 当前使用此对话，不代表正在执行任务'}, 'Bot 当前');
  const dot = node('span', {class: 'conv-running-dot', 'aria-label': '正在生成', hidden: ''});
  const open = node('a', {href: conversationHref(item.id), draggable: 'true',
    class: 'conv-open', 'data-focus': 'open:' + item.id}, branch, childBadge, name, bot, dot);
  open.addEventListener('click', event => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const current = itemById(item.id);
    if (current && isArchived(current)) restoreConversation(item.id, true);
    else selectConversation(item.id);
  });
  const more = button(icon('more'), event => openMenu(item.id, event.currentTarget), {
    class: 'conv-more conv-icon-button', 'aria-haspopup': 'menu', 'aria-expanded': 'false', 'data-focus': 'more:' + item.id,
  });
  more.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') { event.preventDefault(); openMenu(item.id, more); }
  });
  const restore = button(icon('restore'), () => restoreConversation(item.id), {class: 'conv-restore conv-icon-button', hidden: ''});
  const toggle = button(node('span', {class: 'conv-child-chevron', 'aria-hidden': 'true'}, '›'), () => {
    if (expandedChildren.has(item.id)) expandedChildren.delete(item.id); else expandedChildren.add(item.id);
    saveExpandedChildren(); renderList();
  }, {class: 'conv-children-toggle conv-icon-button', hidden: '', 'data-focus': 'children:' + item.id,
      'aria-controls': 'conversation-children-' + item.id, 'aria-expanded': 'false'});
  row.append(open, restore, toggle, more);
  return {row, open, branch, childBadge, name, more, dot, restore, bot, toggle};
}
function renderDraftRow(){
  if(!draftEntry){
    const name=node('span',{class:'conv-row-title'},'新对话');
    const bot=node('span',{class:'conv-bot-badge',hidden:'',title:'发送第一条消息后创建 Bot 当前对话'},'Bot 当前');
    const open=node('a',{href:conversationHref(null),draggable:'true',class:'conv-open','data-focus':'open:new','aria-label':'打开对话：新对话'},name,bot);
    open.addEventListener('click',async event=>{if(event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();if(!mutation&&await prepareChat()){selectLocal(null);setDrawer(false);$('input')?.focus();}});
    const more=button(icon('more'),event=>openDraftMenu(event.currentTarget),{class:'conv-more conv-icon-button','aria-label':'更多操作：新对话','aria-haspopup':'menu','aria-expanded':'false','data-focus':'more:new'});
    more.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();openDraftMenu(more);}});
    const row=node('div',{class:'conv-row conv-draft-row','data-conversation-draft':''},open,more);
    draftEntry={row,open,more,bot};
  }
  draftEntry.row.classList.toggle('is-current',!localCurrent);
  draftEntry.open.setAttribute('aria-current',String(!localCurrent));
  draftEntry.bot.hidden=state.telegram_new_conversation?.token!==draftToken;
  draftEntry.more.disabled=!!mutation;
  draftEntry.more.setAttribute('aria-expanded',String(menuTarget===draftMenuTarget));
  return draftEntry.row;
}
function openDraftMenu(trigger){
  if(mutation||!draftVisible)return;
  if(menuTarget===draftMenuTarget){closeMenu();return;}
  closeMenu(false);menuTarget=draftMenuTarget;menuTrigger=trigger;trigger.setAttribute('aria-expanded','true');
  const current=state.telegram_new_conversation?.token===draftToken;
  const select=button(current?'🤖 Bot 当前对话':'🤖 设为 Bot 当前对话',setBotNewConversation,{role:'menuitem'});
  select.disabled=current;
  menu.replaceChildren(select);menu.hidden=false;positionMenu();select.focus({preventScroll:true});
}
function renderList() {
  if (search.value.trim()) {
    listSignature = '';
    globalResults.search(search.value);
    return;
  }
  if (globalResults.options) globalResults.reset();
  const query = search.value.trim().toLocaleLowerCase();
  const visible = state.items.filter(item => !isArchived(item)
      && (groupView === 'all' || (item.group_id||'ungrouped') === groupView)
      && title(item).toLocaleLowerCase().includes(query))
    .sort((a, b) => {
      const pinned = !query ? Number(b.pinned || 0) - Number(a.pinned || 0) : 0;
      return pinned || timestamp(b) - timestamp(a) || a.id.localeCompare(b.id);
    });
  const showDraft=authenticated&&draftVisible&&(groupView==='all'||groupView===draftGroup);
  const signature = JSON.stringify([groupView, query, showDraft, draftToken, state.telegram_new_conversation, groups().map(group=>[group.id,group.name]), state.current_chat_id, state.telegram_conversation_id, activeRuns(), mutation,
    [...expandedChildren], visible.map(item => [item.id, title(item), groupFor(item), item.group_id, item.pinned,
      item.parent_conversation_id, item.branch_mode, item.owner_conversation_id])]);
  if (signature === listSignature) return;
  listSignature = signature;
  const oldScroll = scroll.scrollTop;
  const focused = list.contains(document.activeElement) ? document.activeElement.dataset.focus : null;
  const children = [];
  const visibleIds = new Set(visible.map(item => item.id)), descendants = new Map();
  for (const item of visible) {
    const owner = item.owner_conversation_id;
    if (owner && owner !== item.id && visibleIds.has(owner)) {
      if (!descendants.has(owner)) descendants.set(owner, []);
      descendants.get(owner).push(item);
    }
  }
  const visited = new Set();
  let group = '';
  if(showDraft){group='今天';children.push(node('h3',{class:'conv-date-group'},group),renderDraftRow());}
  function renderTree(item, depth = 0) {
    if (visited.has(item.id)) return null;
    visited.add(item.id);
    const nested = descendants.get(item.id) || [];
    const entry = rows.get(item.id) || createRow(item);
    rows.set(item.id, entry);
    const current = item.id === state.current_chat_id;
    const branched = isBranch(item);
    entry.row.classList.toggle('is-current', current);
    entry.row.classList.toggle('is-archived', isArchived(item));
    entry.row.classList.toggle('is-branch', branched);
    entry.row.classList.toggle('is-child', !!item.owner_conversation_id);
    entry.row.style.setProperty('--conv-depth', String(Math.min(depth, 3)));
    entry.row.classList.toggle('is-pinned',!!item.pinned&&!query);
    entry.row.classList.toggle('is-pending', mutation?.name === 'switch' && mutation.id === item.id);
    entry.branch.hidden = !branched||!!item.owner_conversation_id;
    entry.childBadge.hidden = !item.owner_conversation_id;
    entry.childBadge.title = '子对话 · 父对话：' + title(itemById(item.owner_conversation_id));
    if (branched) {
      const parent = item.parent_conversation_id ? itemById(item.parent_conversation_id) : null;
      const modeText = item.branch_mode === 'exact' ? '精确文件现场' : '仅上下文';
      entry.branch.title = (parent ? '分支来源：' + title(parent) + ' · ' : '分支对话 · ') + modeText;
    }
    entry.bot.hidden = item.id !== state.telegram_conversation_id;
    entry.name.textContent = title(item);
    entry.open.title = title(item);
    entry.open.setAttribute('aria-label', (isArchived(item) ? '已归档：' : '打开对话：') + title(item));
    if (current) entry.open.setAttribute('aria-current', 'true'); else entry.open.removeAttribute('aria-current');
    entry.dot.hidden = !runningFor(item.id);
    entry.open.setAttribute('aria-disabled', String(!!mutation));
    entry.restore.hidden = !isArchived(item);
    entry.restore.disabled = !!mutation;
    entry.restore.title = '恢复对话';
    entry.restore.setAttribute('aria-label', '恢复对话：' + title(item));
    entry.more.disabled = !!mutation;
    entry.more.title = '更多操作';
    entry.more.setAttribute('aria-label', '更多操作：' + title(item));
    entry.more.setAttribute('aria-expanded', String(menuTarget === item.id));
    entry.toggle.hidden = !nested.length;
    entry.toggle.setAttribute('aria-expanded', String(expandedChildren.has(item.id)));
    entry.toggle.setAttribute('aria-label', (expandedChildren.has(item.id) ? '收起' : '展开') + '子对话：' + title(item));
    entry.toggle.title = (expandedChildren.has(item.id) ? '收起' : '展开') + ' ' + nested.length + ' 个子对话';
    if (!nested.length) return entry.row;
    const childList = node('div', {class: 'conv-child-list', id: 'conversation-children-' + item.id,
      role: 'group', 'aria-label': title(item) + '的子对话', hidden: expandedChildren.has(item.id) ? null : ''});
    for (const child of nested) childList.append(...[renderTree(child, depth + 1)].filter(Boolean));
    return node('div', {class: 'conv-tree-node'}, entry.row, childList);
  }
  const roots = visible.filter(item => !item.owner_conversation_id || !visibleIds.has(item.owner_conversation_id));
  // Keep malformed imported ownership cycles visible and finite.
  for (const item of [...roots, ...visible]) {
    if (visited.has(item.id)) continue;
    const next = query ? '搜索结果 · ' + visible.length :
      (item.pinned ? '置顶' : groupFor(item));
    if (next !== group) { group = next; children.push(node('h3', {class: 'conv-date-group'}, group)); }
    children.push(renderTree(item));
  }
  if (!visible.length && !showDraft) {
    children.push(node('div', {class: 'conv-list-empty'},
      node('strong', {}, query ? '没有找到对话' : '从一段新对话开始'),
      node('p', {}, query ? '换个关键词，或清除搜索。' : '你的对话会保留在这里，随时回来继续。'),
      query ? button('清除搜索', () => { search.value = ''; render(); search.focus(); }) : null));
  }
  list.replaceChildren(...children);
  list.setAttribute('aria-busy', 'false');
  scroll.scrollTop = oldScroll;
  for (const [id] of rows) if (!itemById(id)) rows.delete(id);
  if (focused) Array.from(list.querySelectorAll('[data-focus]')).find(element => element.dataset.focus === focused)?.focus({preventScroll: true});
  if (menuTarget) { if (menuTarget===draftMenuTarget? !showDraft : !itemById(menuTarget)) closeMenu(false); else positionMenu(); }
}
function renderRunning() {
  $('conversation-current-status').hidden = !runningFor(state.current_chat_id);
}
function completion(frame){
  const {run_id:id,conversation_id:cid}=frame;
  if(!id||!cid||completedRuns.has(id))return;
  const run=knownRuns.get(id),item=itemById(cid);
  if(!run||!item||frame.generation!=null&&frame.generation!==item.generation)return;
  completedRuns.add(id);knownRuns.delete(id);if(completedRuns.size>500)completedRuns.delete(completedRuns.values().next().value);
  render();
  if(cid===localCurrent||run.stop_requested)return;
  const area=$('conversation-completions'),notice=node('div',{class:'conv-completion','data-run-id':id,role:'status'});
  let timer;
  const remove=()=>{clearTimeout(timer);completionTimers.delete(timer);notice.remove();};
  const close=button(icon('close'),remove,{class:'conv-icon-button conv-completion-close','aria-label':'关闭对话完成通知'});
  const link=node('a',{href:conversationHref(cid),draggable:'true'},title(item));
  link.onclick=event=>{if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();remove();isArchived(item)?window.XGentWorkbench?.revealArchive(cid):selectConversation(cid);};
  notice.append(node('strong',{},frame.type==='turn_error'?'对话处理已结束':'回复已完成'),link,close);
  area.append(notice);while(area.children.length>3)area.firstElementChild.remove();
  timer=setTimeout(remove,8000);completionTimers.add(timer);
  refresh();
}
function render() {
  searchAutofill.remember();
  const selected = itemById(state.current_chat_id);
  $('wb-conversation-title').textContent = title(selected);
  $('wb-conversation-title').title = title(selected);
  document.querySelector('.wb-brand')?.setAttribute('href',conversationHref(localCurrent));
  $('conversation-new').setAttribute('aria-disabled',String(!authenticated || !!mutation));
  $('conversation-new').setAttribute('aria-busy', String(mutation?.name === 'create'));
  $('conversation-search-clear').hidden = !search.value;
  $('conversation-list-title').textContent = search.value.trim() ? '全局搜索' : groupView === 'all' ? '全部对话' : groupName(groupView);
  const select = $('conversation-group-select');
  if (select) {
    const options = [groups()[0],{id:'all',name:'全部对话'},...groups().slice(1)];
    select.replaceChildren(...options.map(item => node('option',{value:item.id},item.name)));
    if(!options.some(item => item.id === groupView))groupView='ungrouped';
    select.value = groupView;
  }
  if (listReady) renderList();
  renderRunning();
}

function closeMenu(restore = true) {
  const trigger = menuTrigger;
  if (trigger) trigger.setAttribute('aria-expanded', 'false');
  menu.hidden = true; menuTarget = null; menuTrigger = null;
  clearTimeout(moveHideTimer);moveSubmenu=null;moveTrigger=null;
  if (restore && trigger?.isConnected) trigger.focus({preventScroll: true});
}
function positionMenu() {
  if(menu.hidden)return;
  if(!menuTrigger?.isConnected){closeMenu(false);return;}
  const anchor = menuTrigger.getBoundingClientRect(), bounds = menu.getBoundingClientRect();
  menu.style.left = Math.max(8, Math.min(innerWidth - bounds.width - 8, anchor.right - bounds.width)) + 'px';
  menu.style.top = Math.max(8, Math.min(innerHeight - bounds.height - 8, anchor.bottom + 5)) + 'px';
  positionMoveMenu();
}
function positionMoveMenu(){
  if(!moveSubmenu||moveSubmenu.hidden||!moveTrigger?.isConnected)return;
  const anchor=moveTrigger.getBoundingClientRect();
  moveSubmenu.style.position=mobile.matches?'static':'fixed';moveSubmenu.style.width=mobile.matches?'100%':'180px';
  if(mobile.matches)return;
  const bounds=moveSubmenu.getBoundingClientRect(),right=anchor.right+5;
  moveSubmenu.style.left=Math.max(8,Math.min(innerWidth-bounds.width-8,right+bounds.width<=innerWidth-8?right:anchor.left-bounds.width-5))+'px';
  moveSubmenu.style.top=Math.max(8,Math.min(innerHeight-bounds.height-8,anchor.top))+'px';
}
function showMoveMenu(focus=false){
  if(!moveSubmenu||moveTrigger?.disabled)return;clearTimeout(moveHideTimer);moveSubmenu.hidden=false;moveTrigger.setAttribute('aria-expanded','true');positionMenu();
  if(focus)(moveSubmenu.querySelector('button:not(:disabled)')||moveSubmenu).focus();
}
function hideMoveMenu(focus=false){
  clearTimeout(moveHideTimer);if(moveSubmenu)moveSubmenu.hidden=true;if(moveTrigger)moveTrigger.setAttribute('aria-expanded','false');
  if(focus)moveTrigger?.focus();positionMenu();
}
async function exportConversation(item){
  if(exporting.has(item.id))return;
  closeMenu(false);exporting.add(item.id);
  const controller=new AbortController(),epoch=authEpoch;controllers.add(controller);
  const timeout=setTimeout(()=>controller.abort(),120000);
  notify('正在导出「'+title(item)+'」…');
  try{
    const response=await fetch('/api/workbench/conversations/export',{method:'POST',credentials:'same-origin',signal:controller.signal,
      headers:{'Content-Type':'application/json'},body:JSON.stringify({id:item.id})});
    if(response.status===401){window.dispatchEvent(new Event('xgent-auth-expired'));return;}
    if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(error.error||'导出失败');}
    if(!(response.headers.get('Content-Type')||'').includes('application/zip'))throw new Error('导出未返回ZIP文件，请检查登录后重试');
    const blob=await response.blob();if(epoch!==authEpoch||!authenticated)return;
    const match=/filename\*=UTF-8''([^;]+)/i.exec(response.headers.get('Content-Disposition')||'');
    const url=URL.createObjectURL(blob),link=node('a',{href:url,download:match?decodeURIComponent(match[1]):'系统记忆.zip'});
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    notify('「'+title(item)+'」的完整记忆已下载');
  }catch(error){if(epoch===authEpoch)notify(error.name==='AbortError'?'导出超时，请重试':error.message,{error:true});}
  finally{clearTimeout(timeout);controllers.delete(controller);exporting.delete(item.id);}
}
function openMenu(id, trigger) {
  if (mutation) return;
  if (menuTarget === id) { closeMenu(); return; }
  closeMenu(false);
  const item = itemById(id);
  if (!item) return;
  menuTarget = id; menuTrigger = trigger;
  trigger.setAttribute('aria-expanded', 'true');
  const rename = button([icon('rename'), node('span', {}, '重命名')], () => openRename(id), {role: 'menuitem'});
  rename.disabled=isArchived(item);if(rename.disabled)rename.title='归档对话名称固定，恢复后可以重命名';
  const other = isArchived(item)
    ? button([icon('restore'), node('span', {}, '恢复对话')], () => restoreConversation(id), {role: 'menuitem'})
    : button([icon('archive'), node('span', {}, '归档对话')], () => archiveConversation(id), {role: 'menuitem'});
  const download=button([icon('export'),node('span',{},'导出')],()=>exportConversation(item),{role:'menuitem'});download.disabled=exporting.has(id);
  const newChild=button([icon('branch'),node('span',{},'新建子对话')],()=>createChildConversation(id),{role:'menuitem'});
  const remove=button('🗑 删除对话',()=>confirmConversationAction('delete',id),{role:'menuitem',class:'danger'});
  const botCurrent=state.telegram_conversation_id===id;
  const setBot=button(botCurrent?'🤖 Bot 当前对话':'🤖 设为 Bot 当前对话',()=>setBotConversation(item),{role:'menuitem'});
  setBot.disabled=botCurrent||isArchived(item)||!state.telegram_configured;
  setBot.title=!state.telegram_configured?'此部署未配置 Telegram Bot':isArchived(item)?'请先恢复已归档会话':botCurrent?'Bot 已使用此对话':'只改变 Bot 的选择，不切换网页或终端，不改投运行任务';
  const pin=button(item.pinned?'📌 取消组内置顶':'📌 组内置顶',async()=>{
    closeMenu(false);
    try{await groupMutation('/api/workbench/conversations/'+(item.pinned?'unpin':'pin'),{id:item.id,group_id:item.group_id||'ungrouped'});notify(item.pinned?'已取消组内置顶':'已在「'+groupName(item.group_id||'ungrouped')+'」置顶');}
    catch(error){notify(error.message,{error:true,retry:refresh});}
  },{role:'menuitem'});
  pin.title='所属分组：'+groupName(item.group_id||'ungrouped');
  pin.disabled=isArchived(item);if(pin.disabled)pin.title='归档期间保留原置顶信息';
  const moveWrapper=node('div',{class:'conv-move-menu'});
  moveTrigger=button([node('span',{},'移动到'),node('span',{class:'conv-menu-caret','aria-hidden':'true'},'›')],()=>moveSubmenu.hidden?showMoveMenu():hideMoveMenu(),{role:'menuitem','aria-haspopup':'menu','aria-expanded':'false'});
  moveTrigger.disabled=!!item.owner_conversation_id||isArchived(item);
  if(isArchived(item))moveTrigger.title='归档对话通过恢复操作返回原分组';
  if(item.owner_conversation_id)moveTrigger.title='子对话跟随父对话分组';
  moveSubmenu=node('div',{class:'conv-group-submenu',role:'menu','aria-label':'移动到分组',tabindex:'-1',hidden:''});
  const moveButtons=groups().map(group=>button((group.id===(item.group_id||'ungrouped')?'✓ ':'')+group.name,async()=>{
    closeMenu(false);
    try{await groupMutation('/api/workbench/conversations/move',{id:item.id,group_id:group.id});notify('已移动到「'+group.name+'」');}
    catch(error){notify(error.message,{error:true,retry:refresh});}
  },{role:'menuitem',disabled:group.id===(item.group_id||'ungrouped')?'':null}));
  moveSubmenu.append(...moveButtons);moveWrapper.append(moveTrigger,moveSubmenu);
  moveWrapper.addEventListener('pointerenter',event=>{if(event.pointerType!=='touch'&&!moveTrigger.disabled)showMoveMenu();});
  moveWrapper.addEventListener('pointerleave',event=>{if(event.pointerType!=='touch')moveHideTimer=setTimeout(()=>hideMoveMenu(),150);});
  menu.replaceChildren(rename, newChild, other, download, pin, moveWrapper, setBot, remove); menu.hidden = false; positionMenu();
  rename.focus({preventScroll: true});
}
async function setBotConversation(item){
  if(mutation)return;
  const expected=state.telegram_conversation_id;
  closeMenu(false);
  try{
    if(await mutate('set_bot',{id:item.id,generation:item.generation,expected_bot:expected,expected_draft:state.telegram_new_conversation?.token||null}))notify('Bot 当前对话已设为「'+title(item)+'」，网页选择不变。');
  }catch(error){if(error.name!=='AbortError'){notify('设置失败：'+error.message,{error:true,retry:refresh});await refresh();}}
}
async function setBotNewConversation(){
  if(mutation||!draftVisible||!authenticated)return;
  const token=newToken();
  closeMenu(false);
  try{
    const result=await mutate('set_bot',{new_conversation:token,group_id:draftGroup,
      expected_bot:state.telegram_conversation_id,expected_draft:state.telegram_new_conversation?.token||null});
    if(result)notify('新对话已设为 Bot 当前；网页或 Telegram 发送第一条消息后保存。');
  }catch(error){if(error.name!=='AbortError'){notify('设置失败：'+error.message,{error:true,retry:refresh});await refresh();}}
}
async function confirmConversationAction(action,id) {
  closeMenu(false);
  const item=itemById(id);if(!item)return;
  let info;
  try{info=await api('/api/workbench/conversations/delete_info?id='+encodeURIComponent(id));}
  catch(error){notify(error.message);return;}
  const deleting=action==='delete', dialog=node('dialog',{class:'conv-dialog conv-action-dialog','aria-label':deleting?'删除对话':'重置上下文'});
  const feedback=node('p',{role:'alert'});
  const cancel=button('取消',()=>dialog.close());
  const confirm=button(deleting?'永久删除':'确认重置',async()=>{
    cancel.disabled=confirm.disabled=true;feedback.textContent='';
    try{
      const result=await mutate(action,{id,confirm:true});if(!result)return;
      dialog.close();notify(deleting?(result.deleting?'删除已提交，正在停止所属任务…':'已删除「'+title(item)+'」'):'已重置「'+title(item)+'」的上下文，历史保留。');
      if(deleting)for(const target of result.deleted_conversation_ids||[id])window.dispatchEvent(new CustomEvent('xgent-conversation-deleted',{detail:{conversation_id:target}}));
    }catch(error){feedback.textContent=error.message;}
    finally{cancel.disabled=confirm.disabled=false;}
  },{class:deleting?'danger':''});
  dialog.append(node('h2',{},deleting?'永久删除对话？':'重置模型上下文？'),node('p',{},title(item)+' · '+id.slice(0,6)),
    node('p',{},deleting?'会话历史与任务记录将永久删除'+(info.child_count?'，包括 '+info.child_count+' 个子对话':'')+'，并终止 '+info.active_tasks+' 个未完成任务。共享工作目录文件和用量统计保留。':'历史消息、附件与定时任务保留；此前内容不再提供给模型，其他会话不受影响。'),
    feedback,node('div',{class:'conv-dialog-actions'},cancel,confirm));
  dialog.addEventListener('cancel',event=>{if(confirm.disabled)event.preventDefault();});
  dialog.addEventListener('close',()=>dialog.remove(),{once:true});document.body.append(dialog);dialog.showModal();cancel.focus();
}

function openRename(id) {
  if(isArchived(itemById(id))){notify('归档对话名称固定，恢复后可以重命名');return;}
  const item = itemById(id);
  if (!item || mutation) return;
  renameTarget = id; renameReturn = menuTrigger || document.activeElement;
  closeMenu(false);
  $('conversation-rename-input').value = title(item);
  $('conversation-rename-error').hidden = true;
  renameDialog.showModal();
  $('conversation-rename-input').focus(); $('conversation-rename-input').select();
}
function closeRename() { if (!renameSaving) renameDialog.close(); }
renameDialog.addEventListener('close', () => {
  renameTarget = null;
  if (renameReturn?.isConnected) renameReturn.focus({preventScroll: true});
});
renameDialog.addEventListener('cancel', event => { if (renameSaving) event.preventDefault(); });
$('conversation-rename-close').addEventListener('click', closeRename);
$('conversation-rename-cancel').addEventListener('click', closeRename);
$('conversation-rename-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (renameSaving || mutation || !renameTarget) return;
  const name = $('conversation-rename-input').value.trim(), id = renameTarget;
  const error = $('conversation-rename-error');
  if (!name) { error.textContent = '请输入对话名称。'; error.hidden = false; return; }
  renameSaving = true; error.hidden = true;
  renameDialog.querySelectorAll('button,input').forEach(element => { element.disabled = true; });
  $('conversation-rename-save').textContent = '保存中…';
  try { if (await mutate('rename', {id, name})) renameDialog.close(); }
  catch (exc) { if (exc.name !== 'AbortError') { error.textContent = exc.message; error.hidden = false; } }
  finally {
    renameSaving = false;
    renameDialog.querySelectorAll('button,input').forEach(element => { element.disabled = false; });
    $('conversation-rename-save').textContent = '保存';
    if (renameDialog.open) $('conversation-rename-input').focus();
  }
});

function setDrawer(open, restoreFocus = true) {
  open = !!open && mobile.matches;
  if (open === drawerOpen) { syncConversationToggle(); return; }
  drawerOpen = open;
  document.body.classList.toggle('conv-drawer-open', open);
  $('conversation-backdrop').hidden = !open;
  syncConversationToggle();
  const shell = $('wb-shell');
  if (open) {
    drawerReturn = document.activeElement;
    previousInert = shell.inert; shell.inert = true;
    sidebar.setAttribute('role', 'dialog'); sidebar.setAttribute('aria-modal', 'true');
    requestAnimationFrame(() => $('conversation-drawer-close').focus({preventScroll: true}));
  } else {
    closeMenu(false);window.XGentWorkspaceMenu?.close();
    sidebar.removeAttribute('role'); sidebar.removeAttribute('aria-modal');
    if (previousInert !== null) { shell.inert = previousInert; previousInert = null; }
    if (restoreFocus && drawerReturn?.isConnected) drawerReturn.focus({preventScroll: true});
  }
}
$('conversation-new').addEventListener('click',event=>{if(event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();if(authenticated&&!mutation)createConversation();});
$('conversation-new').addEventListener('keydown',event=>{if(event.key===' '){event.preventDefault();if(authenticated&&!mutation)createConversation();}});
$('conversation-drawer-toggle').addEventListener('click', () => {
  if(mobile.matches)setDrawer(!drawerOpen);
  else {const collapsed=document.body.classList.toggle('conv-sidebar-collapsed');try{localStorage.setItem('xgent-conversation-sidebar-collapsed',collapsed?'1':'0');}catch{}syncConversationToggle();}
});
$('conversation-mobile-toggle').addEventListener('click',()=>setDrawer(!drawerOpen));
$('conversation-drawer-close').addEventListener('click', () => setDrawer(false));
$('conversation-backdrop').addEventListener('click', () => setDrawer(false));
$('workspace-menu').addEventListener('click',event=>{if(event.target.closest('a, #btn-settings, #btn-search, #wb-logout'))setDrawer(false,false);});
search.addEventListener('input', event => { if (!event.isComposing) { closeMenu(false); render(); scroll.scrollTop = 0; } });
search.addEventListener('compositionend', () => { closeMenu(false); render(); scroll.scrollTop = 0; });
$('conversation-search-clear').addEventListener('click', () => { search.value = ''; render(); search.focus(); });
search.addEventListener('keydown', event => {
  if (event.isComposing) return;
  if (event.key === 'Enter' && search.value.trim()) { event.preventDefault(); clearTimeout(globalResults.timer); globalResults.load(); }
  if (event.key === 'ArrowDown') { event.preventDefault(); list.querySelector('.global-search-hit,.conv-open:not(:disabled),.conv-restore:not([hidden])')?.focus(); }
});
list.addEventListener('keydown', event => {
  if (!event.target.matches('.conv-open') || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const choices = Array.from(list.querySelectorAll('.conv-open:not(:disabled)')).filter(element=>element.getClientRects().length);
  const index = choices.indexOf(event.target);
  if (event.key === 'ArrowUp' && index === 0) { search.focus(); return; }
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? choices.length - 1 : Math.max(0, Math.min(choices.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
  choices[next]?.focus();
});
scroll.addEventListener('scroll', () => {
  if (!menuTrigger || menu.hidden) return;
  const anchor = menuTrigger.getBoundingClientRect(), viewport = scroll.getBoundingClientRect();
  if (anchor.bottom < viewport.top || anchor.top > viewport.bottom) closeMenu(false);
  else positionMenu();
}, {passive: true});
window.addEventListener('resize', () => { if (!mobile.matches) setDrawer(false, false); positionMenu(); });
window.addEventListener('hashchange', () => { closeMenu(false); setDrawer(false, false); });
document.addEventListener('pointerdown', event => {
  if (!menu.hidden && !menu.contains(event.target) && !event.target.closest('.conv-more')) closeMenu(false);
}, true);
document.addEventListener('keydown', event => {
  if (document.getElementById('global-search-dialog')?.open) return;
  if (!$('workspace-menu').hidden) { if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();window.XGentWorkspaceMenu?.close(true);}return; }
  if (event.isComposing || renameDialog.open) return;
  if (!menu.hidden) {
    const insideMove=moveSubmenu&&!moveSubmenu.hidden&&moveSubmenu.contains(document.activeElement);
    if(event.key==='ArrowRight'&&document.activeElement===moveTrigger){event.preventDefault();showMoveMenu(true);return;}
    if(insideMove&&['ArrowLeft','Escape'].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();hideMoveMenu(true);return;}
    const choices = Array.from((insideMove?moveSubmenu:menu).querySelectorAll('button')).filter(button=>!button.disabled&&button.getClientRects().length&&(insideMove||!button.closest('.conv-group-submenu')));
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      if(!choices.length)return;
      let index = choices.indexOf(document.activeElement);
      index = event.key === 'Home' ? 0 : event.key === 'End' ? choices.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + choices.length) % choices.length;
      choices[index].focus(); return;
    }
    if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); closeMenu(); return; }
    if (event.key === 'Tab') closeMenu();
  }
  if (drawerOpen && event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); setDrawer(false); return; }
  if (drawerOpen && event.key === 'Tab') {
    const focusable = [sidebar, $('conversation-feedback')].flatMap(root => Array.from(root.querySelectorAll('button,input,a[href]'))).filter(element => !element.disabled && element.getClientRects().length);
    const first = focusable[0], last = focusable[focusable.length - 1];
    if ((event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
      event.preventDefault(); (event.shiftKey ? last : first)?.focus();
    }
  }
}, true);

window.XGentConversations = {
  observeRun:frame=>{if(frame.run_id&&frame.conversation_id&&!completedRuns.has(frame.run_id)&&['message','edit','chat_action'].includes(frame.type)){knownRuns.set(frame.run_id,{...knownRuns.get(frame.run_id),...frame});if(knownRuns.size>500)knownRuns.delete(knownRuns.keys().next().value);}},
  completion,
  new:async()=>{if(await prepareChat())selectLocal(null,'replace');},
  materialize:(result,token,groupId='ungrouped')=>{
    const id=result.conversation_id;if(!id)return false;
    const adopted=!localCurrent&&draftToken===token;
    if(Number.isSafeInteger(result.conversation_revision))state.revision=Math.max(state.revision,result.conversation_revision);
    if(!itemById(id)){const item={id,name:'新对话',generation:result.generation,archived:0,group_id:groupId,created_at:Date.now()/1000};state.items=[item,...state.items];itemIndex.set(id,item);listSignature='';}
    window.dispatchEvent(new CustomEvent('xgent-conversation-materialized',{detail:{conversation_id:id,generation:result.generation,token,adopted}}));
    if(draftToken===token){draftToken=null;draftVisible=false;try{sessionStorage.removeItem('xgent-new-conversation-token');}catch{}}
    if(adopted){if(groupId!=='all')groupView=groupId;selectLocal(id,'replace',{materialized:true,token,generation:result.generation});}
    else render();
    request=null;refresh();return adopted;
  },
  get isNew(){return !localCurrent;},
  get newToken(){return newToken();},
  get newGroup(){const linked=state.telegram_new_conversation;return linked?.token===draftToken?linked.group_id||'ungrouped':draftVisible?draftGroup:groupView==='all'?'ungrouped':groupView;},
  restore:id=>restoreConversation(id),
  enter:async(id,message)=>{if(isArchived(itemById(id))){enteredArchives.add(id);try{sessionStorage.setItem('xgent-entered-archives',JSON.stringify([...enteredArchives]));}catch{}}if(!await selectConversation(id))return false;if(message)location.hash=conversationHref(id)+'&message='+encodeURIComponent(message);return true;},
  enteredArchive:id=>enteredArchives.has(id),
  createChild:createChildConversation,
  menu:(id,trigger)=>openMenu(id,trigger),
  accept, refresh, get items(){return state.items;},
  async select(id){if(mutation)throw new Error('正在切换对话，请稍后重试');if(!itemById(id)){selectLocal(null,'replace');return false;}if(isArchived(itemById(id))&&!enteredArchives.has(id)){await window.XGentWorkbench?.revealArchive(id);return false;}selectLocal(id);closeMenu(false);setDrawer(false);return state.current_chat_id===id;},
  href: conversationHref, followLocation: followConversationLocation,
  get readOnly(){return !!state.current_chat_id&&listReady&&!itemById(state.current_chat_id);},
  get archived(){return isArchived(itemById(state.current_chat_id));},
  get current() { return state.current_chat_id; }, get running() { return runningFor(state.current_chat_id); }, get runs() { return activeRuns(); },
};
const groupSelect = $('conversation-group-select');
groupSelect?.addEventListener('change', () => { closeMenu(false);search.value='';groupView = groupSelect.value || 'ungrouped'; render(); scroll.scrollTop = 0; });
function groupDialog(group = null) {
  if(group?.id==='ungrouped'){notify('“默认分组”是保留分组，不能删除或重命名');return;}
  const dialog=node('dialog',{class:'conv-dialog','aria-label':group?'管理分组':'新建分组'});
  const input=node('input',{type:'text',maxlength:80,required:'', 'aria-label':'分组名称'});input.value=group?.name||'';
  const error=node('p',{role:'alert'}),form=node('form',{},node('h2',{},group?'管理分组':'新建分组'),node('label',{},'分组名称',input),error);
  const cancel=button('取消',()=>dialog.close());
  const save=node('button',{type:'submit',class:'conv-save'},'保存');
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;
    try{const result=await groupMutation('/api/workbench/conversation-groups/'+(group?'rename':'create'),{group_id:group?.id,name:input.value.trim()});if(!group)groupView=result.group_id;dialog.close();render();}
    catch(exc){error.textContent=exc.message;}finally{save.disabled=false;}
  };
  const controls=node('div',{class:'conv-dialog-actions'},cancel,save);
  if(group)controls.prepend(button('删除分组',async()=>{
    if(!confirm('删除「'+group.name+'」？其中对话将移到“默认分组”，组内置顶会清除，不会删除对话。'))return;
    try{await groupMutation('/api/workbench/conversation-groups/delete',{group_id:group.id});groupView='ungrouped';dialog.close();render();}
    catch(exc){error.textContent=exc.message;}
  },{class:'danger'}));
  form.append(controls);dialog.append(form);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();input.focus();
}
$('conversation-group-new')?.addEventListener('click',()=>groupDialog());
$('conversation-group-edit')?.addEventListener('click',()=>{
  if(groupView==='all'){notify('请先选择一个分组');return;}
  groupDialog(groups().find(item=>item.id===groupView));
});
function start() { authenticated = true; render(); refresh(); }
window.addEventListener('xgent-authenticated', start);
window.addEventListener('xgent-auth-expired', () => {
  knownRuns.clear();completedRuns.clear();completionTimers.forEach(clearTimeout);completionTimers.clear();$('conversation-completions').replaceChildren();
  enteredArchives.clear();try{sessionStorage.removeItem('xgent-entered-archives');}catch{}
  globalResults.reset();
  authenticated = false; authEpoch++; controllers.forEach(controller => controller.abort()); request = null;
  setDrawer(false, false); closeMenu(false); renameDialog.close();
  clearTimeout(feedbackTimer); $('conversation-feedback').hidden = true;
  $('conversation-feedback').replaceChildren();
  $('conversation-rename-input').value = '';
  $('conversation-sync-error').hidden = true;
  state = {current_chat_id: null, revision: -1, items: [], running: null};
  localCurrent = locationParams().has('message') ? null : locationParams().get('conversation');
  listReady=false;
  rows.clear(); itemIndex.clear(); listSignature = ''; search.value = '';
  list.replaceChildren(); render();
});
api('/api/session').then(data => { if (data.authenticated) start(); }).catch(() => {});
setInterval(() => { if (authenticated && !document.hidden) refresh(); }, 3000);
document.addEventListener('visibilitychange', () => { if (authenticated && !document.hidden) refresh(); });

function syncConversationToggle(){
  sidebar.inert=mobile.matches&&!drawerOpen;
  if(mobile.matches&&!drawerOpen)sidebar.setAttribute('aria-hidden','true');else sidebar.removeAttribute('aria-hidden');
  const expanded=!document.body.classList.contains('conv-sidebar-collapsed'),toggle=$('conversation-drawer-toggle');
  toggle.setAttribute('aria-expanded',String(expanded));toggle.title=expanded?'收起对话列表':'展开对话列表';
  toggle.querySelector('use').setAttribute('href',expanded?'#i-sidebar-hide':'#i-sidebar-show');
  $('conversation-mobile-toggle').setAttribute('aria-expanded',String(drawerOpen));
}
try{document.body.classList.toggle('conv-sidebar-collapsed',localStorage.getItem('xgent-conversation-sidebar-collapsed')==='1');}catch{}
syncConversationToggle();
mobile.addEventListener('change',syncConversationToggle);
