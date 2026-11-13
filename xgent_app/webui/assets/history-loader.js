// 历史读取可以重试；取消、切换对话与永久错误必须立即退出。
function cancelled(signal) {
  if(signal?.aborted)throw new DOMException('历史加载已取消','AbortError');
}

function wait(ms,signal) {
  cancelled(signal);
  return new Promise((resolve,reject)=>{
    const finish=()=>{signal?.removeEventListener('abort',abort);resolve();};
    const timer=setTimeout(finish,ms);
    const abort=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);reject(new DOMException('历史加载已取消','AbortError'));};
    signal?.addEventListener('abort',abort,{once:true});
  });
}

export function canRetryHistory(error) {
  return !!error.retryable||error.name==='TimeoutError'||error instanceof TypeError||
    [408,429].includes(error.status)||(error.status>=500&&error.status<600);
}

export async function readHistory(request,{signal,onState,timeoutMs=12000,retryDelays=[600,1400]}={}) {
  for(let attempt=0;;attempt++){
    cancelled(signal);
    const controller=new AbortController();
    const abort=()=>controller.abort();
    signal?.addEventListener('abort',abort,{once:true});
    let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeoutMs);
    onState?.({attempt,retrying:false});
    try{
      const data=await request(controller.signal);
      cancelled(signal);
      if(timedOut)throw new Error('读取超时');
      if(!data||!Array.isArray(data.messages)){
        const error=new Error('历史记录未完整接收');error.retryable=true;throw error;
      }
      return data;
    }catch(cause){
      cancelled(signal);
      const error=timedOut?Object.assign(new Error('网络响应较慢，历史记录暂未返回'),{name:'TimeoutError'}):cause;
      if(!canRetryHistory(error)||attempt>=retryDelays.length||navigator.onLine===false)throw error;
      onState?.({attempt:attempt+1,retrying:true});
      await wait(retryDelays[attempt],signal);
    }finally{
      clearTimeout(timer);signal?.removeEventListener('abort',abort);
    }
  }
}
