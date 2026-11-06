/* App data must not be inferred as a saved login or personal-information field. */
const ignoreAttributes=['data-lpignore','data-1p-ignore','data-bwignore'];
export function preventAutofill(node){
  if(!['FORM','INPUT','TEXTAREA','SELECT'].includes(node.tagName))return node;
  if(node.tagName==='INPUT'&&['button','submit','reset','checkbox','radio','range','file','hidden'].includes(node.type))return node;
  const purpose=node.getAttribute('autocomplete');
  if(purpose==='current-password'||purpose==='one-time-code')return node;
  node.setAttribute('autocomplete',purpose||((node.tagName==='INPUT'&&node.type==='password')?'new-password':'off'));
  for(const name of ignoreAttributes)node.setAttribute(name,'true');
  return node;
}
export function allowCredentialAutofill(node,purpose){
  node.setAttribute('autocomplete',purpose);
  for(const name of ignoreAttributes)node.removeAttribute(name);
  if(node.form){node.form.setAttribute('autocomplete','on');for(const name of ignoreAttributes)node.form.removeAttribute(name);}
  return node;
}
export function guardSearchAutofill(input){
  preventAutofill(input);
  const autofilled=()=>{for(const selector of [':autofill',':-webkit-autofill']){try{if(input.matches(selector))return true;}catch{}}return false;};
  let value=autofilled()?input.defaultValue:input.value;
  if(autofilled())input.value=value;
  const restore=event=>{
    if(!autofilled()&&event?.animationName!=='xgent-search-autofill')return false;
    input.value=value;event?.stopImmediatePropagation();return true;
  };
  input.addEventListener('focus',()=>{restore();value=input.value;});
  input.addEventListener('blur',()=>{if(!restore())value=input.value;});
  input.addEventListener('input',event=>{if(!restore(event))value=input.value;},true);
  input.addEventListener('animationstart',restore);
  return {remember(){if(!restore())value=input.value;}};
}
