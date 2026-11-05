/* Shared Web branding. This never changes model prompts or saved message text. */
export const defaultBranding = Object.freeze({version:1,name:'XGent',mode:'preset',preset:'4-B',source:'',avatar_id:'',avatars:[]});
export const maxImageBytes = 8 * 1024 * 1024;
const paths = ['M7.5 7.5L16 16L7.5 24.5', 'M16 16L24.5 7.5', 'M17.5 24.5H24.5'];
function presetSvg(background, inks, {glow=false,dots=false}={}) {
  const gradient=Array.isArray(background);
  const defs=(gradient?'<linearGradient id="background" x1="0" y1="0" x2="1" y2="1"><stop stop-color="'+background[0]+'"/><stop offset="1" stop-color="'+background[1]+'"/></linearGradient>':'')+
    (glow?'<filter id="glow" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="0.6"/><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>':'');
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none">\n'+
    (defs?'  <defs>'+defs+'</defs>\n':'')+
    '  <rect width="32" height="32" rx="7" fill="'+(gradient?'url(#background)':background)+'"/>\n'+
    (dots?'  <circle cx="5.5" cy="4" r="1" fill="#ef4444"/><circle cx="9.5" cy="4" r="1" fill="#f59e0b"/><circle cx="13.5" cy="4" r="1" fill="#10b981"/>\n':'')+
    '  <g stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"'+(glow?' filter="url(#glow)"':'')+'>\n'+
    paths.map((path,index)=>'    <path d="'+path+'" stroke="'+inks[index]+'"/>').join('\n')+'\n  </g>\n</svg>';
}
export const brandingPresets = [
  {id:'4-B',label:'a',name:'流光蓝紫',source:presetSvg(['#0c1524','#161226'],['#38bdf8','#818cf8','#c084fc'],{glow:true})},
  {id:'4-C',label:'b',name:'终端雾蓝',source:presetSvg('#131922',['#e2e8f0','#94a3b8','#38bdf8'],{dots:true})},
  {id:'4-D',label:'c',name:'黑曜钛金',source:presetSvg('#141517',['#f59e0b','#fbbf24','#fef08a'])},
  {id:'4-E',label:'d',name:'黑白极简',source:presetSvg('#000000',['#ffffff','#ffffff','#ffffff'])},
  {id:'4-F',label:'e',name:'冷暖对撞',source:presetSvg('#0f141c',['#38bdf8','#38bdf8','#fb923c'])},
  {id:'4-A',label:'f',name:'黑客翠绿',source:presetSvg('#09110d',['#10b981','#34d399','#34d399'],{glow:true})},
];
const svgNamespace='http://www.w3.org/2000/svg';
const tags=new Set(('div span p b strong i em small br section img style svg g defs path rect circle ellipse line polyline polygon lineargradient radialgradient stop filter fegaussianblur femerge femergenode fecolormatrix fecomposite feflood feblend feoffset clipPath mask pattern use text tspan foreignobject title desc').toLowerCase().split(' '));
const attributes=new Set(('id class role aria-label aria-hidden alt title style src width height viewbox preserveaspectratio fill fill-opacity fill-rule stroke stroke-width stroke-linecap stroke-linejoin stroke-opacity stroke-dasharray stroke-dashoffset opacity d x y x1 y1 x2 y2 cx cy r rx ry points transform gradientunits gradienttransform offset stop-color stop-opacity filter filterunits stddeviation in in2 result type values operator k1 k2 k3 k4 mode dx dy flood-color flood-opacity clippathunits clip-path mask maskunits maskcontentunits patternunits patterncontentunits patterntransform href xlink:href xmlns color font-family font-size font-weight text-anchor dominant-baseline').split(' '));
const templates=new Map(), rendered=new WeakMap();
let saved={...defaultBranding}, revision=-1, preview=null, authenticated=false;
let brandingRequest=null,brandingController=null,brandingRequestVersion=0;
let privateLibraryReady=false;
let brandingRequestedRevision=-1;
export function activeBranding(){return preview||saved;}
export function brandingSource(config){return config.mode==='preset'?brandingPresets.find(p=>p.id===config.preset)?.source||brandingPresets[0].source:String(config.source||config.avatars?.find(item=>item.id===config.avatar_id)?.source||'');}
export function imageSource(value) {
  if(/^data:image\/[a-z0-9.+-]+(?:;[a-z0-9=.+-]+)*,/i.test(value))return value;
  if(/^https?:\/\//i.test(value)){
    try{const url=new URL(value);if(url.hostname&&!/\s/.test(value))return url.href;}catch{}
  }
  return null;
}
export function sourceKind(source) {
  const text=String(source||'').trim();
  if(!text)return 'empty';
  if(imageSource(text))return 'image';
  if(text.startsWith('<'))return 'markup';
  throw new Error('请输入 SVG／HTML 代码、图片网址或 data:image/ 地址。');
}
function cleanCss(text) {
  if(/\\|@import|:host|expression\s*\(|-moz-binding|\bbehavior\s*:/i.test(text))return '';
  return text.replace(/url\s*\(([^)]*)\)/gi,(whole,url)=>/^['"]?#[\w-]+['"]?$/.test(url.trim())?whole:'none');
}
function logoTemplate(source) {
  if(templates.has(source))return templates.get(source);
  const template=document.createElement('template');template.innerHTML=source;
  function safeNode(original,depth=0){
    if(depth>64)return null;
    if(original.nodeType===Node.TEXT_NODE)return document.createTextNode(original.textContent);
    if(original.nodeType!==Node.ELEMENT_NODE)return null;
    const tag=original.localName.toLowerCase();if(!tags.has(tag))return null;
    if(tag==='style'){const result=document.createElement('style');result.textContent=cleanCss(original.textContent);return result;}
    const result=original.namespaceURI===svgNamespace?document.createElementNS(svgNamespace,original.localName):document.createElement(tag);
    for(const attr of original.attributes){
      const name=attr.name.toLowerCase();if(!attributes.has(name))continue;
      let value=attr.value;
      if(name==='style')value=cleanCss(value);
      else if(name==='src'){value=imageSource(value);if(!value)continue;}
      else if(name==='href'||name==='xlink:href'){if(!/^#[\w-]+$/.test(value))continue;}
      else if(/url\s*\(/i.test(value)){value=cleanCss(value);}
      result.setAttribute(attr.name,value);
    }
    if(tag==='img'){result.referrerPolicy='no-referrer';result.alt='';result.draggable=false;}
    for(const child of original.childNodes){const safe=safeNode(child,depth+1);if(safe)result.append(safe);}
    return result;
  }
  const fragment=document.createDocumentFragment();
  for(const child of template.content.childNodes){const safe=safeNode(child);if(safe)fragment.append(safe);}
  templates.set(source,fragment);if(templates.size>8)templates.delete(templates.keys().next().value);
  return fragment;
}
export function renderBrandLogo(host, config=activeBranding()) {
  const source=brandingSource(config);if(rendered.get(host)===source)return;
  rendered.set(host,source);host.classList.add('brand-logo');
  host.replaceChildren();
  const shadow=host.shadowRoot||host.attachShadow({mode:'open'});
  const style=document.createElement('style');
  style.textContent=':host{display:inline-flex;overflow:hidden;contain:layout paint style;isolation:isolate;pointer-events:none}*{box-sizing:border-box}#logo{width:100%;height:100%;overflow:hidden;display:grid;place-items:center;position:relative;font:inherit;color:inherit}#logo>svg,#logo>img,#logo>div,#logo>section{max-width:100%;max-height:100%}svg,img{display:block;width:100%;height:100%}img{object-fit:contain}.empty{font-size:18px;line-height:1;color:#94a3b8}';
  const content=document.createElement('div');content.id='logo';
  const kind=sourceKind(source);
  if(kind==='image'){
    const img=document.createElement('img');img.src=imageSource(source);img.alt='';img.referrerPolicy='no-referrer';img.draggable=false;
    img.addEventListener('error',()=>{if(img.isConnected){content.replaceChildren(emptyLogo());host.dispatchEvent(new CustomEvent('brand-image-error',{bubbles:true}));}},{once:true});
    content.append(img);
  }else if(kind==='markup')content.append(logoTemplate(source).cloneNode(true));
  else content.append(emptyLogo());
  shadow.replaceChildren(style,content);
}
function emptyLogo(){const node=document.createElement('span');node.className='empty';node.textContent='＋';return node;}
export function decorateBrandAuthor(author) {
  const icon=document.createElement('span');icon.className='bubble-author-icon';icon.dataset.brandLogo='';icon.setAttribute('aria-hidden','true');
  const name=document.createElement('span');name.dataset.brandName='';name.textContent=activeBranding().name;
  renderBrandLogo(icon);author.replaceChildren(icon,name);
}
function applyBranding() {
  const config=activeBranding();
  document.querySelectorAll('[data-brand-logo]').forEach(node=>renderBrandLogo(node,config));
  document.querySelectorAll('[data-brand-name]').forEach(node=>node.textContent=(node.dataset.brandPrefix||'')+config.name+(node.dataset.brandSuffix||''));
  document.title=config.name+(document.body.dataset.brandTerminal==='true'?' Terminal':' Web Chat');
  const subtitle=document.getElementById('login-sub');
  if(subtitle&&document.getElementById('login-code')?.hidden!==false)subtitle.textContent='请输入访问密码以继续使用 '+config.name+' Web';
  window.dispatchEvent(new CustomEvent('xgent-branding-applied',{detail:config}));
  if(!preview)document.querySelectorAll('.branding-form').forEach(form=>form.dispatchEvent(new CustomEvent('brand-config-changed')));
}
export function acceptBranding(data) {
  const next=data?.branding||data?.values?.web_branding;
  if(!next){const value=data?.branding_revision;if(Number.isSafeInteger(value)&&value>revision)refreshBranding(value>brandingRequestedRevision,value).catch(()=>{});return;}
  const incomingRevision=data?.values?.web_branding?(data.branding_revision??data.revision):data.revision;
  if(!Number.isSafeInteger(incomingRevision)||incomingRevision<revision)return;
  if(typeof next.name!=='string'||!['preset','custom','upload'].includes(next.mode))return;
  if(data?.values?.web_branding)privateLibraryReady=true;
  const changed=incomingRevision!==revision||saved.name!==next.name||saved.avatar_id!==next.avatar_id||brandingSource(saved)!==brandingSource(next);
  saved={...defaultBranding,...next};revision=incomingRevision;
  if(changed&&!preview)applyBranding();
}
export function previewBranding(value) {
  sourceKind(brandingSource(value));preview={...value};applyBranding();
}
export function cancelBrandingPreview(){preview=null;applyBranding();}
export async function saveBranding(value) {
  sourceKind(brandingSource(value));
  const response=await fetch('/api/config',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:'web_branding',value})});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'品牌设置保存失败');
  if(result.settings?.values?.web_branding)acceptBranding(result.settings);else await refreshBranding(true,result.settings?.branding_revision);preview=null;applyBranding();return {...saved};
}
export async function deleteBrandingAvatar(id) {
  const response=await fetch('/api/config',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:'web_branding_delete_avatar',value:id})});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'头像删除失败');
  if(result.settings?.values?.web_branding)acceptBranding(result.settings);else await refreshBranding(true,result.settings?.branding_revision);preview=null;applyBranding();return {...saved};
}
export function refreshBranding(fresh=false,targetRevision=revision) {
  if(brandingRequest&&!fresh)return brandingRequest;
  brandingController?.abort();const controller=brandingController=new AbortController(),version=++brandingRequestVersion;
  brandingRequestedRevision=targetRevision;
  const params=new URLSearchParams();const privateRequest=authenticated;
  if(privateRequest)params.set('library','1');
  if(!fresh&&revision>=0&&(!privateRequest||privateLibraryReady))params.set('revision',revision);
  const request=fetch('/api/branding'+(params.size?'?'+params:''),{credentials:'same-origin',cache:'no-store',signal:controller.signal})
    .then(async response=>{if(!response.ok)throw new Error('头像设置暂时无法读取');const data=await response.json();if(version===brandingRequestVersion){if(privateRequest)privateLibraryReady=true;acceptBranding(data);}})
    .catch(error=>{if(error.name==='AbortError'&&version!==brandingRequestVersion)return brandingRequest;throw error;})
    .finally(()=>{if(brandingRequest===request)brandingRequest=null;});
  brandingRequest=request;return request;
}
window.XGentBranding={decorateAuthor:decorateBrandAuthor,refresh:refreshBranding,cancelPreview:cancelBrandingPreview,get name(){return activeBranding().name;},get state(){return {revision,ready:revision>=0&&(!authenticated||privateLibraryReady),values:{...saved,avatars:(saved.avatars||[]).map(item=>({...item}))}};}};
window.addEventListener('xgent-authenticated',()=>{authenticated=true;privateLibraryReady=false;refreshBranding(true).catch(()=>{});});
window.addEventListener('xgent-auth-expired',()=>{authenticated=false;privateLibraryReady=false;cancelBrandingPreview();refreshBranding(true).catch(()=>{});});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshBranding().catch(()=>{});});
applyBranding();refreshBranding().catch(()=>{});
setInterval(()=>{if(!document.hidden&&(!authenticated||!window.XGentAppearance))refreshBranding().catch(()=>{});},15000);
