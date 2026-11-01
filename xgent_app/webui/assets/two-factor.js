import {el,button,field,api,message,copyText} from './components.js';

const endpoint='/api/security/2fa';
export async function twoFactorCard({card,dialog,closeDialog,submit}){
  let status=await api(endpoint);
  const body=el('div'),controls=el('div',{class:'wb-detail-actions'});
  const panel=card('两步验证（2FA）',body,controls);
  async function refresh(){status=await api(endpoint);draw();}
  function draw(){
    body.replaceChildren(el('p',{},status.enabled?'已开启：网页密码登录还需动态验证码或恢复码。':'未开启。可手动添加验证器 App，绑定验证成功后才启用。'),
      el('p',{class:'wb-note'},'电报授权用户免密登录不要求第二次验证。'),
      ...(status.enabled?[el('p',{class:'wb-note'},'剩余恢复码：'+status.recovery_remaining+' 个')]:[]));
    controls.replaceChildren(...(status.enabled?[button('重新生成恢复码',()=>reauth('recovery')),button('关闭两步验证',()=>reauth('disable'),'danger')]:[button('添加验证器',setup,'primary')]));
  }
  function recoveryCodes(codes){
    const content=el('div',{},el('p',{},'两步验证已生效。恢复码仅在本次显示，每个只能使用一次；请保存到安全位置。'),
      el('pre',{class:'wb-pre'},codes.join('\n')),
      el('div',{class:'wb-detail-actions'},button('复制恢复码',async()=>{await copyText(codes.join('\n'));}),button('下载恢复码',()=>{
        const url=URL.createObjectURL(new Blob(['XGent Web 恢复码\n'+codes.join('\n')+'\n'],{type:'text/plain;charset=utf-8'}));
        const a=el('a',{href:url,download:'XGent-Web恢复码.txt'});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }),button('已保存',()=>{closeDialog();refresh();},'primary')));
    dialog('保存恢复码',content);
  }
  function setup(){
    const box=el('div'),form=el('form',{},field('当前访问密码','password','','password','重新确认密码后生成绑定二维码。'),el('button',{type:'submit',class:'wb-btn primary'},'生成绑定信息'));
    form.elements.password.autocomplete='current-password';form.elements.password.required=true;form.elements.password.setAttribute('aria-label','当前访问密码');
    box.append(form);dialog('添加验证器 App',box);
    form.onsubmit=event=>{event.preventDefault();submit(form,async data=>{
      const binding=await api(endpoint+'/setup',{data:{password:data.password}});form.reset();
      const verify=el('form',{},el('p',{},'用验证器 App 扫码，或手动添加下方密钥；再输入六位验证码完成绑定。'),
        el('img',{src:binding.qr,alt:'验证器绑定二维码',width:210,height:210}),
        el('details',{},el('summary',{},'手动添加密钥'),el('code',{},binding.secret),button('复制密钥',()=>copyText(binding.secret))),
        field('六位动态验证码','code','','text'),el('button',{type:'submit',class:'wb-btn primary'},'验证并启用'));
      verify.elements.code.autocomplete='one-time-code';verify.elements.code.inputMode='numeric';verify.elements.code.maxLength=6;verify.elements.code.required=true;
      verify.onsubmit=e=>{e.preventDefault();submit(verify,async d=>{
        const result=await api(endpoint+'/confirm',{data:{setup_id:binding.setup_id,code:d.code}});
        binding.secret='';binding.qr='';verify.reset();box.replaceChildren();await refresh();recoveryCodes(result.recovery_codes);
      });};box.replaceChildren(verify);
    });};
  }
  function reauth(action){
    const form=el('form',{},field('当前访问密码','password','','password'),field('动态验证码或恢复码','code','','text'),
      el('button',{type:'submit',class:'wb-btn '+(action==='disable'?'danger':'primary')},action==='disable'?'确认关闭':'重新生成'));
    form.elements.password.autocomplete='current-password';form.elements.code.autocomplete='one-time-code';
    form.elements.password.required=form.elements.code.required=true;
    dialog(action==='disable'?'关闭两步验证':'重新生成恢复码',form);
    form.onsubmit=e=>{e.preventDefault();submit(form,async d=>{
      const result=await api(endpoint+'/'+action,{data:{password:d.password,code:d.code}});form.reset();
      await refresh();if(result.recovery_codes)recoveryCodes(result.recovery_codes);else{closeDialog();body.append(message('两步验证已关闭','success'));}
    });};
  }
  draw();return panel;
}
