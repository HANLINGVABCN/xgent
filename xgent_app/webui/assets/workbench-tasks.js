/* Task views. Existing task service calls and fields are preserved. */
import {$,el,button,fmt,stamp,bytes,message,empty,field,select,check,table,formData,api,wb,download,query,tag,copyText,requestId,safeLocalUrl,inlineState} from './components.js';
import {heading,card,toolbar,actions} from './ui.js';
export function createViews(context) {
const {state,filter,render,selectFilter,searchFilter,sourceLink,filePagination,outputViewer,showError,detail,closeDetail,confirmAction,dialog,closeDialog,submit,dirtyForm,errorOr,refreshBootstrap,chatControls,localFilters,managementModule,taskSourceSearch}=context;
const activeTask=t=>!['completed','failed','cancelled'].includes(t.status);
const triggerLabel=t=>t.condition_expr?'条件触发':({cron:'Cron 定时',once:'单次执行',immediate:'立即执行'}[t.schedule_type]||t.schedule_type||'—');
function taskStamp(value,zone){
  if(!value)return '—';
  try{return new Date(value*1000).toLocaleString('zh-CN',{timeZone:zone||'Asia/Shanghai',hour12:false});}
  catch{return stamp(value);}
}
function taskNext(t){
  if(!activeTask(t))return '已结束';
  if(t.status==='running')return '正在执行';
  if(t.status==='waiting_delivery')return '等待 Agent 接收结果';
  return t.next_run_at?taskStamp(t.next_run_at,t.timezone):'等待调度';
}
function duration(seconds){
  const n=Math.max(0,Math.floor(Number(seconds)||0));
  return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(value=>String(value).padStart(2,'0')).join(':');
}
function taskTime(t){
  if(!t.started_at)return el('span',{class:'wb-note'},'尚未执行');
  if(t.finished_at)return el('span',{class:'wb-task-time'},'结束时间：'+taskStamp(t.finished_at,t.timezone)+' · 总用时：'+duration(t.duration_seconds));
  const node=el('span',{class:'wb-task-time','data-task-start':t.started_at},'已进行 '+duration(Date.now()/1000-t.started_at));
  return node;
}
setInterval(()=>{
  if(document.hidden)return;
  document.querySelectorAll('[data-task-start]').forEach(node=>{node.textContent='已进行 '+duration(Date.now()/1000-Number(node.dataset.taskStart));});
},1000);
function cancelTasks(ids,after){
  confirmAction('取消任务',`将取消 ${ids.length} 个任务，停止后续调度并终止正在运行的命令。Telegram、网页和 CLI 共享的任务都会受影响；保留已有运行记录。`,
    ()=>wb('tasks/cancel',{data:{ids,confirm:true}}),null,after);
}
async function taskPage(read){
  const status=filter('status')||'',q=filter('q')||'',kind=filter('trigger')||'',source=filter('source')||'';
  const data=await read('tasks'+query({status,q,kind,source_conversation_id:source,offset:filter('offset')||0}));
  const page=el('div',{class:'wb-task-page'},heading('任务中心','管理 Trigger 的计划、条件与执行结果；所有通道共享同一份任务。',
    [button('创建任务',()=>taskForm(data.timezone,data.sources),'primary')]));
  const counts=data.counts||{},stats=el('div',{class:'wb-task-stats'});
  for(const [label,value] of [['待执行',(counts.scheduled||0)+(counts.pending||0)],['运行 / 待通知',(counts.running||0)+(counts.waiting_delivery||0)],['已完成',counts.completed||0],['失败',counts.failed||0]])
    stats.append(el('div',{},el('span',{},label),el('strong',{},fmt(value))));
  page.append(stats);
  const selected=new Set(),boxes=[];
  const selection=el('span',{class:'wb-note',role:'status'},'仅可选择未结束的任务');
  const cancel=button('取消选中',()=>cancelTasks([...selected]),'danger');cancel.disabled=true;
  const all=el('input',{type:'checkbox','aria-label':'选择本页全部未结束任务'});
  const updateSelection=()=>{cancel.disabled=!selected.size;all.checked=!!boxes.length&&selected.size===boxes.length;all.indeterminate=selected.size>0&&selected.size<boxes.length;selection.textContent=selected.size?`已选 ${selected.size} 项`:'仅可选择未结束的任务';};
  all.onchange=()=>{for(const [box,id] of boxes){box.checked=all.checked;all.checked?selected.add(id):selected.delete(id);}updateSelection();};
  const change=()=>{filter('offset',0);render();};
  const statusSelect=selectFilter('status',[{value:'',label:'全部状态'},...['scheduled','pending','running','waiting_delivery','completed','failed','cancelled'].map(v=>({value:v,label:tag(v).textContent}))],'',change);
  const kindSelect=selectFilter('trigger',[{value:'',label:'全部触发方式'},{value:'once',label:'单次执行'},{value:'cron',label:'Cron 定时'},{value:'condition',label:'条件触发'},{value:'immediate',label:'立即执行'}],'',change);
  const sourceSelect=selectFilter('source',[{value:'',label:'全部来源对话'},...(data.sources||[]).map(c=>({value:c.id,label:(c.name||'新对话')+' · '+c.id.slice(0,6)+(c.archived?'（已归档）':'')}))],'',change);
   sourceSelect.setAttribute('aria-label','任务来源对话');
   const sourceSearch=button('',()=>taskSourceSearch());sourceSearch.classList.add('wb-source-search');sourceSearch.setAttribute('aria-label','搜索对话记录');sourceSearch.title='搜索对话名称或历史内容';sourceSearch.innerHTML='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-search"/></svg>';
   page.append(toolbar(searchFilter('搜索任务名称、命令或 ID',change),el('div',{class:'wb-source-picker'},sourceSelect,sourceSearch),statusSelect,kindSelect,button('清除筛选',()=>{for(const key of ['q','source','status','trigger'])filter(key,'');change();}),button('刷新',()=>render())));
  page.append(el('div',{class:'wb-selection-bar'},el('label',{class:'wb-check'},all,'全选本页'),selection,cancel));
  all.disabled=!data.items.some(activeTask);
  if(!data.items.length){
    page.append(status||q||kind||source?empty('没有匹配的任务','试试其他状态、触发方式或关键词。',button('清除筛选',()=>{for(const k of ['status','q','trigger','source'])filter(k,'');filter('offset',0);render();})):
      empty('暂时没有任务','支持延时、指定时间、Cron 和输出条件触发。查看本页不会执行命令。',button('创建第一个任务',()=>taskForm(data.timezone,data.sources),'primary')));
  }else{
    const labels=['选择','任务','命令','触发规则','状态','执行时间 / 下次执行','执行次数','操作'];
    const list=table(labels,data.items.map(t=>{
      const box=el('input',{type:'checkbox',disabled:!activeTask(t),'aria-label':'选择 '+(t.summary||t.id),onchange:e=>{e.target.checked?selected.add(t.id):selected.delete(t.id);updateSelection();}});
      if(activeTask(t))boxes.push([box,t.id]);
      const title=el('div',{class:'wb-task-title'},el('button',{class:'link',type:'button',onclick:()=>taskDetail(t.id)},t.summary||t.id),el('div',{class:'wb-task-source'},'对话来源：',sourceLink(t.source)));
      const rule=el('div',{},el('strong',{},triggerLabel(t)),el('small',{class:'wb-task-rule',title:t.schedule_expr||''},t.schedule_expr||(t.condition_expr?'命令启动后监控输出':'立即执行，无时间计划')),t.condition_expr?el('small',{class:'wb-task-rule',title:t.condition_expr},'条件：'+t.condition_expr):null,t.repeat?el('small',{},'命中后重复监控'):null);
      return [el('label',{class:'wb-task-select'},box),title,el('code',{class:'wb-task-command',title:t.command},t.command),rule,tag(t.status),el('div',{},taskTime(t),el('small',{},taskNext(t)),activeTask(t)?el('small',{},t.timezone):null),
        el('div',{},fmt(t.fire_count),t.failure_count?el('small',{class:'wb-danger-text'},`失败 ${fmt(t.failure_count)} 次`):null),
        actions(button('详情',()=>taskDetail(t.id)),activeTask(t)?button('取消',()=>cancelTasks([t.id]),'danger'):null)];
    }));
    list.classList.add('wb-task-table');
    for(const row of list.querySelectorAll('tbody tr'))[...row.children].forEach((cell,i)=>cell.dataset.label=labels[i]);
    page.append(list);
  }
  const offset=data.offset||0;
  const previous=button('上一页',()=>{filter('offset',Math.max(0,offset-50));render();});previous.disabled=!offset;
  const next=button('下一页',()=>{filter('offset',data.next_offset);render();});next.disabled=data.next_offset===null;
  page.append(el('div',{class:'wb-pagination'},el('span',{class:'wb-note'},data.total?`共 ${fmt(data.total)} 项 · 当前 ${offset+1}–${offset+data.items.length}`:'共 0 项'),actions(previous,next)));
  return page;
}
function taskForm(timezone,sources=[]) {
  const zone=timezone||'Asia/Shanghai',drafts={};let currentMode;
  const target=window.XGentConversations?.current;
  const targetName=document.getElementById('wb-conversation-title')?.textContent||target;
  const available=sources.filter(item=>!item.archived&&!item.deleting);
  const defaultTarget=available.find(item=>item.id===state.boot?.conversations?.current_chat_id)?.id||available[0]?.id||'';
  const origin=target?el('p',{class:'wb-note'},'任务来源：'+targetName+' · '+target.slice(0,6)):
    select('任务来源对话','conversation_id',available.length?available.map(item=>({value:item.id,label:(item.name||'新对话')+' · '+item.id.slice(0,6)})):[{value:'',label:'还没有可用的已保存对话'}],defaultTarget);
  const form=el('form',{},origin,!target?el('p',{class:'wb-note'},available.length?'选择接收任务结果的已保存对话。':'先发送一条消息保存对话，即可在这里为它创建任务。'):null,field('任务名称','task','','text','描述任务目的，便于查看执行记录'),
    field('执行命令','command','','textarea','使用服务运行账号执行；不会提供沙箱隔离。'),
    select('触发方式','mode',[{value:'after',label:'延时执行'},{value:'at',label:'指定时间'},{value:'cron',label:'Cron 定时'},{value:'when',label:'输出条件触发'}],'after'));
  const schedule=el('div'),summary=el('div',{class:'wb-callout','aria-live':'polite'});
  const configuration={after:{label:'等待时间',value:'30s',hint:'支持 30s、5m、2h、1d 等格式。',presets:[['30 秒','30s'],['5 分钟','5m'],['1 小时','1h']]},
    at:{label:'执行时间',type:'datetime-local',hint:'按指定时区解释，不使用浏览器本地时区。'},
    cron:{label:'Cron 表达式',value:'0 9 * * *',hint:'五个字段：分 时 日 月 周；周建议用 mon–sun（数字 0 为周一）。',presets:[['每小时','0 * * * *'],['每天 09:00','0 9 * * *'],['工作日 09:00','0 9 * * mon-fri']]},
    when:{label:'触发条件',value:'READY',hint:'命令启动后持续监控输出；匹配条件时通知 Agent。'}};
  function updateSummary(){
    const mode=form.elements.mode.value,value=form.elements.expression?.value||'未填写';
    summary.replaceChildren(el('strong',{},'创建后会发生什么'),el('p',{},mode==='when'?'立即启动命令并等待输出匹配。':'交由服务器调度器按计划执行。'),
      el('p',{},`${configuration[mode].label}：${value} · 时区：${form.elements.timezone.value||zone}`),
      el('small',{},'仅确认创建才会登记任务。查看预览和切换触发方式不会执行命令。'));
  }
  function scheduleForm(){
    if(currentMode)drafts[currentMode]={expression:form.elements.expression.value,repeat:!!form.elements.repeat?.checked};
    const mode=form.elements.mode.value,c=configuration[mode],draft=drafts[mode];currentMode=mode;
    schedule.replaceChildren(field(c.label,'expression',draft?.expression??c.value??'',c.type||'text',c.hint));
    form.elements.expression.required=true;
    if(c.presets)schedule.append(el('div',{class:'wb-presets'},c.presets.map(([label,value])=>button(label,()=>{form.elements.expression.value=value;form.elements.expression.dispatchEvent(new Event('input',{bubbles:true}));}))));
    if(mode==='when')schedule.append(check('条件命中后重复监控','repeat',draft?.repeat));
    updateSummary();
  }
  form.elements.mode.onchange=scheduleForm;
  form.append(schedule,field('时区','timezone',zone,'text','所有计划按此时区执行，例如 Asia/Shanghai。'),summary);scheduleForm();
  let id=requestId();form.addEventListener('input',()=>{id=requestId();updateSummary();});form.addEventListener('change',()=>{id=requestId();updateSummary();});
  form.elements.task.required=true;form.elements.command.required=true;form.elements.timezone.required=true;
  if(!target)form.elements.conversation_id.required=true;
  form.append(actions(button('取消',closeDialog),el('button',{class:'wb-btn primary',type:'submit'},'确认创建任务')));dirtyForm(form);
  form.querySelector('[type=submit]').disabled=!target&&!available.length;
  form.onsubmit=e=>{e.preventDefault();submit(form,async d=>{
    if(!d.task.trim()||!d.command.trim())throw new Error('请填写任务名称和执行命令');
    if(!d.expression)throw new Error('请填写触发时间或条件');
    const expression=d.mode==='at'?d.expression.replace('T',' '):d.expression;
    await wb('tasks/create',{data:{conversation_id:target||d.conversation_id,request_id:id,task:d.task,command:d.command,timezone:d.timezone,
      [d.mode]:expression,...(d.mode==='when'?{repeat:!!d.repeat}:{})}});
    state.dirty=false;closeDialog();for(const key of ['status','q','trigger','source'])filter(key,'');filter('offset',0);await render();
  });};dialog('创建后台任务',form);
}

async function taskDetail(id){
  const box=el('div',{},message('读取任务详情…','loading'));detail('任务详情',box);
  const signal=state.detailRequest.signal;
  try{
    const data=await wb('tasks'+query({id}),{signal}),t=data.task;
    const showRun=r=>card(taskStamp(r.started_at||r.created_at,t.timezone),sourceLink(r.source),tag(r.status),taskTime({...r,timezone:t.timezone}),el('p',{class:'wb-note'},'退出码 '+(r.exit_code??'—')),
      r.error?message(r.error):null,r.output_path?button('查看完整输出',()=>outputViewer(r.output_path,'任务输出',()=>taskDetail(id))):el('pre',{class:'wb-pre'},r.output||'暂无输出'));
    box.replaceChildren(el('h2',{class:'wb-detail-filename'},t.summary||id),el('div',{class:'wb-task-source'},'对话来源：',sourceLink(t.source)),taskTime(t),actions(tag(t.status),button('刷新状态',()=>taskDetail(id))),
      el('dl',{},[['任务 ID',t.id],['来源对话',sourceLink(t.source)],['触发方式',triggerLabel(t)],['计划',t.schedule_expr],['输出条件',t.condition_expr],['重复监控',t.repeat?'是':'否'],['时区',t.timezone],
        ['下次执行',taskNext(t)],['创建时间',taskStamp(t.created_at,t.timezone)],['执行 / 失败',`${fmt(t.fire_count)} / ${fmt(t.failure_count||0)}`]]
        .filter(([k,v])=>v!=null&&v!=='').map(([k,v])=>el('div',{class:'wb-detail-row'},el('dt',{},k),el('dd',{},v)))),
      el('h3',{class:'wb-section-title'},'执行命令'),el('pre',{class:'wb-pre wb-output-text'},t.command),button('复制命令',errorOr(box,async()=>{await copyText(t.command);inlineState(box,'命令已复制');})));
    if(t.last_error)box.append(message(t.last_error));
    if(activeTask(t))box.append(button('取消任务',()=>cancelTasks([id],async()=>{await render();if(!signal.aborted)await taskDetail(id);}),'danger'));
    const runs=el('div',{class:'wb-run-list'});
    box.append(el('h3',{class:'wb-section-title'},'运行记录'),runs);
    for(const r of data.runs)runs.append(showRun(r));
    if(!data.runs.length)runs.append(empty('还没有运行记录','任务执行后，结果和输出会保存在这里。'));
    if(data.next_cursor){
      let cursor=data.next_cursor;
      const more=button('更早运行记录',async()=>{more.disabled=true;try{
        const older=await wb('tasks'+query({id,before:cursor}),{signal});
        for(const r of older.runs)runs.append(showRun(r));
        cursor=older.next_cursor;if(!cursor)more.remove();
      }catch(e){showError(box,e);}finally{more.disabled=false;}});box.append(more);
    }
  }catch(e){if(e.name!=='AbortError')box.replaceChildren(message(e.message),button('重试读取',()=>taskDetail(id)));}
}



return {taskPage,taskForm,taskDetail};
}
