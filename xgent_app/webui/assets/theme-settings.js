import {el,icon,readPreference} from './ui.js';
import {themePresets} from './theme-presets.js';
import {getThemePalette,setThemePalette} from './theme.js';
function syncPaletteChoices(list=document){const selected=getThemePalette();for(const item of list.querySelectorAll('[data-palette-choice]')){const active=item.dataset.paletteChoice===selected;item.setAttribute('aria-checked',String(active));item.tabIndex=active?0:-1;}for(const select of list.querySelectorAll('.theme-settings-card [name=theme]'))select.value=readPreference('xgent-theme','system');}
window.addEventListener('xgent-theme-applied',()=>syncPaletteChoices());
const content=document.getElementById('settings-content');
if(content)new MutationObserver(()=>syncPaletteChoices()).observe(content,{childList:true});

export function themePicker(){
  const list=el('div',{class:'theme-grid',role:'radiogroup','aria-label':'界面主题'});
  for(const preset of themePresets){
    const swatch=el('span',{class:'theme-swatch','aria-hidden':'true'},el('i',{class:'theme-mini-sidebar'}),
      el('i',{class:'theme-mini-line'}),el('i',{class:'theme-mini-line second'}),el('i',{class:'theme-mini-message'}),el('i',{class:'theme-mini-input'}));
    const option=el('button',{type:'button',class:'theme-option',role:'radio','data-palette-choice':preset.id,'aria-label':preset.name,
      title:preset.description,onclick:()=>setThemePalette(preset.id)},swatch,
      el('span',{class:'theme-option-label'},el('span',{class:'theme-letter'},preset.label),el('strong',{},preset.name),
        preset.id==='neon'?el('small',{class:'theme-default'},'默认'):null,icon('check','theme-selected')),
      el('span',{class:'theme-description'},preset.description));
    for(const [name,value] of Object.entries({'--preview-bg':preset.background,'--preview-sidebar':preset.sidebar,'--preview-accent':preset.accent,
      '--preview-gradient':'linear-gradient(135deg,'+preset.colors.join(',')+')'}))option.style.setProperty(name,value);
    list.append(option);
  }
  list.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
    const choices=[...list.children],current=choices.indexOf(document.activeElement);if(current<0)return;
    event.preventDefault();const columns=getComputedStyle(list).gridTemplateColumns.split(' ').length;
    const delta=event.key==='ArrowUp'?-columns:event.key==='ArrowDown'?columns:event.key==='ArrowLeft'?-1:1;
    const index=event.key==='Home'?0:event.key==='End'?choices.length-1:(current+delta+choices.length)%choices.length;
    choices[index].focus();setThemePalette(choices[index].dataset.paletteChoice);
  });
  syncPaletteChoices(list);
  return list;
}
