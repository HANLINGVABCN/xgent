import {el} from './ui.js';

export const settingsSections=[['appearance','外观'],['conversation','对话与记忆'],['agent','Agent'],['web','Web 与安全'],['data','数据与备份'],['health','系统状态']];
export const settingsPanels=[...settingsSections,['tasks','任务'],['files','文件与输出'],['models','模型与技能'],['usage','用量'],['archive','已归档']];
export const panelNames=Object.fromEntries(settingsPanels);
export const appLabels={chat:'对话',settings:'设置'};
export const appPages=[['chat','对话','M4 4h16v12H8l-4 4V4'],['tasks','任务','M8 5h12M8 12h12M8 19h12M3 5h1M3 12h1M3 19h1'],['files','文件与输出','M3 5h7l2 3h9v12H3V5'],['models','模型与技能','M12 3l9 5v8l-9 5-9-5V8l9-5M3 8l9 5 9-5M12 13v8'],['usage','用量','M4 20V10M10 20V4M16 20v-8M22 20H2'],['settings','设置','M4 6h16M4 12h16M4 18h16M9 3v6M16 9v6M8 15v6'],['archive','已归档','M4 8h16v12H4zM3 4h18v4H3zM10 12h4']];

// All content choices are buttons in one retained navigation. No links or route jumps.
export function settingsNavigation({onSelect,onSearch,onLogout}){
  const nav=el('nav',{class:'wb-settings-nav','aria-label':'设置选项'});
  for(const [panel,label] of settingsPanels){
    const attrs={type:'button',class:'wb-nav-item','data-panel':panel,'aria-controls':'settings-content',onclick:event=>onSelect(panel,event.detail===0)};
    if(panel==='archive')attrs['data-archive']='1';
    nav.append(el('button',attrs,el('span',{},label)));
  }
  nav.append(el('button',{type:'button',class:'wb-nav-item','data-action':'search',onclick:onSearch},el('span',{},'全局搜索')),
    el('button',{type:'button',class:'wb-nav-item','data-action':'logout',onclick:onLogout},el('span',{},'退出登录')));
  nav.addEventListener('keydown',event=>{
    if(!['ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    const items=[...nav.querySelectorAll('button')],current=items.indexOf(document.activeElement);if(current<0)return;
    event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?items.length-1:(current+(['ArrowUp','ArrowLeft'].includes(event.key)?-1:1)+items.length)%items.length;
    items[index].focus();items[index].scrollIntoView({block:'nearest',inline:'nearest'});
  });
  return el('aside',{class:'wb-settings-side'},nav);
}
