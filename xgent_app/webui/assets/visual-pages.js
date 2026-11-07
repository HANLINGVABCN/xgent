/* Progressive reply pages. Each fence completes independently of its reply. */
const instances=new Set();
const csp="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
const esc=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const base='<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="'+esc(csp)+'"><style>html,body{margin:0;min-height:0;box-sizing:border-box}body{font-family:system-ui,sans-serif}html[data-xgent-graphic],html[data-xgent-graphic] body{width:100%!important;height:100%!important;min-height:0!important;margin:0!important;padding:0!important;overflow:hidden!important}html[data-xgent-graphic] body>svg{display:block;width:100%!important;height:100%!important;max-width:none!important;max-height:none!important}html[data-xgent-embedded] svg[data-xgent-canvas]{display:block;width:100%!important;height:auto!important;max-width:100%!important}</style>';
const icon=path=>'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="'+path+'"/></svg>';
const codeIcon=icon('M8 6 2 12l6 6m8-12 6 6-6 6');
const expandIcon=icon('M5 19 19 5M5 13v6h6M13 5h6v6');
const collapseIcon=icon('m5 19 6-6M5 13h6v6m8-14-6 6M13 5v6h6');
function requested(recordId,index=0){const params=new URLSearchParams(location.hash.split('?')[1]||'');return params.get('visual')===String(recordId)&&params.get('visual_full')==='1'&&Number(params.get('visual_index')||0)===index;}

// Runs in the opaque-origin frame. Draft updates keep existing SVG nodes and
// CSS animations alive; unfinished scripts and event handlers remain inert.
function drawingSize(source,format){
  // The SVG header is available before its children or closing tag arrive.
  // Percentages have no intrinsic size; viewBox supplies the canvas ratio.
  if(format!=='svg'&&!/^\s*(?:<\?xml[^>]*>\s*)?<svg\b/i.test(source||''))return null;
  const header=/<svg\b([^>]*)(?:>|$)/i.exec(source||'');if(!header)return null;
  const svg=new DOMParser().parseFromString('<svg'+header[1]+'></svg>','text/html').querySelector('svg');
  if(!svg)return null;
  const number=value=>/^\s*(?:\d+(?:\.\d*)?|\.\d+)(?:px)?\s*$/i.test(value||'')&&Number.parseFloat(value)>0?Number.parseFloat(value):null;
  const box=(svg.getAttribute('viewBox')||'').trim().split(/[\s,]+/).map(Number);
  const ratio=box.length===4&&box.every(Number.isFinite)&&box[2]>0&&box[3]>0?box[2]/box[3]:null;
  let width=number(svg.getAttribute('width')),height=number(svg.getAttribute('height'));
  if(!width&&!height&&ratio){width=box[2];height=box[3];}
  else if(!height&&width&&ratio)height=width/ratio;
  else if(!width&&height&&ratio)width=height*ratio;
  if(!width||!height||!Number.isFinite(width+height))return null;
  const normalize=Math.min(1,100000/Math.max(width,height));return {width:width*normalize,height:height*normalize};
}

