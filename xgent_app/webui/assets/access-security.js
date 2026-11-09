import {el,button,field,select,check,api,message,stamp} from './components.js';
const endpoint='/api/security/access';
export async function accessSecurityCards({card,dialog,closeDialog,submit}){
  let data=await api(endpoint);
  const visits=el('div'),sessions=el('div'),rules=el('div'),policy=el('div');
  const panels=[card('近期访问与封禁',visits),card('已登录设备',sessions),card('IP 黑名单与白名单',rules),card('访问保护规则',policy)];
  panels.forEach(p=>p.classList.add('wb-access-panel'));
  const controls=(...items)=>el('div',{class:'wb-actions'},items);
  async function refresh(){data=await api(endpoint);draw();}
  async function change(action,values){await api(endpoint+'/'+action,{data:{...values,confirm:true}});await refresh();}
  function safe(action,values,text){return button(text,async()=>{if(!confirm('确认'+text+'？'))return;try{await change(action,values);}catch(e){visits.append(message(e.message));}},action==='block'||action==='revoke'?'danger':'');}
  function clientRow(c){
    const banned=c.blocked,wait=Math.max(0,Math.ceil(c.wait_until-Date.now()/1000));
    return el('div',{class:'wb-access-row'},el('div',{},el('strong',{},c.kind==='ip'?c.id:'设备 '+c.id.slice(0,10)),
      el('p',{class:'wb-note'},'访问 '+c.visits+' 次 · 错误 '+c.failures+' 次 · '+(banned?'已封禁':wait?'等待 '+wait+' 秒':'正常')),
      el('p',{class:'wb-note'},'最近访问 '+stamp(c.last_seen)+' · '+c.last_ip)),
      controls(button('详情',()=>showClient(c)),safe(banned?'unblock':'block',banned?{[c.kind]:c.id}:{kind:c.kind,id:c.id},banned?'解除封禁':'封禁')));
  }
  function showClient(c){dialog(c.kind==='ip'?'IP 访问详情':'设备访问详情',el('dl',{class:'wb-access-details'},
    ...[['标识',c.id],['来源 IP',c.last_ip],['首次访问',stamp(c.first_seen)],['最近访问',stamp(c.last_seen)],['访问次数',c.visits],['认证失败次数',c.failures],['连续失败次数',c.streak],['状态',c.blocked?'已封禁':'正常'],['原因',c.reason||'—'],['浏览器信息',c.agent||'未提供']].map(([k,v])=>el('div',{class:'wb-detail-row'},el('dt',{},k),el('dd',{},String(v))))));}
  function deviceDetails(s){dialog('已登录设备详情',el('dl',{class:'wb-access-details'},
    ...[['设备',s.device],['IP',s.ip],['登录时间',stamp(s.created_at)],['最近活动',stamp(s.last_seen)],['当前到期时间',stamp(s.expires_at)],['自动续期',data.policy.session_auto_renew?'使用中自动延长':'已关闭'],['浏览器信息',s.agent||'未提供']].map(([k,v])=>el('div',{class:'wb-detail-row'},el('dt',{},k),el('dd',{},String(v))))));}
  function draw(){
    const recent=el('div');const filter=select('显示范围','scope',['近期 IP','已封禁 IP','已封禁设备'],'近期 IP');let shown=50;
    function drawVisits(){const choice=filter.querySelector('select').value;const clients=data.clients.filter(c=>choice==='近期 IP'?c.kind==='ip':choice==='已封禁 IP'?c.kind==='ip'&&c.blocked:c.kind==='device'&&c.blocked);
      recent.replaceChildren(...clients.slice(0,shown).map(clientRow));
      if(clients.length>shown)recent.append(button('显示更多记录',()=>{shown+=50;drawVisits();}));
      if(!recent.childElementCount)recent.append(el('p',{class:'wb-note'},'暂无记录'));}
    filter.onchange=()=>{shown=50;drawVisits();};
    visits.replaceChildren(controls(filter,button('刷新访问记录',refresh)),recent);drawVisits();
    const days=field('登录有效期（天）','session_days',data.policy.session_days,'number');
    const daysInput=days.querySelector('input');daysInput.min='1';daysInput.max='365';daysInput.step='1';daysInput.required=true;
    const renew=check('使用中自动延长登录','session_auto_renew',data.policy.session_auto_renew);
    const sessionSummary=el('p',{class:'wb-note wb-session-policy-summary',role:'status'});
    const sessionForm=el('form',{class:'wb-session-policy'},days,renew,sessionSummary,
      el('button',{type:'submit',class:'wb-btn primary'},'保存登录设置'));
    function describeSession(){const count=Number(daysInput.value),active=sessionForm.elements.session_auto_renew.checked;
      sessionSummary.textContent=Number.isInteger(count)&&count>=1&&count<=365?
        (active?`正常使用会自动续期，连续 ${count} 天未使用才需要重新登录。`:`自动续期已关闭，登录凭据有效期为 ${count} 天。`)+
        ' 踢出设备、修改密码或两步验证、封禁仍立即撤销登录。修改后保存生效。':'请输入 1–365 的整数天数。';}
    sessionForm.addEventListener('input',describeSession);sessionForm.addEventListener('change',describeSession);describeSession();
    sessionForm.onsubmit=e=>{e.preventDefault();submit(sessionForm,async values=>{
      await change('policy',{session_days:Number(values.session_days),session_auto_renew:values.session_auto_renew});});};
    sessions.replaceChildren(sessionForm,el('p',{class:'wb-note'},'已登录 '+data.sessions.length+' 个设备。踢下线后需要重新登录；清除浏览器数据可能创建新的设备记录。'),
      controls(button('刷新设备',refresh),safe('revoke_others',{},'踢出其他设备')),
      ...data.sessions.map(s=>el('div',{class:'wb-access-row'},el('div',{},el('strong',{},(s.current?'当前设备 · ':'')+s.device.slice(0,10)),
        el('p',{class:'wb-note'},s.ip+' · 最近活动 '+stamp(s.last_seen)),
        el('p',{class:'wb-note'},'当前到期 '+stamp(s.expires_at)),el('p',{class:'wb-note'},s.agent||'浏览器信息未提供')),
        controls(button('详情',()=>deviceDetails(s)),safe('revoke',{id:s.id},s.current?'退出此设备':'踢下线')))));
    rules.replaceChildren(el('p',{class:'wb-note'},'黑名单拒绝访问；白名单仍需密码和两步验证，但不自动累计等待或封禁。已手动封禁的 IP／设备仍需先解除。'),
      controls(button('添加 IP 规则',addRule),button('刷新名单',refresh)),
      ...data.rules.map(r=>el('div',{class:'wb-access-row'},el('div',{},el('strong',{},r.network),el('p',{class:'wb-note'},(r.mode==='black'?'黑名单':'白名单')+(r.note?' · '+r.note:''))),safe('delete_rule',{id:r.id},'删除规则'))));
    const p=data.policy;const description=el('p',{class:'wb-note wb-access-policy-summary',role:'status'});
    const form=el('form',{},check('启用连续失败自动封禁','enabled',p.enabled),
      field('等待触发次数','wait_after',p.wait_after,'number'),field('等待时长（秒）','wait_seconds',p.wait_seconds,'number'),field('直接封禁累计次数','ban_after',p.ban_after,'number'),
      select('反向代理来源 IP','proxy_header',[{value:'none',label:'直接连接：TCP 来源 IP'},{value:'cloudflare',label:'Cloudflare：CF-Connecting-IP'},{value:'real-ip',label:'本机代理：X-Real-IP'}],p.proxy_header),
      description,
      el('button',{type:'submit',class:'wb-btn primary'},'保存访问规则'));
    function describe(){
      const fields=form.elements,wait=Number(fields.wait_after.value),seconds=Number(fields.wait_seconds.value),ban=Number(fields.ban_after.value);
      const valid=[wait,seconds,ban].every(value=>Number.isInteger(value)&&value>0)&&ban>wait;
      const rule=!fields.enabled.checked?'自动等待与封禁已关闭。':valid?
        `连续认证失败 ${wait} 次后等待 ${seconds} 秒，等待结束后再失败 ${ban-wait} 次，封禁 IP 和设备。`:
        '请填写有效次数和时长；封禁累计次数须大于等待触发次数。';
      const origin={'none':'当前使用 TCP 来源 IP。',
        'cloudflare':'当前使用本机 Cloudflare 代理提供的 CF-Connecting-IP。',
        'real-ip':'当前使用本机代理提供的 X-Real-IP。'}[fields.proxy_header.value];
      description.textContent=rule+' '+origin+' 修改后保存生效。';
    }
    form.addEventListener('input',describe);form.addEventListener('change',describe);describe();
    form.onsubmit=e=>{e.preventDefault();submit(form,async values=>{await change('policy',{enabled:values.enabled,wait_after:Number(values.wait_after),wait_seconds:Number(values.wait_seconds),ban_after:Number(values.ban_after),proxy_header:values.proxy_header});});};policy.replaceChildren(form);
  }
  function addRule(){const form=el('form',{},field('IP 或 CIDR 网段','network','','text'),select('名单类型','mode',[{value:'black',label:'黑名单'},{value:'white',label:'白名单'}],'black'),field('备注','note',''),el('button',{type:'submit',class:'wb-btn primary'},'保存 IP 规则'));form.onsubmit=e=>{e.preventDefault();submit(form,async values=>{if(!confirm('确认保存这条 IP 规则？'))return;await change('rule',values);closeDialog();});};dialog('添加 IP 规则',form);}
  draw();return panels;
}
