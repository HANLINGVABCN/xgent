import {readPreference,writePreference} from './ui.js';
import {DEFAULT_PALETTE,normalizePalette} from './theme-presets.js';

let telegram=null,palette=normalizePalette(readPreference('xgent-theme-palette')),lastApplied='';
const media=matchMedia('(prefers-color-scheme:dark)');
const savedMode=()=>readPreference('xgent-theme','system');
export const getThemePalette=()=>palette;

function syncChrome(){
  const dark=document.body.classList.contains('dark');
  document.documentElement.dataset.theme=dark?'dark':'light';
  document.documentElement.dataset.palette=palette;
  const button=document.getElementById('btn-theme'),mode=dark?'sun':'moon';
  if(button&&button.dataset.themeIcon!==mode){
    button.innerHTML='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-'+mode+'"/></svg>';
    button.dataset.themeIcon=mode;
  }
  const style=getComputedStyle(document.documentElement),color=name=>style.getPropertyValue(name).trim();
  const colors={background:color('--bg'),foreground:color('--text'),cursor:color('--accent'),cursorAccent:color('--bg'),selectionBackground:color('--accent-ring')};
  for(const meta of document.querySelectorAll('meta[name="theme-color"]'))meta.content=colors.background;
  const signature=JSON.stringify([dark,palette,colors]);
  if(signature===lastApplied)return;
  lastApplied=signature;
  const detail={dark,palette,colors};
  window.dispatchEvent(new CustomEvent('xgent-theme-applied',{detail}));
  document.getElementById('terminal-iframe')?.contentWindow?.postMessage({type:'xgent-theme',...detail},location.origin);
}
function apply(mode){
  const dark=mode==='dark'||mode==='system'&&(telegram?.colorScheme?telegram.colorScheme==='dark':media.matches);
  document.body.classList.toggle('dark',dark);syncChrome();
}
export function setThemeMode(mode){writePreference('xgent-theme',mode==='system'?null:mode);apply(mode);}
export function setThemePalette(value){
  palette=normalizePalette(value);writePreference('xgent-theme-palette',palette);syncChrome();
}
export function acceptTheme(value){
  palette=normalizePalette(value.palette||palette);
  document.body.classList.toggle('dark',!!value.dark);syncChrome();
}
export function initializeTheme({telegram:host,toggle,onToggle}={}){
  telegram=host;apply(savedMode());
  toggle?.addEventListener('click',()=>{setThemeMode(document.body.classList.contains('dark')?'light':'dark');onToggle?.();});
}
media.addEventListener('change',()=>{if(savedMode()==='system')apply('system');});
window.addEventListener('storage',event=>{
  if(event.key==='xgent-theme-palette'){palette=normalizePalette(event.newValue);syncChrome();}
  if(event.key==='xgent-theme')apply(savedMode());
});
new MutationObserver(syncChrome).observe(document.body,{attributes:true,attributeFilter:['class']});
window.XGentTheme={setPalette:setThemePalette,setMode:setThemeMode,get palette(){return palette;},defaultPalette:DEFAULT_PALETTE};
