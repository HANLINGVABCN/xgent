import {el,button,field,message} from './components.js';
import {brandingPresets,defaultBranding,maxImageBytes,brandingSource,renderBrandLogo,sourceKind,previewBranding,cancelBrandingPreview,saveBranding} from './branding.js';

export function brandingCard({card,actions,state,dirtyForm}) {
  const initial=()=>window.XGentBranding.state.values;
  let draft=initial(),reader=null,uploadSequence=0,editing=false,busy=false,pendingAvatarId='',initialized=false;
  const form=el('form',{class:'branding-form'});
  const name=field('系统名称','brand_name',draft.name,'text');
  const nameInput=name.querySelector('input');nameInput.maxLength=80;nameInput.required=true;
  const list=el('div',{class:'brand-avatar-strip',role:'radiogroup','aria-label':'头像列表'});
  const preview=el('span',{class:'brand-editor-preview','aria-hidden':'true'});
  const avatarName=field('头像名称','avatar_name','','text');
  const avatarInput=avatarName.querySelector('input');avatarInput.maxLength=40;avatarInput.placeholder='给头像命名';
  const nameSave=button('命名',()=>persist(true));
  const code=el('textarea',{name:'brand_source',rows:8,spellcheck:'false',placeholder:'输入 SVG／HTML 代码，或粘贴图片地址','aria-label':'Logo 代码或图片链接'});
  const codeSave=button('保存',()=>persist(true), 'primary');codeSave.setAttribute('aria-label','保存头像');
  const codeLabel=el('label',{class:'wb-field brand-code-field'},el('span',{},'Logo 代码或图片链接'),el('div',{class:'brand-code-editor'},code,codeSave));
  const feedback=el('div',{class:'brand-feedback',role:'status'});
  const file=el('input',{type:'file',accept:'image/*',hidden:true,'aria-label':'上传本地 Logo 图片'});
  const fileName=el('span',{class:'brand-file-name'});
  const save=el('button',{class:'wb-btn primary',type:'submit'},'保存品牌设置');
  const presetLetter=()=>draft.preset.slice(-1).toLowerCase();
  function selectedName(){return draft.avatar_id?draft.avatars.find(item=>item.id===draft.avatar_id)?.name||'':draft.mode==='preset'?presetLetter():'';}
  function abortUpload(){uploadSequence++;reader?.abort();reader=null;}
  function select(value){abortUpload();pendingAvatarId='';draft={...draft,...value};code.value=brandingSource(draft);avatarInput.value=selectedName();fileName.textContent='';changed();}
  function drawStrip(){
    const left=list.scrollLeft;list.replaceChildren();
    function choice(id,label,config,fn,title=label){
      const icon=el('span',{class:'brand-preset-icon','aria-hidden':'true'});
      if(config)renderBrandLogo(icon,config);else icon.append(el('span',{class:'brand-custom-icon'},'＋'));
      const item=button([icon,el('span',{class:'brand-avatar-label'},label)],fn);
      item.className='brand-preset';item.setAttribute('role','radio');item.setAttribute('aria-label',label);item.title=title;
      item.dataset.avatar=id;item.setAttribute('aria-checked',String(id===(draft.mode==='preset'?draft.preset:draft.avatar_id||'custom')));list.append(item);
    }
    for(const preset of brandingPresets)choice(preset.id,preset.id.slice(-1).toLowerCase(),{...defaultBranding,preset:preset.id},
      ()=>select({mode:'preset',preset:preset.id,source:'',avatar_id:''}),preset.id+' '+preset.name);
    choice('custom','自定义',null,()=>{select({mode:'custom',source:'',avatar_id:''});code.focus();});
    for(const item of draft.avatars)choice(item.id,item.name,{...defaultBranding,mode:item.mode,source:item.source},
      ()=>select({mode:item.mode,source:'',avatar_id:item.id}),item.name);
    list.scrollLeft=left;
  }
  function reflect(){sourceKind(brandingSource(draft));renderBrandLogo(preview,draft);previewBranding(draft);drawStrip();}
  function changed(){editing=true;state.dirty=true;feedback.replaceChildren();try{reflect();}catch(error){feedback.replaceChildren(message(error.message));}}
  function revealSelected(){const selected=list.querySelector('[aria-checked=true]');if(selected){const item=selected.getBoundingClientRect(),box=list.getBoundingClientRect();list.scrollLeft+=item.left-box.left-(list.clientWidth-item.width)/2;}}
  function load(value){const before=draft.avatar_id||draft.preset;abortUpload();draft={...value};pendingAvatarId='';nameInput.value=draft.name;code.value=brandingSource(draft);avatarInput.value=selectedName();fileName.textContent='';drawStrip();renderBrandLogo(preview,draft);if(!initialized||before!==(draft.avatar_id||draft.preset))requestAnimationFrame(()=>{if(form.isConnected)revealSelected();});initialized=true;}
  function savedValue(asAvatar){
    const current=initial();const result={...draft,name:asAvatar?current.name:draft.name,avatars:current.avatars};
    const source=brandingSource(draft);
    if(!source){if(asAvatar)throw new Error('请先输入头像代码或选择图片。');return result;}
    if(draft.mode==='preset'&&!asAvatar&&avatarInput.value.trim()===presetLetter())return result;
    const alias=avatarInput.value.trim()||selectedName()||'头像 '+(current.avatars.length+1);
    const existing=current.avatars.find(item=>item.id===draft.avatar_id)||current.avatars.find(item=>item.name===alias&&item.source===source);
    const id=existing?.id||(pendingAvatarId ||= globalThis.crypto?.randomUUID?.()||('avatar-'+Date.now().toString(36)+Math.random().toString(36).slice(2)));
    const entry={id,name:alias,mode:draft.mode==='upload'?'upload':'custom',source};
    result.avatars=current.avatars.map(item=>item.id===id?entry:item);
    if(!result.avatars.some(item=>item.id===id))result.avatars.push(entry);
    return {...result,mode:entry.mode,avatar_id:id,source:''};
  }
  async function persist(asAvatar){
    if(busy)return;feedback.replaceChildren();
    if(reader){feedback.replaceChildren(message('图片正在读取，请稍候再保存。'));return;}
    const pendingName=nameInput.value;
    const controls=[...form.querySelectorAll('button,input,textarea')].map(node=>[node,node.disabled]);
    busy=true;form.setAttribute('aria-busy','true');controls.forEach(([node])=>node.disabled=true);
    try{
      const stored=await saveBranding(savedValue(asAvatar));
      load(asAvatar?{...stored,name:pendingName}:stored);
      editing=draft.name!==stored.name;state.dirty=editing;
      if(editing)previewBranding(draft);
      feedback.replaceChildren(message(asAvatar?'头像已保存。':'品牌设置已保存，其他网页设备同步生效。','success'));
      revealSelected();
    }catch(error){feedback.replaceChildren(message(error.message));}
    finally{busy=false;form.removeAttribute('aria-busy');controls.forEach(([node,disabled])=>node.disabled=disabled);}
  }
  code.addEventListener('input',()=>{abortUpload();draft={...draft,mode:'custom',source:code.value,avatar_id:code.value.trim()?draft.avatar_id:''};fileName.textContent='';changed();});
  nameInput.addEventListener('input',()=>{draft.name=nameInput.value;changed();});
  avatarInput.addEventListener('input',()=>{editing=true;state.dirty=true;feedback.replaceChildren();});
  avatarInput.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();persist(true);}});
  file.addEventListener('change',()=>{
    abortUpload();const chosen=file.files?.[0];if(!chosen)return;
    if(chosen.size>maxImageBytes){feedback.replaceChildren(message('图片最多支持 8 MB，请选择较小的图片。'));file.value='';return;}
    const type=chosen.type||({png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',svg:'image/svg+xml',webp:'image/webp',gif:'image/gif'}[chosen.name.split('.').pop().toLowerCase()]);
    if(!type?.startsWith('image/')){feedback.replaceChildren(message('请选择 PNG、JPG、SVG、WebP 等图片。'));file.value='';return;}
    const sequence=uploadSequence;reader=new FileReader();
    reader.onload=()=>{if(sequence!==uploadSequence||!form.isConnected)return;const source=String(reader.result).replace(/^data:[^;]*;/,'data:'+type+';');draft={...draft,mode:'upload',source,avatar_id:''};pendingAvatarId='';code.value=source;avatarInput.value=chosen.name.replace(/\.[^.]+$/,'').slice(0,40);fileName.textContent=chosen.name;reader=null;changed();};
    reader.onerror=()=>{if(sequence===uploadSequence){feedback.replaceChildren(message('图片读取失败，请重新选择。'));reader=null;}};
    reader.readAsDataURL(chosen);file.value='';
  });
  preview.addEventListener('brand-image-error',()=>feedback.replaceChildren(message('图片暂时无法读取，请检查地址或换一张图片。')));
  form.append(name,list,el('div',{class:'brand-preview-row'},preview,avatarName,nameSave),codeLabel,
    el('div',{class:'brand-upload-row'},button('上传本地图片',()=>file.click()),file,fileName),
    el('p',{class:'wb-note'},'代码框内“保存”将头像加入上方列表。“命名”保存头像名称。图片最多 8 MB，代码最多 65,536 个字符。'),feedback,
    actions(button('恢复默认 4-B',()=>{load({...initial(),...defaultBranding,avatars:initial().avatars});changed();}),
      button('取消品牌预览',()=>{editing=false;state.dirty=false;cancelBrandingPreview();load(initial());feedback.replaceChildren();}),save));
  dirtyForm(form);
  form.onsubmit=event=>{event.preventDefault();persist(false);};
  form.addEventListener('brand-config-changed',()=>{if(!editing&&!busy)load(initial());});
  load(draft);
  const result=card('品牌名称与 Logo',form);result.classList.add('branding-card');return result;
}
