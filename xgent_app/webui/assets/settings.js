import {el,button,field,select,check,wb,api,message,tag} from './components.js';
import {panelNames} from './navigation.js';
import {readPreference,writePreference} from './ui.js';
import {themePicker} from './theme-settings.js';
import {allowCredentialAutofill} from './input-policy.js';

export async function settingsView({logout,boot,health,state,render,dialog,closeDialog,submit,dirtyForm,confirmAction,refreshBootstrap,setTheme,filter,heading,card,actions,read,localFilters,detail,closeDetail,toolbar,managementModule,sideNav}) {
  const settings=boot.settings;
  const active=filter('section')||'appearance';
  const descriptions={appearance:'品牌、头像、文字与主题。修改后保存生效。',conversation:'对话方式、思考与共享记忆。修改后保存生效。',agent:'工具调用、执行行为与命令规则。修改后保存生效。',web:'网页访问、账户安全与两步验证。修改后保存生效。',data:'备份内容、压缩计划与数据恢复。',health:'查看通道与服务的当前状态。'};
  const page=el('div',{class:'settings-panel','data-setting-section':active},heading(panelNames[active]||'设置',descriptions[active]));
  const grid=el('div',{class:'wb-settings-grid'});
  const epoch=state.authEpoch;
  function lazyCards(title,build){
    page.dataset.deferredPanels='1';
    const placeholder=card(title,message('正在读取…','loading'));if(!title)placeholder.querySelector('h3')?.remove();
    grid.append(placeholder);
    page.deferredPanelsReady=Promise.resolve().then(build).then(cards=>{if(epoch===state.authEpoch)placeholder.replaceWith(...(Array.isArray(cards)?cards:[cards]));})
      .catch(error=>{if(epoch!==state.authEpoch||error.name==='AbortError')return;placeholder.replaceChildren(message(error.message),button('重试',render));});
  }
  if(active==='data'){
    page.classList.add('wb-data-page');grid.classList.add('wb-data-layout');
    lazyCards('数据与备份',async()=>{const {dataBackupCards}=await managementModule('data-backups');return dataBackupCards({page,card,state,dirtyForm});});
    page.append(grid);
    return page;
  }
  if(active==='appearance'){
    lazyCards('',async()=>{const {brandingCard}=await managementModule('branding-settings');if(!window.XGentBranding.state.ready)await window.XGentBranding.refresh();return brandingCard({card,actions,state,submit,dirtyForm});});
    const appearance=card('文字字号',el('p',{},'消息、界面和网页终端字号都在这里调整。预览只影响本页，保存后写入服务端配置并同步到其他网页设备。'));
    const theme=select('明暗模式','theme',[{value:'system',label:'跟随系统'},{value:'light',label:'浅色'},{value:'dark',label:'深色'}],readPreference('xgent-theme','system'));theme.querySelector('select').onchange=e=>setTheme(e.target.value);
    const reduce=check('减少界面动效','reduce',readPreference('xgent-reduce-motion')==='1');reduce.onchange=e=>{writePreference('xgent-reduce-motion',e.target.checked?'1':'0');document.body.classList.toggle('wb-reduce-motion',e.target.checked);};
    const fonts=window.XGentAppearance, fontForm=el('form',{class:'font-settings'});
    const fontKeys=[['web_message_font_size','消息字号'],['web_ui_font_size','界面字号'],['web_terminal_font_size','网页终端字号']];
    for(const [key,label] of fontKeys){const control=field(label+'（px）',key,fonts.state.values[key],'number');const input=control.querySelector('input');[input.min,input.max]=fonts.limits[key];input.step='1';const slider=el('input',{type:'range',min:input.min,max:input.max,step:'1','aria-label':label+'滑块','data-font-key':key});slider.value=input.value;slider.oninput=()=>input.value=slider.value;input.oninput=()=>{if(input.checkValidity())slider.value=input.value;};fontForm.append(el('div',{class:'font-control'},control,slider));}
    const preview=el('div',{class:'font-preview'},'消息预览：中文、English、12345。',el('br'),el('code',{},'代码与表格跟随消息字号。'));
    const feedback=el('div');fontForm.append(preview,feedback,actions(button('恢复默认',()=>{for(const [key] of fontKeys)fontForm.elements[key].value=fonts.defaults[key];fontForm.querySelectorAll('[data-font-key]').forEach(slider=>slider.value=fonts.defaults[slider.dataset.fontKey]);state.dirty=true;fonts.preview(fonts.defaults);}),button('取消预览',()=>{fonts.cancelPreview();for(const [key] of fontKeys)fontForm.elements[key].value=fonts.state.values[key];fontForm.querySelectorAll('[data-font-key]').forEach(slider=>slider.value=fonts.state.values[slider.dataset.fontKey]);state.dirty=false;}),el('button',{class:'wb-btn primary',type:'submit'},'保存字号')));
    dirtyForm(fontForm);fontForm.addEventListener('input',()=>{const values={};for(const [key] of fontKeys){const n=Number(fontForm.elements[key].value),[min,max]=fonts.limits[key];if(Number.isInteger(n)&&n>=min&&n<=max)values[key]=n;}fonts.preview(values);});
    fontForm.onsubmit=e=>{e.preventDefault();submit(fontForm,async d=>{await fonts.save(Object.fromEntries(fontKeys.map(([key])=>[key,Number(d[key])])));feedback.replaceChildren(message('字号已保存，其他网页设备同步生效。','success'));});};
    appearance.append(fontForm);
    const visual=card('界面主题',el('p',{},'六种配色均支持明暗模式，即点即用。主题和头像分别选择。'),themePicker(),theme,reduce,button('重置布局宽度',()=>{writePreference('xgent-detail-width',null);document.documentElement.style.setProperty('--detail-width','440px');}));
    visual.classList.add('theme-settings-card');
    grid.append(visual,appearance,card('快捷操作',el('dl',{},...[['Ctrl / ⌘ K','搜索命令'],['Ctrl / ⌘ F','搜索全部历史'],['Enter','桌面发送消息'],['Shift / Alt + Enter','换行'],['Esc','关闭详情或弹窗']].map(([k,v])=>el('div',{class:'wb-detail-row'},el('dt',{},k),el('dd',{},v)))),el('p',{class:'wb-note'},'触屏 Enter 始终换行。正在生成时仍可编辑草稿。')));
  }
  if(active==='conversation'||active==='agent'){
    const conversation=[['response_mode','网页回复方式','select'],['telegram_response_mode','Bot 回复方式','select'],['thinking_level','思考深度','select'],['text_stitch_mode','文本拼接方式','select'],['global_depth','记忆深度','number'],['stream_timeout','流式超时（秒，0 为自动）','number']];
    const agent=[['agent_mode','Agent 模式','bool'],['agent_call_mode','工具调用方式','select'],['agent_max_iterations','最大迭代次数','number'],['agent_command_timeout','命令等待时间（秒）','number'],['smart_match_threshold','智能匹配阈值','number'],['idle_message_interval','空闲提示间隔（秒）','number']];
    const fields=active==='agent'?agent:conversation;const form=el('form');
    const notes={"response_mode":"网页选择前台流式或非流式，不改变 Bot 设置。","telegram_response_mode":"Bot 独立控制预览；前台限制刷新频率，后台只显示生成进度。限流不拖慢网页。","thinking_level":"选择模型思考深度；不同模型支持范围不同。","text_stitch_mode":"控制连续回复的拼接方式。","global_depth":"参与后续请求的历史深度，不会删除聊天记录。","stream_timeout":"等待模型回复的超时；0 使用自动策略。","agent_mode":"允许 Agent 按现有权限执行工具。","agent_call_mode":"Tool call／正则围栏；切换影响下一次新请求，运行中的回合保持原模式。","agent_max_iterations":"本轮请求允许的最多 Agent 迭代次数。","agent_command_timeout":"命令等待时间，单位为秒。","smart_match_threshold":"命令智能匹配阈值，范围 0–100%。","idle_message_interval":"空闲状态提示的间隔，单位为秒。"};
    const rows=el('div',{class:'wb-setting-rows'});
    for(const [key,label,type] of fields){const control=type==='bool'?check(label,key,settings.values[key]):type==='select'?select(label,key,settings.options[key],settings.values[key]):field(label,key,settings.values[key],type);const row=el('div',{class:'wb-setting-row'},control,el('p',{class:'wb-setting-note'},notes[key]));if(type==='number'){const input=control.querySelector('input');input.min=key==='global_depth'?'1':'0';input.step='1';if(key==='smart_match_threshold')input.max='100';}rows.append(row);}
    form.append(rows);
    const feedback=el('div');form.append(el('p',{class:'wb-note'},'保存后生效。执行中的命令不会因为修改参数而重新启动。'),feedback,el('button',{type:'submit',class:'wb-btn primary'},'保存设置'));dirtyForm(form);
    form.onsubmit=e=>{e.preventDefault();submit(form,async d=>{
      const saved=await wb('settings',{data:{items:fields.map(([key,,type])=>({key,value:type==='number'?Number(d[key]):d[key]}))}});
      if(state.boot&&saved?.values)state.boot={...state.boot,settings:saved};
      feedback.replaceChildren(message('设置已保存','success'));
    });};
    grid.append(card(active==='agent'?'执行行为':'对话行为',form));
    if(active==='conversation'){
      // 「记忆」浏览管理：自「模型与技能」页迁入，与记忆深度等设置同区。
      lazyCards('记忆',async()=>{
        const {knowledgePage}=await managementModule('knowledge');
        const container=el('div',{class:'wb-memories-page wb-memory-embed'});
        const data=await read('memories');
        await knowledgePage(container,data,'memories',{state,filter,localFilters,render,detail,closeDetail,confirmAction,refreshBootstrap,toolbar});
        return [container];
      });
    }
    if(active==='agent') grid.append(card('执行权限说明',el('div',{class:'wb-callout'},el('strong',{},'这不是沙箱'),el('p',{},'Agent 与网页终端拥有运行账号的实际权限。命令黑名单不是安全隔离。请只执行你信任的任务。')),button('管理命令黑名单',()=>blacklistEditor({dialog,submit,dirtyForm}))));
  }
  if(active==='web'){
    const values=boot.web||{};const form=el('form',{},check('启用 Web Chat','web_enabled',values.web_enabled!==false),check('启用网页终端','terminal_enabled',values.terminal_enabled),field('监听端口','web_port',values.web_port||8790,'number','只监听 127.0.0.1，修改端口会使当前连接断开。'),field('公开 HTTPS 地址','web_public_url',values.web_public_url||'','url','用于 Telegram 网页入口；留空使用本地地址。'),el('p',{class:'wb-note'},'关闭 Web Chat 会失去当前管理界面。请确保还能通过 CLI 或 Telegram 重新开启。'),el('button',{class:'wb-btn primary',type:'submit'},'应用 Web 配置'));
    dirtyForm(form);form.onsubmit=e=>{e.preventDefault();if(!confirm('确认修改 Web 服务配置？端口改变或关闭功能可能让当前页面断线、关闭终端。'))return;submit(form,async d=>{const response=await wb('settings/web',{data:{...d,web_port:Number(d.web_port),confirm:true}});form.append(message(response.reconnect?'已保存，服务正在调整。请使用新的地址重新连接。':'配置已保存并同步。','success'));if(!response.reconnect)await refreshBootstrap();});};
    grid.append(card('服务入口',form));
    grid.append(card('账号与访问',el('p',{},'改密将撤销所有网页登录并关闭网页终端会话。'),button('修改访问密码',()=>{
      const f=el('form',{},field('新密码','password','','password','至少 6 位，建议使用长且唯一的密码。'),field('再次输入','repeat','','password'),check('我知道这会让全部浏览器下线并关闭终端','confirm'),el('button',{type:'submit',class:'wb-btn primary'},'保存并重新登录'));
      f.querySelectorAll('input[type=password]').forEach(n=>allowCredentialAutofill(n,'new-password'));dirtyForm(f);
      f.onsubmit=e=>{e.preventDefault();submit(f,async d=>{if(d.password!==d.repeat)throw new Error('两次密码不一致');if(d.password.length<6)throw new Error('密码至少 6 位');await wb('password',{data:{password:d.password,confirm:d.confirm}});f.reset();state.dirty=false;sessionStorage.clear();f.append(message('已修改，正在撤销会话并重新登录…','success'));setTimeout(()=>location.reload(),1000);});};dialog('修改 Web 密码',f);
    }),button('退出当前登录',logout)));
    lazyCards('两步验证（2FA）',async()=>{const {twoFactorCard}=await managementModule('two-factor');return twoFactorCard({card,dialog,closeDialog,submit});});
  }
  if(active==='health'){
    lazyCards('版本与更新',async()=>{const {updateCard}=await managementModule('settings-updates');return updateCard({card,confirmAction});});
    lazyCards('通道状态',async()=>{const health=await api('/api/health');return [card('通道状态',...Object.entries(health.components||{}).map(([name,v])=>el('div',{class:'wb-detail-row'},el('dt',{},name),el('dd',{},tag(v.state),v.error?message(v.error):null))),button('刷新状态',render)),
      el('details',{class:'wb-card wb-diagnostics'},el('summary',{},'查看详细健康数据'),el('pre',{class:'wb-pre'},JSON.stringify(health,null,2)))];});
    grid.append(card('维护操作',el('p',{},'这些操作将在当前对话中显示结果，重启可能中断连接。'),button('检查服务状态',()=>{location.hash='/chat';window.XGentChat?.command('/status');}),button('重启服务',()=>confirmAction('重启服务','当前连接和终端可能被关闭。确认重启？',async()=>{location.hash='/chat';window.XGentChat?.command('/restart');}))));
  }
  page.append(grid);return page;
}

