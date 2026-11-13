import {el,button,field,select,check,wb,message,requestId} from './components.js';
import {actions} from './ui.js';

export async function updateCard({card,confirmAction}){
  const status=await wb('system/update');
  const version=el('p',{class:'wb-note'},'当前版本：'+status.current_version);
  const source=select('更新来源','source',[{value:'normal',label:'XGent 主仓库'},{value:'test',label:'XGent 测试仓库'}],status.source);
  const token=field('GitHub Token（可选）','token','','password',status.has_token?'留空使用服务器已配置的 Token。':'公开仓库不需要；私有仓库需要 Contents 只读权限。');
  const overwrite=check('覆盖并备份本地提示词与公共技能','overwrite',false);
  const result=el('div',{class:'wb-update-result','aria-live':'polite'}),progress=el('div',{class:'wb-update-progress','aria-live':'polite'});
  const panel=card('版本与更新',version,source,token,overwrite,el('p',{class:'wb-note'},'默认保留本地提示词和技能。更新保留数据库、运行数据、私有技能和配置，完成后重启服务。'),result,progress);
  let plan=null,busy=false,identifier=status.job?.id,retryId=requestId(),timer;
  const checkButton=button('检查更新',async()=>{
    busy=true;paintControls();result.replaceChildren(message('正在检查所选仓库的最新版本…','loading'));
    try{
      plan=await wb('system/update/check',{data:{source:source.querySelector('select').value,token:token.querySelector('input').value}});
      if(plan.current_version)version.textContent='当前版本：'+plan.current_version;
      token.querySelector('input').value='';retryId=requestId();
      result.replaceChildren(el('p',{},plan.up_to_date?'当前已是所选仓库的最新版本。':'发现可更新版本。'),el('code',{},plan.revision.slice(0,10)),el('p',{class:'wb-note'},plan.message||'最新提交'));
    }catch(error){plan=null;result.replaceChildren(message(error.message));}finally{busy=false;paintControls();}
  });
  const updateButton=button('更新并重启',()=>{
    const checked=plan,replace=overwrite.querySelector('input').checked;
    confirmAction('更新 XGent',`将更新到 ${checked.revision.slice(0,10)}，${replace?'备份后覆盖':'保留'}本地提示词与公共技能，并重启服务。请先等待正在进行的对话结束。`,async()=>{
      const receipt=await wb('system/update/start',{data:{plan_id:checked.plan_id,request_id:retryId,overwrite_local_custom_files:replace,confirm:true}});
      if(receipt.up_to_date){
        plan={...checked,up_to_date:true};busy=false;version.textContent='当前版本：'+receipt.current_version;
        result.replaceChildren(message('当前已是所选仓库的最新版本，无需重复更新。','success'));paintControls();return;
      }
      identifier=receipt.id;busy=true;paintProgress(receipt.job);paintControls();setTimeout(poll,1000);
    },null,()=>{});
  },'primary');
  panel.append(actions(checkButton,updateButton));
  function paintControls(){checkButton.disabled=busy;updateButton.disabled=busy||!plan||(plan.up_to_date&&!overwrite.querySelector('input').checked);source.querySelector('select').disabled=busy;overwrite.querySelector('input').disabled=busy;}
  function paintProgress(job,historical=false){
    if(!job){progress.replaceChildren();return;}
    const label={pending:'准备更新…',downloading:'正在下载并保存代码…',saved:'代码已保存，准备重启…',restarting:'服务正在重启，稍后自动确认…',complete:'更新完成，服务已重新启动。',failed:'更新未完成。'}[job.phase]||job.phase;
    if(historical&&['complete','failed'].includes(job.state)){
      const record=el('details',{class:'wb-update-history'},el('summary',{},(job.state==='complete'?'上次更新已完成':'上次更新未完成')+' · '+String(job.revision||'').slice(0,10)));
      record.append(message(label,job.state==='failed'?'error':'success'));if(job.error)record.append(message(job.error));
      if(job.backup_path)record.append(el('p',{class:'wb-note'},'本地文件备份：'+job.backup_path));progress.replaceChildren(record);
      busy=false;paintControls();return;
    }
    progress.replaceChildren(message(label,job.state==='failed'?'error':job.state==='complete'?'success':'loading'));
    if(job.error)progress.append(message(job.error));
    if(job.backup_path)progress.append(el('p',{class:'wb-note'},'本地文件备份：'+job.backup_path));
    if(['complete','failed'].includes(job.state)){
      busy=false;plan=null;
      if(job.state==='complete')result.replaceChildren(message('已更新至 '+job.revision.slice(0,10)+'。','success'));
      paintControls();
    }
  }
  async function poll(){
    clearTimeout(timer);
    if(!identifier)return;
    if(!panel.isConnected){timer=setTimeout(poll,5000);return;}
    try{
      const next=await wb('system/update?id='+encodeURIComponent(identifier));paintProgress(next.job);version.textContent='当前版本：'+next.current_version;
      if(next.job&&!['complete','failed'].includes(next.job.state))timer=setTimeout(poll,2000);
    }catch{progress.replaceChildren(message('等待服务重新连接…','loading'));timer=setTimeout(poll,3000);}
  }
  source.onchange=()=>{plan=null;result.replaceChildren();paintControls();};
  token.oninput=()=>{plan=null;paintControls();};
  overwrite.onchange=paintControls;
  paintControls();paintProgress(status.job,!!status.job?.historical);
  if(status.job&&!['complete','failed'].includes(status.job.state)){busy=true;paintControls();timer=setTimeout(poll,2000);}
  return panel;
}
