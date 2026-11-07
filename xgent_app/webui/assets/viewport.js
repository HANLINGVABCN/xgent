/* Fit the app to the visible mobile viewport, including the keyboard's pan. */
export function installViewportFit({resizeEditor}={}){
  const viewport=window.visualViewport,root=document.documentElement,body=document.body;
  const mobile=matchMedia('(max-width: 767px), (pointer: coarse)');
  let scheduled=false,fullHeight=innerHeight,last='';
  const telegram=window.Telegram?.WebApp;
  function update(){
    scheduled=false;
    // Pinch zoom changes the visual viewport too. Keep native browser zoom.
    const active=mobile.matches&&(!viewport||Math.abs(viewport.scale-1)<.02);
    if(!active){
      body.classList.remove('viewport-fit','wb-keyboard');
      root.style.removeProperty('--app-viewport-height');root.style.removeProperty('--app-viewport-top');
      last='';resizeEditor?.();return;
    }
    let height=Math.min(innerHeight,viewport?.height||innerHeight);
    if(telegram?.initData&&telegram.viewportHeight>0)height=Math.min(height,telegram.viewportHeight);
    const top=Math.max(0,Math.min(viewport?.offsetTop||0,innerHeight-height));
    const editing=document.activeElement?.matches('textarea,input:not([type=button]):not([type=checkbox]):not([type=radio]),[contenteditable=true]');
    if(!editing)fullHeight=Math.max(fullHeight,innerHeight,height);
    const keyboard=!!editing&&(fullHeight-height>80||innerHeight-height-top>80);
    const key=[height.toFixed(2),top.toFixed(2),keyboard].join(':');
    if(key===last)return;last=key;
    root.style.setProperty('--app-viewport-height',height.toFixed(2)+'px');
    root.style.setProperty('--app-viewport-top',top.toFixed(2)+'px');
    body.classList.add('viewport-fit');body.classList.toggle('wb-keyboard',keyboard);
    resizeEditor?.();
  }
  function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(update);}}
  viewport?.addEventListener('resize',schedule);viewport?.addEventListener('scroll',schedule);
  window.addEventListener('resize',schedule);mobile.addEventListener('change',schedule);
  document.addEventListener('focusin',schedule);document.addEventListener('focusout',schedule);
  window.addEventListener('orientationchange',()=>{fullHeight=innerHeight;schedule();});
  if(telegram?.initData)telegram.onEvent?.('viewportChanged',schedule);
  schedule();
}