async function blacklistEditor({dialog,submit,dirtyForm}){
  const box=el('div',{},message('正在读取黑名单…','loading'));dialog('命令黑名单',box);
  try{
    let state=await wb('settings/blacklist');
    const form=el('form',{class:'wb-blacklist-form'},field('禁止片段（每行一条）','patterns',state.patterns.join('\n'),'textarea','命令包含这些片段时会被现有黑名单机制拦截；这不是沙箱。'));
    const input=form.querySelector('textarea');input.rows=10;input.setAttribute('aria-label','禁止片段（每行一条）');
    const recommended=el('details',{},el('summary',{},'推荐规则（不会自动启用）'),el('pre',{class:'wb-pre'},state.recommended.join('\n')),button('追加推荐规则',()=>{input.value=Array.from(new Set([...input.value.split('\n').filter(Boolean),...state.recommended])).join('\n');input.dispatchEvent(new Event('input',{bubbles:true}));}));
    const feedback=el('div');form.append(recommended,feedback,el('button',{class:'wb-btn primary',type:'submit'},'保存黑名单'));dirtyForm(form);
    form.onsubmit=e=>{e.preventDefault();const patterns=input.value.split('\n').map(s=>s.trim()).filter(Boolean);if(!patterns.length&&state.patterns.length&&!confirm('确认清空所有命令黑名单规则？'))return;submit(form,async()=>{state=await wb('settings/blacklist',{data:{patterns,revision:state.revision,confirm_clear:!patterns.length}});input.value=state.patterns.join('\n');feedback.replaceChildren(message('黑名单已保存','success'));});};box.replaceChildren(form);
  }catch(error){box.replaceChildren(message(error.message));}
}
