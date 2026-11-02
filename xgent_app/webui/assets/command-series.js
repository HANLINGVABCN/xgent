// Fold only completed runs of command-only replies. Original message nodes stay in place.
export function installCommandSeries(log, {conversation, currentRun}) {
  const controls=new Map(),completed=new Set();
  const commandCounts=new WeakMap();
  let queued=false,positionQueued=false;
  let pointer=null;
  const touchControls=window.matchMedia('(hover: none) and (pointer: coarse)');
  const measuredRows=new Set();
  const resizeObserver=new ResizeObserver(position);
  resizeObserver.observe(log);
  let preferences={};
  try{preferences=JSON.parse(sessionStorage.getItem('xgent-command-series')||'{}');}catch{}
  const entry=row=>row._chatEntry;
  const owner=row=>(row.dataset.presentationConversationId||conversation()||'global_memory')+':'+
    (row.dataset.replyGroupId||row.dataset.runId||row.dataset.turnId||'legacy');
  const rows=()=>Array.from(log.children).filter(node=>node.classList.contains('msg-row'));
  const commands=row=>{
    const value=entry(row),segments=value?.webDisplay?.segments;
    if(value?.messageType!=='ai_reply'||!Array.isArray(segments))return 0;
    const cached=commandCounts.get(value);if(cached?.display===value.webDisplay)return cached.count;
    let count=0;
    for(const part of segments){
      if(part.footer||part.terminal_notice)continue;
      if(!part.text?.trim())continue;
      if(part.kind==='markdown')return 0;
      if(part.kind!=='html')return 0;
      const parsed=document.createElement('template');parsed.innerHTML=part.text;
      const blocks=parsed.content.querySelectorAll('blockquote[data-protocol]');
      if(!blocks.length)return 0;
      // An HTML segment can contain prose beside a command card. Finding a
      // command is insufficient: only command-only replies may join a series.
      blocks.forEach(block=>block.remove());
      if(parsed.content.textContent.trim()||parsed.content.querySelector('img,video,audio,pre,code,table,button,input,hr'))return 0;
      count+=blocks.length;
    }
    commandCounts.set(value,{display:value.webDisplay,count});return count;
  };
  function save(key,collapsed){
    preferences[key]=collapsed;
    const keys=Object.keys(preferences);for(const old of keys.slice(0,Math.max(0,keys.length-200)))delete preferences[old];
    try{sessionStorage.setItem('xgent-command-series',JSON.stringify(preferences));}catch{}
  }
  function setCollapsed(control,collapsed){
    control.collapsed=collapsed;
    control.button.hidden=!collapsed;
    if(collapsed)control.close.hidden=true;
    control.button.setAttribute('aria-expanded',String(!collapsed));
    control.node.classList.toggle('series-open',!collapsed);
    for(const row of control.members){
      row.classList.toggle('command-series-anchor',row===control.members[0]);
      row.classList.toggle('command-series-collapsed',collapsed);
    }
    position();
  }
  function position(){
    if(positionQueued)return;positionQueued=true;
    requestAnimationFrame(()=>{
      positionQueued=false;
      const viewport=log.getBoundingClientRect();
      const right=viewport.left+log.clientLeft+log.clientWidth;
      for(const control of controls.values()){
        if(control.collapsed||!control.node.isConnected||!log.getClientRects().length){control.close.hidden=true;continue;}
        const origin=control.node.getBoundingClientRect().top;
        const bottom=control.members.at(-1)?.getBoundingClientRect().bottom??origin;
        const left=entry(control.members[0])?.bubble.getBoundingClientRect().left??viewport.left;
        const top=Math.max(origin,viewport.top+6),end=Math.min(bottom,viewport.bottom-6);
        const hovered=pointer&&pointer.x>=left&&pointer.x<=right&&pointer.y>=top&&pointer.y<=end;
        const focused=document.activeElement?.matches(':focus-visible')&&
          (document.activeElement===control.close||control.members.some(row=>row.contains(document.activeElement)));
        if(end-top<28||!touchControls.matches&&!hovered&&!focused){control.close.hidden=true;continue;}
        control.close.hidden=false;
        const width=control.close.offsetWidth,height=control.close.offsetHeight;
        control.close.style.left=Math.max(viewport.left+4,right-width-8)+'px';
        control.close.style.top=Math.round(top+(end-top-height)/2)+'px';
      }
    });
  }
  log.addEventListener('scroll',position,{passive:true});window.addEventListener('resize',position);
  document.addEventListener('pointermove',event=>{if(event.pointerType!=='touch'){pointer={x:event.clientX,y:event.clientY};position();}},{passive:true});
  document.addEventListener('pointerout',event=>{if(!event.relatedTarget){pointer=null;position();}},{passive:true});
  document.addEventListener('focusin',position);document.addEventListener('focusout',position);
  window.addEventListener('blur',()=>{pointer=null;position();});
  window.addEventListener('xgent-conversation-changed',()=>{pointer=null;position();});
  touchControls.addEventListener('change',position);
  function stopNotices(messages){
    const byRun=new Map();
    for(const row of messages){
      row.classList.remove('duplicate-stop-notice');
      row.querySelectorAll('.stop-notice').forEach(node=>node.hidden=false);
      const info=entry(row)?.webDisplay?.terminal_notice;
      if(info?.state!=='stopped')continue;
      if(!row.dataset.runId&&!row.dataset.replyGroupId)continue;
      const key=(row.dataset.presentationConversationId||conversation())+':'+(row.dataset.runId||row.dataset.replyGroupId);
      if(!byRun.has(key))byRun.set(key,[]);byRun.get(key).push(row);
    }
    for(const group of byRun.values()){
      const canonical=group.filter(row=>entry(row).webDisplay.terminal_notice.only).at(-1)||group[0];
      for(const row of group){
        if(row===canonical)continue;
        if(entry(row).webDisplay.terminal_notice.only)row.classList.add('duplicate-stop-notice');
        else row.querySelectorAll('.stop-notice').forEach(node=>node.hidden=true);
      }
    }
  }
  function repaint(){
    queued=false;
    const messages=rows();stopNotices(messages);
    const ended=new Set(completed),waiting=new Set(),summaries=new Map();
    for(const row of messages){
      const value=entry(row),key=owner(row);
      if(value?.replyComplete===true&&value?.loadedFromHistory)ended.add(key);
      if(value?.askState?.snapshot?.status==='pending')waiting.add(key);
      if(value?.executionSummary)summaries.set(key,value.executionSummary.items||[]);
    }
    const sequences=[];let sequence=null;
    function finish(){if(sequence&&sequence.replies.length>1)sequences.push(sequence);sequence=null;}
    for(const row of messages){
      if(row.classList.contains('presentation-hidden'))continue;
      const value=entry(row),key=owner(row),count=commands(row);
      const boundary=value?.askState||value?.ui||value?.messageType==='ui_message'||value?.messagePolicy?.purpose==='menu'||
        value?.messageType==='runtime_error'||row.querySelector('.has-media')||
        value?.webDisplay?.terminal_notice?.only||row.classList.contains('user');
      if(boundary){finish();continue;}
      if(count){
        if(sequence&&sequence.owner!==key)finish();
        if(!sequence)sequence={owner:key,members:[],replies:[],count:0};
        sequence.members.push(row);sequence.replies.push(row);sequence.count+=count;
      }else if(sequence&&(row.classList.contains('cmd')||row.classList.contains('sys')||row.classList.contains('token'))&&
          (key===sequence.owner||!row.dataset.replyGroupId&&!row.dataset.runId))sequence.members.push(row);
      else finish();
    }
    finish();const retained=new Set();
    for(const group of sequences){
      const running=currentRun();
      const isCurrent=running&&group.members.some(row=>row.dataset.runId===running.run_id);
      if(!ended.has(group.owner)||waiting.has(group.owner)||isCurrent&&!completed.has(group.owner))continue;
      const first=group.replies[0];
      const key=group.owner+':'+(first.dataset.recordId||first.dataset.runId||first.dataset.turnId||group.replies.indexOf(first));
      retained.add(key);
      let control=controls.get(key);
      if(!control){
        const node=document.createElement('div');node.className='command-series-control';
        const button=document.createElement('button');button.type='button';button.className='command-series-toggle';
        const arrow=document.createElement('span');arrow.textContent='▸';arrow.setAttribute('aria-hidden','true');
        const label=document.createElement('em');button.append(arrow,label);
        const close=document.createElement('button');close.type='button';close.className='command-series-close';close.textContent='收起';
        close.hidden=true;close.title='收起这段命令';close.setAttribute('aria-label','收起这段命令');node.append(button);document.body.append(close);
        control={node,button,label,close,members:[],collapsed:preferences[key]!==false};controls.set(key,control);
        button.onclick=event=>{
          save(key,false);setCollapsed(control,false);
          if(event.detail===0&&!touchControls.matches){control.close.hidden=false;control.close.focus({preventScroll:true});}
        };
        close.onclick=()=>{save(key,true);setCollapsed(control,true);control.button.focus();};
      }
      for(const old of control.members)if(!group.members.includes(old))old.classList.remove('command-series-collapsed','command-series-anchor');
      control.members=group.members;
      const bubble=entry(first).bubble,head=entry(first).head;
      const before=head?head.nextSibling:bubble.firstChild;
      if(before!==control.node)bubble.insertBefore(control.node,before);
      const ids=new Set(group.replies.map(row=>String(row.dataset.recordId)));
      const summary=summaries.get(group.owner);
      const operations=summary?.filter(item=>ids.has(String(item.reply_record_id)));
      const fallback=group.replies.flatMap(row=>entry(row)?.executionMetrics?.operations||[]);
      const unique=new Map((operations||fallback).map(item=>[item.sequence,item]));
      const count=summary?unique.size:unique.size||group.count;
      const response=group.replies.map(row=>entry(row)?.executionMetrics?.response_seconds);
      const times=[...response,...Array.from(unique.values(),item=>item.elapsed_seconds)];
      const duration=times.every(value=>typeof value==='number'&&Number.isFinite(value)&&value>=0)?times.reduce((a,b)=>a+b,0):null;
      const time=duration==null?'总耗时未记录':'总耗时约 '+(duration<10?duration.toFixed(1):Math.round(duration))+' 秒';
      control.label.textContent='共执行 '+group.replies.length+' 轮，'+count+' 个操作 · '+time;
      control.button.setAttribute('aria-label',control.label.textContent+'，点击展开');
      setCollapsed(control,control.collapsed);
    }
    for(const [key,control] of controls)if(!retained.has(key)){
      control.members.forEach(row=>row.classList.remove('command-series-collapsed','command-series-anchor'));
      control.node.remove();control.close.remove();controls.delete(key);
    }
    const members=new Set(Array.from(controls.values()).flatMap(control=>control.members));
    for(const row of measuredRows)if(!members.has(row)){resizeObserver.unobserve(row);measuredRows.delete(row);}
    for(const row of members)if(!measuredRows.has(row)){resizeObserver.observe(row);measuredRows.add(row);}
    position();
  }
  function changed(){if(!queued){queued=true;queueMicrotask(repaint);}}
  function finished(frame){
    if(frame.reply_group_id&&frame.reply_complete===true){
      completed.add((frame.conversation_id||conversation()||'global_memory')+':'+frame.reply_group_id);
      if(completed.size>1000)completed.delete(completed.values().next().value);
    }
    changed();
  }
  new MutationObserver(changed).observe(log,{childList:true});
  return {changed,finished};
}
