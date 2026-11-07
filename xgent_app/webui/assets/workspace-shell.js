import {$, el, icon,installDialogDismissal} from './ui.js';
import {appLabels as names} from './navigation.js';
installDialogDismissal();
$('workspace-search-open')?.addEventListener('click', () => $('btn-search')?.click());
const searchShortcut=document.querySelector('.header-search kbd');
if(searchShortcut)searchShortcut.textContent=/Mac|iPhone|iPad/.test(navigator.platform)?'⌘ F':'Ctrl F';
document.querySelector('.skip-link')?.addEventListener('click',event=>{
  event.preventDefault();$(document.body.dataset.page==='chat'?'input':'settings-content')?.focus({preventScroll:true});
});

function updateRoute() {
  const route = document.body.dataset.page || 'chat';
  if ($('workspace-context')) $('workspace-context').textContent = names[route] || names.chat;
  for (const node of document.querySelectorAll('#workspace-settings')) {
    const active = (node.dataset.route || 'settings') === route;
    node.classList.toggle('active', active);
    if (active) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
  }
  const skip = document.querySelector('.skip-link');
  if (skip) skip.href = route === 'chat' ? '#input' : '#wb-page';
}
new MutationObserver(updateRoute).observe(document.body, {attributes: true, attributeFilter: ['data-page']});
updateRoute();

// Tooltips are one shared surface. They never observe or rebuild message content.
const touch=matchMedia('(hover: none) and (pointer: coarse)');
const tooltip = el('div', {id: 'workspace-tooltip', role: 'tooltip', hidden: true});
document.body.append(tooltip);
let tooltipTarget = null, tooltipTimer = null;
function hideTooltip() {
  clearTimeout(tooltipTimer);
  tooltip.hidden = true;
  if (tooltipTarget) {
    tooltipTarget.removeAttribute('aria-describedby');
    if (tooltipTarget.dataset.tooltipTitle) {
      tooltipTarget.title = tooltipTarget.dataset.tooltipTitle;
      delete tooltipTarget.dataset.tooltipTitle;
    }
  }
  tooltipTarget = null;
}
function queueTooltip(target) {
  if (!target?.title || target.disabled || touch.matches) return;
  hideTooltip();
  tooltipTarget = target;
  target.dataset.tooltipTitle = target.title;
  target.removeAttribute('title');
  tooltipTimer = setTimeout(() => {
    if (tooltipTarget !== target || !target.isConnected) return;
    tooltip.textContent = target.dataset.tooltipTitle;
    tooltip.hidden = false;
    const rect = target.getBoundingClientRect(), box = tooltip.getBoundingClientRect();
    const above = rect.top > box.height + 16;
    tooltip.style.top = (above ? rect.top - box.height - 8 : rect.bottom + 8) + 'px';
    tooltip.style.left = Math.max(8, Math.min(innerWidth - box.width - 8, rect.left + (rect.width - box.width) / 2)) + 'px';
    target.setAttribute('aria-describedby', 'workspace-tooltip');
  }, 500);
}
const tooltipSelector = '#header button[title],#composer button[title],.conv-icon-button[title]';
document.addEventListener('pointerover', event => {
  const target = event.target.closest(tooltipSelector);
  if (target && !target.contains(event.relatedTarget)) queueTooltip(target);
});
document.addEventListener('pointerout', event => {
  if (tooltipTarget?.contains(event.target) && !tooltipTarget.contains(event.relatedTarget)) hideTooltip();
});
document.addEventListener('focusin', event => { if (event.target.matches(tooltipSelector) && event.target.matches(':focus-visible')) queueTooltip(event.target); });
document.addEventListener('focusout', hideTooltip);
document.addEventListener('pointerdown', hideTooltip, {passive: true});
document.addEventListener('keydown', hideTooltip);
window.addEventListener('resize', hideTooltip);
window.addEventListener('hashchange', hideTooltip);