function pageRuntime(token,draft){
  let queued=false,lastSize='',observed=new Set();
  const observer=new ResizeObserver(schedule);
  function schedule(){if(!queued){queued=true;requestAnimationFrame(report);}}
  function report(){
    queued=false;if(!document.body)return;
    const body=document.body,children=Array.from(body.children).filter(node=>!['SCRIPT','STYLE','LINK','TEMPLATE'].includes(node.tagName));
    // Observe content as well as body: fixed-height pages can have overflowing
    // children, while compact cards need both their width and height measured.
    const next=new Set([body,...children.slice(0,32)]);
    for(const node of observed)if(!next.has(node))observer.unobserve(node);
    for(const node of next)if(!observed.has(node))observer.observe(node);observed=next;
    const style=getComputedStyle(body),paddingX=parseFloat(style.paddingLeft)+parseFloat(style.paddingRight),paddingY=parseFloat(style.paddingTop)+parseFloat(style.paddingBottom);
    let width=document.documentElement.clientWidth,height=Math.max(body.getBoundingClientRect().height,body.scrollHeight),compact=false,drawing=null;
    if(children.length===1){const child=children[0],rect=child.getBoundingClientRect(),css=getComputedStyle(child);
      const measured=rect.width+paddingX;
      if(measured>0&&measured<width-2){width=measured;compact=true;}
      height=Math.max(height,rect.height+paddingY+parseFloat(css.marginTop||0)+parseFloat(css.marginBottom||0));
      const svgs=child.tagName.toLowerCase()==='svg'?[child]:Array.from(child.querySelectorAll('svg'));
      if(svgs.length===1&&child.textContent.trim()===svgs[0].textContent.trim()&&!child.matches('button,a')){
        const svg=svgs[0],box=svg.viewBox?.baseVal;
        if(box?.width>0&&box.height>0){
          const embedded=child!==svg;
          const extraX=embedded?parseFloat(css.paddingLeft)+parseFloat(css.paddingRight)+paddingX:0;
          const extraY=embedded?parseFloat(css.paddingTop)+parseFloat(css.paddingBottom)+paddingY:0;
          const naturalWidth=embedded&&rect.width<document.documentElement.clientWidth-2?rect.width:box.width+extraX;
          drawing={width:naturalWidth,height:(naturalWidth-extraX)*box.height/box.width+extraY,embedded};
          svg.setAttribute('data-xgent-canvas','');
        }
      }
    }
    const rootStyle=getComputedStyle(document.documentElement);
    const viewportPage=!drawing&&['hidden','clip'].includes(style.overflowY)&&
      (['hidden','clip'].includes(rootStyle.overflowY)||body.getBoundingClientRect().height>=innerHeight-2)&&
      children.some(node=>node.tagName==='CANVAS'||['absolute','fixed'].includes(getComputedStyle(node).position)&&node.getBoundingClientRect().height>=innerHeight-2);
    let minHeight=0;
    if(viewportPage){
      // Full-window games use absolute overlays: body height cannot reveal a
      // clipped centered menu. Measure its visible contents before fitting.
      for(const container of children){const css=getComputedStyle(container);if(css.display!=='flex'||css.flexDirection!=='column'||!container.getClientRects().length)continue;
        const visible=Array.from(container.children).filter(node=>node.getClientRects().length);
        const occupied=visible.reduce((sum,node)=>{const rect=node.getBoundingClientRect(),s=getComputedStyle(node);return sum+rect.height+(parseFloat(s.marginTop)||0)+(parseFloat(s.marginBottom)||0);},0);
        minHeight=Math.max(minHeight,occupied+(parseFloat(css.rowGap)||0)*Math.max(0,visible.length-1)+(parseFloat(css.paddingTop)||0)+(parseFloat(css.paddingBottom)||0));
      }
    }
    if(document.documentElement.hasAttribute('data-xgent-graphic')){width=document.documentElement.clientWidth;height=innerHeight;compact=false;}
    const size=JSON.stringify([Math.ceil(width),Math.ceil(height),compact,drawing,viewportPage,Math.ceil(minHeight)]);
    if(size!==lastSize){lastSize=size;parent.postMessage({type:'xgent-visual-size',token,width:Math.ceil(width),height:Math.ceil(height),compact,drawing,viewportPage,minHeight:Math.ceil(minHeight)},'*');}
  }
  function layout(data){
    document.documentElement.toggleAttribute('data-xgent-graphic',!!data.graphic);
    document.documentElement.toggleAttribute('data-xgent-embedded',!!data.embedded);schedule();
  }
  function attrs(target,source){
    for(const attr of Array.from(target.attributes))if(!source.hasAttribute(attr.name))target.removeAttribute(attr.name);
    for(const attr of source.attributes)if(target.getAttribute(attr.name)!==attr.value)target.setAttribute(attr.name,attr.value);
  }
  function patch(target,source){
    for(let i=0;i<source.childNodes.length;i++){
      const next=source.childNodes[i];let old=target.childNodes[i];
      if(!old){target.append(next.cloneNode(true));continue;}
      if(old.nodeType!==next.nodeType||old.nodeName!==next.nodeName){target.replaceChild(next.cloneNode(true),old);continue;}
      if(next.nodeType===1){attrs(old,next);patch(old,next);}
      else if(old.nodeValue!==next.nodeValue)old.nodeValue=next.nodeValue;
    }
    while(target.childNodes.length>source.childNodes.length)target.lastChild.remove();
  }
  const styles=document.createElement('div');styles.hidden=true;document.head.append(styles);
  addEventListener('message',event=>{
    const data=event.data;if(event.source!==parent||data?.token!==token)return;
    if(data.type==='xgent-visual-layout'){layout(data);return;}
    if(!draft||data.type!=='xgent-visual-draft'||typeof data.source!=='string'||data.source.length>262144)return;
    const parsed=new DOMParser().parseFromString(data.source,'text/html');
    parsed.querySelectorAll('script,iframe,object,embed,base,link,meta').forEach(node=>node.remove());
    parsed.querySelectorAll('*').forEach(node=>{for(const attr of Array.from(node.attributes))if(/^on/i.test(attr.name)||/^\s*javascript:/i.test(attr.value))node.removeAttribute(attr.name);});
    const head=document.createElement('div');for(const style of parsed.head.querySelectorAll('style'))head.append(style.cloneNode(true));patch(styles,head);
    attrs(document.body,parsed.body);patch(document.body,parsed.body);schedule();
    parent.postMessage({type:'xgent-visual-painted',token,visible:!!document.body.querySelector('svg,canvas,img,article,main,section,div,button,h1,p')||!!document.body.textContent.trim()},'*');
  });
  addEventListener('resize',schedule);
  if(document.body)schedule();else addEventListener('DOMContentLoaded',schedule,{once:true});
  parent.postMessage({type:draft?'xgent-visual-draft-ready':'xgent-visual-ready',token},'*');
}

