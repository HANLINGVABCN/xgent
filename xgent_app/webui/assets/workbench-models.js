/* Provider and skill views. Configuration contracts stay unchanged. */
import {$,el,button,fmt,stamp,bytes,message,empty,field,select,check,table,formData,api,wb,download,query,tag,copyText,requestId,safeLocalUrl,inlineState} from './components.js';
import {heading,card,toolbar,actions} from './ui.js';
export function createViews(context) {
const {state,filter,render,selectFilter,searchFilter,sourceLink,filePagination,outputViewer,showError,detail,closeDetail,confirmAction,dialog,closeDialog,submit,dirtyForm,errorOr,refreshBootstrap,chatControls,localFilters,managementModule,taskSourceSearch}=context;
async function modelPage(read){let mode=filter('mode')||'providers';
 if(mode==='memories'){/* 「记忆」已迁至 设置·对话与记忆：旧过滤值回退到提供商视图 */state.filters.models={...state.filters.models,mode:'providers'};mode='providers';}
 const page=el('div',{},heading('模型与技能','连接你的模型，让 Agent 具备所需的能力。',mode==='providers'?[button('导入 / 导出',importExport),button('添加提供商',()=>providerForm(null),'primary')]:[]));const tabs=el('div',{class:'wb-tabs'},button('模型提供商',()=>{filter('mode','providers');render();},mode==='providers'?'active':''),button('技能库',()=>{filter('mode','skills');render();},mode==='skills'?'active':''));page.append(tabs);
 if(mode==='skills'){const {knowledgePage}=await managementModule('knowledge');await knowledgePage(page,await read(mode),mode,{state,filter,localFilters,render,detail,closeDetail,confirmAction,refreshBootstrap,toolbar});return page;}
 const bootReady=state.boot&&Date.now()-state.bootUpdatedAt<60000;
 const [boot,data]=await Promise.all([bootReady?Promise.resolve(read.cached('bootstrap',state.boot)):read('bootstrap'),read('providers')]);
 if(!bootReady){state.boot=boot;state.bootUpdatedAt=Date.now();}
 chatControls();state.providerFormats=data.formats;const providerSearch=el('input',{type:'search','aria-label':'搜索提供商或模型',placeholder:'搜索提供商名称、地址或模型…'}),providerCounts=el('span',{class:'wb-note',role:'status'});providerSearch.value=filter('providerQuery')||'';const grid=el('div',{class:'wb-grid wb-provider-list'});page.append(toolbar(providerSearch,providerCounts));for(const p of data.items){const c=card(p.name,el('p',{},p.base_url),actions(tag(p.api_format),tag(p.has_key?'已配置密钥':'未配置密钥'),state.boot.settings.values.chat_model?.startsWith(p.name+'|')?el('span',{class:'wb-tag good'},'当前对话'):null,state.boot.media_model?.provider===p.name?el('span',{class:'wb-tag good'},'当前媒体'):null),el('p',{},`${p.models.length} 个已保存模型`));const current=state.boot.settings.values.chat_model?.split('|');const choices=el('select',{'aria-label':p.name+' 模型'},p.models.map(m=>el('option',{value:m,selected:current?.[0]===p.name&&current?.[1]===m},m)));c.append(el('label',{class:'wb-field'},el('span',{},'选择模型'),choices),actions(button('用于对话',errorOr(c,async()=>{await wb('providers/select',{data:{target:'chat',provider:p.name,model:choices.value}});await refreshBootstrap();inlineState(c,'已设置为对话模型');render();})),button('用于媒体',errorOr(c,async()=>{await wb('providers/select',{data:{target:'media',provider:p.name,model:choices.value}});await refreshBootstrap();inlineState(c,'已设置为媒体模型');render();}))),el('div',{class:'wb-card-footer'},button('编辑配置',()=>providerForm(p)),button('删除',()=>confirmAction('删除提供商','删除后，依赖此提供商的默认模型需要重新选择。',()=>wb('providers/delete',{data:{name:p.name,confirm:true}})),'danger')));c.dataset.providerSearch=[p.name,p.base_url,...p.models].join(' ').toLowerCase();if(!p.models.length)c.querySelectorAll('button').forEach(b=>{if(b.textContent.startsWith('用于'))b.disabled=true;});grid.append(c);}const filterProviders=(save=true)=>{if(save)localFilters({providerQuery:providerSearch.value});let count=0;for(const row of grid.children){row.hidden=!row.dataset.providerSearch.includes(providerSearch.value.trim().toLowerCase());if(!row.hidden)count++;}providerCounts.textContent=count+' / '+data.items.length+' 个提供商';};providerSearch.oninput=()=>filterProviders();filterProviders(false);page.append(data.items.length?grid:empty('连接第一个模型','填写兼容接口地址和密钥后，就可以开始对话。密钥仅写入服务器，不会回传明文。',button('添加提供商',()=>providerForm(null),'primary')));return page;}
function providerForm(provider) {
  const p=provider||{name:'',base_url:'',models:[],api_format:'openai'};
  const form=el('form',{},field('提供商名称','name',p.name),field('接口地址','base_url',p.base_url,'url','填写 API 地址，不要把密钥放入地址中。'),
    select('接口格式','api_format',state.providerFormats||['openai','openai_compatible','claude','gemini','vertex'],p.api_format),
    field('API Key','api_key','','password',provider?'留空保留已保存密钥；不会读取或回显明文。':'只写入服务器，不保存到浏览器。'),
    check('清除已保存密钥','clear_key'),field('已保存模型（每行一个）','models',p.models.join('\n'),'textarea'));
  form.elements.api_key.autocomplete='new-password';
  const candidates=el('div',{class:'wb-model-candidates'});
  const fetchBtn=button('拉取候选模型',async()=>{
    fetchBtn.disabled=true;fetchBtn.textContent='正在连接…';candidates.replaceChildren();
    try{
      const values=formData(form),connection={name:values.name.trim()||provider?.name||'新提供商',base_url:values.base_url,api_format:values.api_format,clear_key:values.clear_key};
      if(values.api_key.trim())connection.api_key=values.api_key.trim();
      if(!connection.base_url.trim())throw new Error('请先填写接口地址。');
      const d=await wb('providers/fetch',{data:{name:provider?.name,connection}});
      const choices=el('div',{class:'wb-candidate-list'});const selected=new Set(form.elements.models.value.split('\n').map(s=>s.trim()));
      d.models.forEach(model=>choices.append(check(model,model,selected.has(model))));
      const search=el('input',{type:'search',placeholder:'筛选候选模型','aria-label':'筛选候选模型'});
      search.oninput=()=>choices.querySelectorAll('label').forEach(l=>l.hidden=!l.textContent.toLowerCase().includes(search.value.toLowerCase()));
      candidates.append(el('h3',{},`${d.models.length} 个候选模型`),el('p',{class:'wb-note'},'使用当前表单的连接信息拉取。应用到列表后，保存配置生效。'),search,choices,
        actions(button('全选可见',()=>choices.querySelectorAll('label:not([hidden]) input').forEach(i=>i.checked=true)),button('应用到列表',()=>{
          form.elements.models.value=[...choices.querySelectorAll('input:checked')].map(i=>i.name).join('\n');state.dirty=true;inlineState(candidates,'已应用到编辑列表，保存配置后生效。');
        })));
    }catch(e){showError(candidates,e);}finally{fetchBtn.disabled=false;fetchBtn.textContent='拉取候选模型';}});form.append(fetchBtn,candidates);
  form.append(el('p',{class:'wb-note'},'删除当前正在使用的模型会清除对应默认选择，需要重新指定。'),actions(button('取消',closeDialog),el('button',{class:'wb-btn primary',type:'submit'},'保存配置')));
  dirtyForm(form);form.onsubmit=e=>{e.preventDefault();submit(form,async d=>{
    const data={...d,create:!provider,original_name:provider?.name,models:d.models.split('\n').map(v=>v.trim()).filter(Boolean)};
    if(!d.api_key)delete data.api_key;
    await wb('providers/save',{data});form.elements.api_key.value='';state.dirty=false;closeDialog();await refreshBootstrap();await render();
  });};dialog(provider?'编辑提供商':'添加提供商',form);
}
function importExport(){const form=el('div',{},el('p',{class:'wb-note'},'导入会合并/覆盖同名提供商；脱敏配置不覆盖原有密钥。默认导出不包含任何密钥。'));const file=el('input',{type:'file',accept:'.json,application/json','aria-label':'选择配置文件'});const errors=el('div');form.append(field('粘贴 JSON 配置','config','','textarea'),file,errors);file.onchange=async()=>{if(file.files[0])form.querySelector('textarea').value=await file.files[0].text();};form.append(actions(button('确认导入',async()=>{try{const config=JSON.parse(form.querySelector('textarea').value);if(!confirm('合并导入配置并覆盖同名提供商？'))return;await wb('providers/import',{data:{config,confirm:true}});form.querySelector('textarea').value='';closeDialog();render();await refreshBootstrap();}catch(e){errors.replaceChildren(message(e.message));}},'primary'),button('导出脱敏配置',async()=>{try{download('xgent-providers.json',await wb('providers/export',{data:{include_secrets:false}}));}catch(e){errors.replaceChildren(message(e.message));}}),button('导出含密钥配置',async()=>{if(!confirm('导出的文件包含明文 API Key。确认下载并自行妥善保管？'))return;try{download('xgent-providers-private.json',await wb('providers/export',{data:{include_secrets:true,confirm:true}}));}catch(e){errors.replaceChildren(message(e.message));}},'danger')));dialog('配置导入与导出',form);}

return {modelPage};
}
