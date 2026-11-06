/* Presentation only: no requests, stored conversation state or model decisions. */
import {preventAutofill} from './input-policy.js';
export const $ = id => document.getElementById(id);
export function readPreference(key,fallback=null){try{return localStorage.getItem(key)??fallback;}catch{return fallback;}}
export function writePreference(key,value){try{if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,String(value));}catch{}}
let dialogDismissInstalled=false;
export function installDialogDismissal(){
  if(dialogDismissInstalled)return;dialogDismissInstalled=true;
  let pressed=null;
  const outside=(node,event)=>{const box=node.getBoundingClientRect();return event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom;};
  document.addEventListener('pointerdown',event=>{
    const node=event.target instanceof HTMLDialogElement?event.target:null;
    pressed=node?.open&&node.id!=='login'&&outside(node,event)?{node,x:event.clientX,y:event.clientY}:null;
  },true);
  document.addEventListener('pointerup',event=>{
    const saved=pressed;pressed=null;
    if(!saved||!saved.node.open||event.target!==saved.node||!outside(saved.node,event)||Math.hypot(event.clientX-saved.x,event.clientY-saved.y)>6)return;
    const cancel=new Event('cancel',{cancelable:true});
    if(saved.node.dispatchEvent(cancel))saved.node.close();
  },true);
}

export function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === 'class') node.className = value;
    else if (name === 'text') node.textContent = value;
    else if (name.startsWith('on')) node.addEventListener(name.slice(2), value);
    else if (['checked', 'disabled', 'hidden', 'selected'].includes(name)) node[name] = !!value;
    else if (value !== null && value !== undefined) node.setAttribute(name, value);
  }
  preventAutofill(node);
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const paths = {
  plus: 'M12 5v14M5 12h14',
  search: 'M21 21l-4.4-4.4M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0',
  close: 'm6 6 12 12M18 6 6 18',
  chevron: 'm9 5 7 7-7 7',
  arrow: 'M5 12h14m-5-5 5 5-5 5',
  check: 'm5 12 4 4L19 6',
  copy: 'M8 8h12v12H8zM16 4H4v12',
  file: 'M5 3h9l5 5v13H5zM14 3v6h5M9 13h6M9 17h6',
  clock: 'M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  settings: 'M4 6h16M4 12h16M4 18h16M9 3v6M16 9v6M8 15v6',
  chart: 'M4 20V10M10 20V4M16 20v-8M22 20H2',
  model: 'm12 3 9 5v8l-9 5-9-5V8zM3 8l9 5 9-5M12 13v8',
  chat: 'M4 4h16v12H8l-4 4z',
  archive: 'M4 8h16v12H4zM3 4h18v4H3zM10 12h4',
  exit: 'M10 4H4v16h6M14 8l4 4-4 4M8 12h10',
  info: 'M12 11v6M12 7h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  refresh: 'M20 7V3m0 4h-4M4 17v4m0-4h4M20 7a9 9 0 0 0-15-2M4 17a9 9 0 0 0 15 2',
};
export function icon(nameOrPath, className = '') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', 'icon ' + className);
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', paths[nameOrPath] || nameOrPath);
  svg.append(path);
  return svg;
}

export const button = (text, fn, kind = '') => el('button', {class: 'wb-btn ' + kind, type: 'button', onclick: fn}, text);
export const fmt = number => number == null ? '—' : Number(number).toLocaleString('zh-CN');
export const stamp = number => number ? new Date(number * 1000).toLocaleString('zh-CN', {hour12: false}) : '—';
export const bytes = number => number == null ? '—' : number > 1048576 ? (number / 1048576).toFixed(1) + ' MiB' : number > 1024 ? (number / 1024).toFixed(1) + ' KiB' : number + ' B';

export function message(text, kind = 'error') {
  return el('div', {class: 'wb-' + kind, role: kind === 'error' ? 'alert' : 'status'},
    icon(kind === 'loading' ? 'refresh' : kind === 'success' ? 'check' : 'info', 'notice-icon'), el('span', {}, text));
}
export function empty(title, detail, action) {
  return el('div', {class: 'wb-empty'}, el('span', {class: 'wb-empty-icon', 'aria-hidden': 'true'}, icon('file')),
    el('h3', {}, title), el('p', {}, detail), action);
}
export function field(label, name, value = '', type = 'text', note = '') {
  const input = el(type === 'textarea' ? 'textarea' : 'input', {name, type: type === 'textarea' ? null : type});
  input.value = value ?? '';
  return el('label', {class: 'wb-field'}, el('span', {}, label), input, note ? el('small', {}, note) : null);
}
export function select(label, name, options, value) {
  return el('label', {class: 'wb-field'}, el('span', {}, label),
    el('select', {name}, options.map(option => el('option', {value: option.value ?? option, selected: (option.value ?? option) === value}, option.label ?? option))));
}
export function check(label, name, value = false) {
  const toggle=['agent_mode','web_enabled','terminal_enabled','reduce','enabled'].includes(name);
  return el('label', {class: 'wb-check'}, el('input', {name, type: 'checkbox', role:toggle?'switch':null, checked: value}), el('span', {}, label));
}
export function table(headings, rows) {
  return el('div', {class: 'wb-table-wrap', tabindex: '0'}, el('table', {class: 'wb-table'},
    el('thead', {}, el('tr', {}, headings.map(heading => el('th', {scope: 'col'}, heading)))),
    el('tbody', {}, rows.map(row => el('tr', {}, row.map((value, index) => el('td', {'data-label': headings[index]}, value)))))));
}
export function formData(form) {
  const data = Object.fromEntries(new FormData(form));
  form.querySelectorAll('input[type=checkbox]').forEach(input => data[input.name] = input.checked);
  return data;
}
export const heading = (title, description, actions = []) => el('div', {class: 'wb-page-head'},
  el('div', {class: 'wb-page-heading'}, el('h1', {}, title), description ? el('p', {}, description) : null), el('div', {class: 'wb-actions'}, actions));
export const card = (title, ...children) => el('section', {class: 'wb-card'}, el('h3', {}, title), children);
export const toolbar = (...children) => el('div', {class: 'wb-toolbar'}, children);
export const actions = (...children) => el('div', {class: 'wb-actions'}, children);