export function syncVisualPage(entry,descriptor,recordId,mount=entry.body){
  if(!descriptor||descriptor.version!==2)return;
  if(entry.visualPage){entry.visualPage.update(descriptor,recordId);return;}
  const pending=mount.querySelector('.visual-page-loading');
  const card=pending||document.createElement('section');card.className='visual-page visual-page-loading';card.setAttribute('aria-busy','true');
  const bar=document.createElement('header'),title=document.createElement('strong'),controls=document.createElement('div');
  const identity=document.createElement('span');identity.className='visual-page-identity';identity.append(title);bar.append(identity,controls);
  const expand=document.createElement('button');expand.type='button';expand.className='visual-page-icon';expand.innerHTML=expandIcon;expand.title='展开页面';expand.setAttribute('aria-label','展开页面');expand.setAttribute('aria-expanded','false');
  const sourceToggle=document.createElement('button');sourceToggle.type='button';sourceToggle.className='visual-page-icon';sourceToggle.innerHTML=codeIcon;sourceToggle.title='源码';sourceToggle.setAttribute('aria-label','源码');sourceToggle.setAttribute('aria-pressed','false');
  const copy=document.createElement('button');copy.type='button';copy.textContent='复制';copy.hidden=true;
  const download=document.createElement('a');download.textContent='下载';download.download='';download.hidden=true;
  const resetSize=document.createElement('button');resetSize.type='button';resetSize.className='visual-page-icon';resetSize.innerHTML=icon('M3 10a9 9 0 1 1 2 8M3 4v6h6');resetSize.title='恢复自动大小';resetSize.setAttribute('aria-label','恢复自动大小');resetSize.hidden=true;
  const retry=document.createElement('button');retry.type='button';retry.textContent='重新加载';retry.hidden=true;controls.append(sourceToggle,copy,download,retry,resetSize,expand);
  const status=document.createElement('span');status.className='visual-page-phase';identity.append(status);
  const viewport=pending?.querySelector('.visual-page-viewport')||document.createElement('div');viewport.className='visual-page-viewport';
  viewport.style.height='160px';
  const skeleton=viewport.querySelector('.visual-page-skeleton')||document.createElement('div');skeleton.className='visual-page-skeleton';skeleton.setAttribute('aria-hidden','true');
  if(!skeleton.children.length)skeleton.innerHTML='<span></span><span></span><span></span>';
  const sourceView=document.createElement('pre');sourceView.className='visual-page-source';sourceView.dataset.enhanced='1';sourceView.hidden=true;const code=document.createElement('code'),sourceText=document.createTextNode('');code.append(sourceText);sourceView.append(code);
  let frame=document.createElement('iframe');frame.className='visual-page-frame';frame.setAttribute('sandbox','allow-scripts');frame.referrerPolicy='no-referrer';
  const resize=document.createElement('button');resize.type='button';resize.className='visual-page-resize';resize.title='拖拽等比例调整大小，双击恢复自动大小';resize.setAttribute('aria-label','拖拽等比例调整页面大小');resize.innerHTML=icon('M5 19 19 5M5 13v6h6M13 5h6v6');
  const resizeBar=document.createElement('div');resizeBar.className='visual-page-resize-bar';resizeBar.append(resize);
  viewport.replaceChildren(frame,skeleton,sourceView);card.replaceChildren(bar,viewport,resizeBar);if(!pending)mount.replaceChildren(card);
  let controller,token='',revision=0,expanded=false,previousFocus,sourceMode=false;
  let current,owner=recordId,source=null,complete=false,draftReady=false,draftStarted=false,timer,blobUrl,destroyed=false,renderedSource=null,downloadKey;
  let sourcePaint=0,sourceScroll=0,sourceAtEnd=true,autoScrollTop=null,printedSource='',sentDraft=null,draftInFlight=false;
  let graphic=null,declaredGraphic=null,viewportPage=false,stageMinHeight=0,contentWidth=null,contentHeight=160,layoutWidth=560,layoutHeight=200,layoutQueued=false,lastLayout='';
  let manualSize=null,sizeKey='',drag=null;
  const area=card.closest('#log'),host=card.closest('.body')||mount;
  function readSizes(){try{const value=JSON.parse(localStorage.getItem('xgent-visual-sizes')||'{}');return value&&typeof value==='object'&&!Array.isArray(value)?value:{};}catch{return {};}}
  function syncSizeKey(){
    const row=card.closest('[data-record-id]'),cid=row?.dataset.presentationConversationId||new URLSearchParams(location.hash.split('?')[1]||'').get('conversation');
    if(!cid||owner==null)return;
    const next=cid+':'+owner+':'+(current?.index||0);if(next===sizeKey)return;
    sizeKey=next;
    if(manualSize){saveSize();return;}
    const stored=readSizes()[sizeKey];
    if(stored&&['width','logicalWidth','logicalHeight'].every(key=>Number.isFinite(stored[key])&&stored[key]>0&&stored[key]<=100000))manualSize=stored;
  }
  function saveSize(){
    if(!sizeKey)return;try{
      const values=readSizes();delete values[sizeKey];if(manualSize)values[sizeKey]=manualSize;
      for(const key of Object.keys(values).slice(0,-200))delete values[key];
      localStorage.setItem('xgent-visual-sizes',JSON.stringify(values));
    }catch{}
  }
  function resetSizing(){manualSize=null;saveSize();scheduleLayout();}
  function scheduleLayout(){if(!layoutQueued){layoutQueued=true;requestAnimationFrame(applyLayout);}}
  function applyLayout(){
    layoutQueued=false;if(destroyed||!card.isConnected)return;
    const availableWidth=Math.max(1,host.clientWidth||mount.clientWidth||320);
    const sideSpace=sourceMode||expanded?0:38;
    const readingHeight=area?.clientHeight||innerHeight;
    const maxHeight=Math.max(96,Math.min(440,readingHeight*.65));
    syncSizeKey();
    const heightLimit=expanded?Math.max(1,card.clientHeight-bar.offsetHeight):manualSize&&!sourceMode?Math.max(96,readingHeight-56):maxHeight;
    const widthLimit=expanded?Math.max(1,card.clientWidth-2):Math.max(1,availableWidth-sideSpace-2);
    const preferred=expanded?1:.8;
    let scale=preferred,displayWidth,displayHeight;
    if(manualSize&&!sourceMode&&!expanded){
      layoutWidth=manualSize.logicalWidth;layoutHeight=manualSize.logicalHeight;
      scale=Math.min(manualSize.width/layoutWidth,widthLimit/layoutWidth,heightLimit/layoutHeight);
      displayWidth=layoutWidth*scale;displayHeight=layoutHeight*scale;
    }else if(viewportPage&&!graphic){
      layoutWidth=expanded?widthLimit:Math.min(current?.width||800,1600);
      layoutHeight=expanded?Math.max(heightLimit,stageMinHeight):Math.max(current?.height||600,stageMinHeight);
      scale=Math.min(preferred,widthLimit/layoutWidth,heightLimit/layoutHeight);
      displayWidth=layoutWidth*scale;displayHeight=layoutHeight*scale;
    }else if(graphic){
      layoutWidth=graphic.width;layoutHeight=graphic.height;
      scale=Math.min(preferred,widthLimit/layoutWidth,heightLimit/layoutHeight);
      displayWidth=layoutWidth*scale;displayHeight=layoutHeight*scale;
    }else{
      layoutWidth=Math.min(contentWidth||Math.min(current?.width||560,800),widthLimit/preferred);
      displayWidth=layoutWidth*scale;
      displayHeight=Math.min(heightLimit,Math.max(36,contentHeight*scale));
      layoutHeight=displayHeight/scale;
    }
    card.classList.toggle('visual-graphic',!!graphic);
    card.classList.toggle('visual-viewport-page',viewportPage);
    resetSize.hidden=!manualSize;resizeBar.hidden=resize.hidden=sourceMode||expanded;
    if(!expanded){
      const toolbarMinimum=82+(manualSize?31:0)+(retry.hidden?0:75);
      const cardWidth=sourceMode?Math.min(availableWidth,680):Math.min(availableWidth-sideSpace,Math.max(toolbarMinimum,displayWidth+2));
      card.style.width=cardWidth+'px';
      viewport.style.width=(sourceMode?cardWidth-2:displayWidth)+'px';
      viewport.style.height=(sourceMode?Math.min(maxHeight,Math.max(240,displayHeight)):displayHeight)+'px';
    }else{card.style.width='';viewport.style.width='100%';viewport.style.height='';}
    const key=[layoutWidth,layoutHeight,scale,!!graphic,graphic?.embedded].join(':');
    for(const child of viewport.querySelectorAll('iframe')){
      child.style.width=layoutWidth+'px';child.style.height=layoutHeight+'px';child.style.setProperty('--visual-scale',String(scale));
    }
    if(key!==lastLayout){lastLayout=key;frame.contentWindow?.postMessage({type:'xgent-visual-layout',token,graphic:!!graphic&&!graphic.embedded,embedded:!!graphic?.embedded},'*');}
  }
  const layoutObserver=new ResizeObserver(scheduleLayout);layoutObserver.observe(host);if(area)layoutObserver.observe(area);
  window.addEventListener('resize',scheduleLayout);
  function finishResize(event){
    if(!drag||event.pointerId!==drag.id)return;drag=null;card.classList.remove('visual-page-resizing');saveSize();
    if(resize.hasPointerCapture(event.pointerId))resize.releasePointerCapture(event.pointerId);
  }
  resize.addEventListener('pointerdown',event=>{
    if(event.button!==0||expanded||sourceMode)return;
    event.preventDefault();event.stopPropagation();applyLayout();
    drag={id:event.pointerId,x:event.clientX,y:event.clientY,width:viewport.clientWidth,height:viewport.clientHeight,logicalWidth:layoutWidth,logicalHeight:layoutHeight};
    card.classList.add('visual-page-resizing');resize.setPointerCapture(event.pointerId);
  });
  resize.addEventListener('pointermove',event=>{
    if(!drag||event.pointerId!==drag.id)return;event.preventDefault();
    const ratio=drag.width/drag.height,delta=((event.clientX-drag.x)+(event.clientY-drag.y)/ratio)/(1+1/(ratio*ratio));
    manualSize={width:Math.max(82,drag.width+delta),logicalWidth:drag.logicalWidth,logicalHeight:drag.logicalHeight};scheduleLayout();
  });
  resize.addEventListener('pointerup',finishResize);resize.addEventListener('pointercancel',finishResize);resize.addEventListener('lostpointercapture',finishResize);
  resize.addEventListener('dblclick',resetSizing);resetSize.onclick=resetSizing;
  resize.addEventListener('keydown',event=>{
    if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)){
      event.preventDefault();applyLayout();const bigger=['ArrowRight','ArrowDown'].includes(event.key);
      manualSize={width:Math.max(82,viewport.clientWidth*(bigger?1.1:1/1.1)),logicalWidth:layoutWidth,logicalHeight:layoutHeight};saveSize();scheduleLayout();
    }else if(event.key==='Home'){event.preventDefault();resetSizing();}
  });
  sourceView.addEventListener('scroll',()=>{
    if(sourceView.scrollTop===autoScrollTop){autoScrollTop=null;return;}
    sourceAtEnd=sourceView.scrollHeight-sourceView.scrollTop-sourceView.clientHeight<32;
  },{passive:true});
  function sourceSelected(){const selection=getSelection();return selection&&!selection.isCollapsed&&(sourceView.contains(selection.anchorNode)||sourceView.contains(selection.focusNode));}
  function paintSource(){
    sourcePaint=0;if(destroyed||!sourceMode||source===null||printedSource===source)return;
    const append=source.startsWith(printedSource),selected=sourceSelected();
    // Append to the same text node so a range in existing code stays selected.
    // A rare rewrite waits until the reader finishes selecting the old source.
    if(!append&&selected)return;
    const follow=!selected&&(printedSource?sourceAtEnd:!complete);
    if(append)sourceText.appendData(source.slice(printedSource.length));else sourceText.replaceData(0,sourceText.length,source);
    printedSource=source;
    if(follow&&!sourceScroll)sourceScroll=requestAnimationFrame(()=>{
      sourceScroll=0;if(sourceMode&&sourceAtEnd&&!sourceSelected()){sourceView.scrollTop=sourceView.scrollHeight;autoScrollTop=sourceView.scrollTop;}
    });
  }
  function scheduleSource(){if(sourceMode&&!sourcePaint)sourcePaint=requestAnimationFrame(paintSource);}
  function setSourceMode(value){
    sourceMode=value;sourceView.hidden=!value;viewport.querySelectorAll('iframe').forEach(node=>node.hidden=value);card.classList.toggle('visual-source-mode',value);
    resizeBar.hidden=resize.hidden=value||expanded;
    copy.hidden=download.hidden=!value;sourceToggle.title=value?'预览':'源码';sourceToggle.setAttribute('aria-label',sourceToggle.title);sourceToggle.setAttribute('aria-pressed',String(value));
    scheduleLayout();
    if(value){clearTimeout(timer);timer=null;cancelAnimationFrame(sourcePaint);sourcePaint=0;paintSource();}
    else{cancelAnimationFrame(sourcePaint);cancelAnimationFrame(sourceScroll);sourcePaint=sourceScroll=0;if(complete)renderComplete();else renderDraft();}
  }
  function setExpanded(value){
    expanded=value;card.classList.toggle('visual-page-expanded',value);card.setAttribute('role',value?'dialog':'region');
    resizeBar.hidden=resize.hidden=value||sourceMode;
    card.setAttribute('aria-modal',String(value));expand.innerHTML=value?collapseIcon:expandIcon;expand.title=value?'关闭页面':'展开页面';expand.setAttribute('aria-label',expand.title);expand.setAttribute('aria-expanded',String(value));
    if(value){previousFocus=document.activeElement;expand.focus({preventScroll:true});}
    else{previousFocus?.focus({preventScroll:true});if(requested(owner,current.index||0)){const url=new URL(location.href),params=new URLSearchParams(url.hash.split('?')[1]||'');params.delete('visual_full');url.hash='/chat?'+params;history.replaceState(null,'',url);}}
    scheduleLayout();
  }
  function showPreview(){card.classList.remove('visual-page-loading','visual-page-error');card.classList.add('visual-page-ready');card.setAttribute('aria-busy',String(!complete));}
  function updateDownload(){
    const key=current.source_url||(complete?source:null);if(key===downloadKey)return;downloadKey=key;
    if(blobUrl){URL.revokeObjectURL(blobUrl);blobUrl=null;}
    if(current.source_url)download.href=current.source_url;
    else if(complete&&source){blobUrl=URL.createObjectURL(new Blob([source],{type:current.format==='svg'?'image/svg+xml':'text/html'}));download.href=blobUrl;}
    else download.removeAttribute('href');
    download.download='page.'+(current.format||'html');
  }
  function flushDraft(){
    timer=null;if(destroyed||complete||sourceMode||!draftReady||draftInFlight||sentDraft===source)return;
    draftInFlight=true;sentDraft=source;
    frame.contentWindow.postMessage({type:'xgent-visual-draft',token,source:source||''},'*');
  }
  function renderDraft(){
    if(sourceMode||destroyed)return;
    if(!draftStarted){
      draftStarted=true;draftReady=false;draftInFlight=false;sentDraft=null;token=crypto.randomUUID();
      frame.srcdoc='<!doctype html><html'+(graphic&&!graphic.embedded?' data-xgent-graphic':'')+'><head>'+base+'</head><body><script>('+pageRuntime.toString()+')('+JSON.stringify(token)+',true);</script></body></html>';
    }
    if(!timer)timer=setTimeout(flushDraft,120);
  }
  function renderComplete(){
    if(sourceMode||destroyed)return;
    if(renderedSource===source)return;renderedSource=source;clearTimeout(timer);timer=null;draftReady=false;
    token=crypto.randomUUID();const activeToken=token;
    const bridge='<script>('+pageRuntime.toString()+')('+JSON.stringify(token)+',false);</script>';
    // Keep the last draft visible until the complete page is ready.
    const next=document.createElement('iframe');next.className='visual-page-frame visual-page-staging';next.title=current.title||'渲染页面';next.setAttribute('sandbox','allow-scripts');next.referrerPolicy='no-referrer';next.hidden=sourceMode;
    const old=frame;frame=next;viewport.insertBefore(next,old);old.className='visual-page-previous';
    next.onload=()=>{if(destroyed||token!==activeToken)return;requestAnimationFrame(()=>{if(destroyed||token!==activeToken)return;next.classList.remove('visual-page-staging');old.remove();showPreview();status.hidden=true;});};
    next.srcdoc='<!doctype html><html'+(graphic&&!graphic.embedded?' data-xgent-graphic':'')+'><head>'+base+bridge+'</head><body>'+source+'</body></html>';
    lastLayout='';scheduleLayout();
  }
  function accept(page){
    if(typeof page.source!=='string'||page.source.length>262144)throw new Error('页面内容无效');
    const isComplete=page.streaming!==true;
    if(complete&&!isComplete)return;
    const unchanged=source===page.source&&complete===isComplete;
    source=page.source;complete=isComplete;if(!unchanged)scheduleSource();
    if(!unchanged){declaredGraphic=drawingSize(source,current.format);if(declaredGraphic)graphic=declaredGraphic;}
    scheduleLayout();
    status.textContent=complete?'准备预览…':'生成中…';status.hidden=complete&&(sourceMode||renderedSource===source);
    if(!unchanged)card.setAttribute('aria-busy','true');frame.title=current.title||'渲染页面';updateDownload();
    if(!unchanged){if(sourceMode){card.setAttribute('aria-busy',String(!complete));}else if(complete)renderComplete();else renderDraft();}
  }
  async function load(){
    controller?.abort();controller=new AbortController();const activeRevision=++revision;retry.hidden=true;
    try{
      const response=await fetch(current.url,{credentials:'same-origin',signal:controller.signal});const page=await response.json();
      if(!response.ok)throw new Error(page.error||'页面读取失败');
      if(activeRevision!==revision||destroyed||!card.isConnected)return;
      if(page.version!==2)throw new Error('页面内容无效');accept({...page,streaming:false});
    }catch(error){if(error.name==='AbortError')return;status.hidden=false;status.textContent=error.message;retry.hidden=false;card.classList.add('visual-page-error');card.classList.remove('visual-page-loading');card.setAttribute('aria-busy','false');}
  }
  const instance={
    get frame(){return frame;},
    update(page,id){
      current=page;if(id!=null)owner=id;syncSizeKey();title.textContent=page.title||'渲染页面';card.setAttribute('aria-label',title.textContent);
      if(typeof page.source==='string'){controller?.abort();revision++;accept(page);}
      else if(source===null)load();else updateDownload();
      if(requested(owner,page.index||0))setExpanded(true);
    },
    expand:()=>setExpanded(true),
    destroy:()=>{destroyed=true;clearTimeout(timer);cancelAnimationFrame(sourcePaint);cancelAnimationFrame(sourceScroll);layoutObserver.disconnect();window.removeEventListener('resize',scheduleLayout);document.removeEventListener('selectionchange',scheduleSource);controller?.abort();if(blobUrl)URL.revokeObjectURL(blobUrl);instances.delete(instance);card.remove();},
    receive(data){
      if(data.token!==token)return;
      if(data.type==='xgent-visual-draft-ready'){draftReady=true;lastLayout='';scheduleLayout();flushDraft();}
      else if(data.type==='xgent-visual-ready'){lastLayout='';scheduleLayout();}
      else if(data.type==='xgent-visual-painted'){draftInFlight=false;if(data.visible)showPreview();if(sentDraft!==source&&!sourceMode)renderDraft();}
      else if(data.type==='xgent-visual-size'&&Number.isFinite(data.height)&&data.height>0&&!declaredGraphic){
        const size=data.drawing;
        graphic=size&&Number.isFinite(size.width+size.height)&&size.width>0&&size.height>0?
          {width:Math.min(100000,size.width),height:Math.min(100000,size.height),embedded:size.embedded===true}:null;
        contentHeight=Math.min(100000,data.height);
        viewportPage=data.viewportPage===true;
        stageMinHeight=viewportPage&&Number.isFinite(data.minHeight)?Math.max(0,Math.min(100000,data.minHeight)):0;
        if(viewportPage&&manualSize&&manualSize.logicalHeight<Math.max(stageMinHeight,current?.height||600)){
          manualSize={...manualSize,logicalHeight:Math.max(stageMinHeight,current?.height||600)};saveSize();
        }
        if(data.compact&&Number.isFinite(data.width)&&data.width>0)contentWidth=data.width;
        scheduleLayout();
      }
    },
    close:()=>{if(expanded)setExpanded(false);}
  };
  entry.visualPage=instance;instances.add(instance);
  expand.onclick=()=>setExpanded(!expanded);retry.onclick=()=>{renderedSource=null;if(current.url)load();else if(complete)renderComplete();else{draftStarted=false;renderDraft();}};
  sourceToggle.onclick=()=>setSourceMode(!sourceMode);
  copy.onclick=async()=>{try{await navigator.clipboard.writeText(source||'');copy.textContent='已复制';setTimeout(()=>copy.textContent='复制',1600);}catch{copy.textContent='复制失败';}};
  document.addEventListener('selectionchange',scheduleSource);
  instance.update(descriptor,recordId);
}

