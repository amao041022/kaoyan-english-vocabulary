/* 页面与同一持久化入口通信；失败显式提示，不伪装成已保存。 */
(() => {
  'use strict';
  const C=StudyCore, pending=new Map(); let sequence=0, cached=C.emptyState();
  const frame=document.createElement('iframe'); frame.hidden=true;frame.title='学习进度存储';frame.src='progress-store.html';
  const ready=new Promise((resolve,reject)=>{
    frame.addEventListener('load',resolve,{once:true});
    frame.addEventListener('error',()=>reject(new Error('无法加载进度存储页面')),{once:true});
    setTimeout(()=>reject(new Error('学习进度加载超时，请检查项目文件是否完整')),8000);
  });
  document.body.append(frame);
  window.addEventListener('message',event=>{
    if(event.source!==frame.contentWindow||event.data?.channel!==C.PROJECT)return;
    const task=pending.get(event.data.id);if(!task)return;
    pending.delete(event.data.id);clearTimeout(task.timer);
    if(event.data.error)task.reject(new Error(event.data.error));
    else {cached=event.data.state;task.resolve(cached);}
  });
  async function request(op,payload) {
    await ready;
    return new Promise((resolve,reject)=>{
      const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('进度操作超时，请先保留页面再重试'));},10000);
      pending.set(id,{resolve,reject,timer});frame.contentWindow.postMessage({channel:C.PROJECT,id,op,payload},'*');
    });
  }
  function notify(){window.dispatchEvent(new CustomEvent('progresschange',{detail:cached}));}
  window.Progress={
    get state(){return cached;},
    async load(){await request('load');notify();return cached;},
    async save(op,payload){await request(op,payload);notify();return cached;},
    async export(){await request('load');return {schema:1,project:C.PROJECT,events:cached.events,settings:cached.settings,personal:cached.personal||[]};}
  };
  window.addEventListener('focus',()=>Progress.load().catch(error=>window.dispatchEvent(new CustomEvent('progresserror',{detail:error}))));
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)Progress.load().catch(error=>window.dispatchEvent(new CustomEvent('progresserror',{detail:error})));});
})();
