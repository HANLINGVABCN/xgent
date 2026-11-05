/* Theme identifiers are stable; the visible order and names are independent of avatar choice. */
export const DEFAULT_PALETTE='neon';
export const themePresets=Object.freeze([
  {id:'neon',label:'a',name:'流光蓝紫',description:'蓝紫流光 · 冷调底色',colors:['#38bdf8','#818cf8','#c084fc'],background:'#f5f6fb',sidebar:'#eef0f8',accent:'#6262b8'},
  {id:'slate',label:'b',name:'终端雾蓝',description:'雾蓝灰阶 · 清晰克制',colors:['#e2e8f0','#94a3b8','#38bdf8'],background:'#f3f6f8',sidebar:'#eaf0f4',accent:'#277a9a'},
  {id:'gold',label:'c',name:'黑曜钛金',description:'钛金点缀 · 温润底色',colors:['#f59e0b','#fbbf24','#fef08a'],background:'#f8f6f1',sidebar:'#f0ece3',accent:'#906720'},
  {id:'mono',label:'d',name:'黑白极简',description:'纯粹黑白 · 鲜明对比',colors:['#202020','#777777','#d4d4d4'],background:'#fafafa',sidebar:'#f0f0f0',accent:'#242424'},
  {id:'duo',label:'e',name:'冷暖对撞',description:'冰蓝与橙 · 轻快鲜活',colors:['#38bdf8','#229aca','#fb923c'],background:'#f5f8fb',sidebar:'#eaf2f8',accent:'#287aab'},
  {id:'forest',label:'f',name:'黑客翠绿',description:'翠绿微光 · 沉静自然',colors:['#10b981','#34d399','#7bdcb0'],background:'#f6f7f4',sidebar:'#eef1eb',accent:'#28765b'},
]);
export function normalizePalette(value){return themePresets.some(preset=>preset.id===value)?value:DEFAULT_PALETTE;}