export function syncReplyPages(entry,pages,recordId,display=entry.webDisplay){
  const descriptors=new Map((Array.isArray(pages)?pages:[]).map(page=>[page.index,page]));
  for(const segment of display?.segments||[]){
    if(!Number.isSafeInteger(segment.visual_index)||typeof segment.visual_source!=='string')continue;
    const index=segment.visual_index;
    descriptors.set(index,{...descriptors.get(index),version:2,index,title:segment.visual_title,format:segment.visual_format,source:segment.visual_source,streaming:segment.visual_pending===true});
  }
  const mounted=entry.visualPages||=new Map(),keep=new Set();
  for(const [index,descriptor] of descriptors){
    if(!Number.isSafeInteger(index)||index<0||index>=4)continue;
    const slot=entry.body.querySelector('[data-visual-index="'+index+'"]');if(!slot)continue;
    keep.add(index);let child=mounted.get(index);
    if(child?.body!==slot){child?.visualPage?.destroy();child={body:slot};mounted.set(index,child);}
    syncVisualPage(child,descriptor,recordId,slot);
  }
  for(const [index,child] of mounted)if(!keep.has(index)){child.visualPage?.destroy();mounted.delete(index);}
}
window.addEventListener('message',event=>{if(!event.data?.type?.startsWith('xgent-visual-'))return;for(const instance of instances)if(event.source===instance.frame.contentWindow)instance.receive(event.data);});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const instance of instances)instance.close();});
window.addEventListener('xgent-auth-expired',()=>{for(const instance of instances)instance.destroy();});
