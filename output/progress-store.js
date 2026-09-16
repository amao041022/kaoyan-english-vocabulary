/* 所有本地页面使用同一地址的隐藏页面持久化数据，事务避免多标签写入互相覆盖。 */
(() => {
  'use strict';
  const C=StudyCore;
  const dbReady=new Promise((resolve,reject)=>{
    const req=indexedDB.open(C.PROJECT,1);
    req.onupgradeneeded=()=>req.result.createObjectStore('state');
    req.onsuccess=()=>resolve(req.result);
    req.onerror=()=>reject(new Error('浏览器未允许保存学习记录，请检查本地存储设置'));
  });
  function checkTargets(cards){
    for(const card of cards||[]){if(!card.targetId)continue;const unit=VOCAB_STUDY.units.find(u=>u.id===card.targetId);if(!unit||PersonalCore.normalize(unit.lemma)!==PersonalCore.normalize(card.lemma)||PersonalCore.meaningKey(unit.gloss)!==PersonalCore.meaningKey(card.meaning))throw new Error('备份关联的原有义项与当前词库不一致，请先使用相同版本词库');}
  }
  async function access(change) {
    const db=await dbReady;
    return new Promise((resolve,reject)=>{
      const tx=db.transaction('state',change?'readwrite':'readonly'); const store=tx.objectStore('state');
      let result, failure;
      store.get('progress').onsuccess=e=>{
        try { result=e.target.result||C.emptyState(); if(change){result=change(result);checkTargets(result.personal);store.put(result,'progress');} }
        catch(error){failure=error;tx.abort();}
      };
      tx.oncomplete=()=>resolve(result);
      tx.onabort=tx.onerror=()=>reject(failure||new Error('进度保存失败；请导出备份并检查浏览器存储空间'));
    });
  }
  window.addEventListener('message',async event=>{
    // file: 页面消息的 origin 可能为 null；只接收自己的父窗口，且只接受限定操作。
    if(event.source!==parent||event.data?.channel!==C.PROJECT||!Number.isInteger(event.data.id))return;
    const {id,op,payload}=event.data;
    try {
      let state;
      if(op==='load'||op==='export')state=await access();
      else if(op==='record')state=await access(s=>{
        const e=C.validateEvent(payload.event), existing=s.events.find(x=>x.id===e.id);
        if(existing&&JSON.stringify(existing)!==JSON.stringify(e))throw new Error('本题已提交，不能重复改变答案');
        if(e.kind==='answer'&&s.session?.id!==payload.session?.id)throw new Error('另一页面已开始新的练习，请刷新并继续最新一轮');
        if(!existing)s.events.push(e);
        if(e.kind==='answer')s.session=payload.session; return s;
      });
      else if(op==='settings')state=await access(s=>{
        const dailyNew=payload.dailyNew;
        if(!Number.isInteger(dailyNew)||dailyNew<1||dailyNew>100)throw new Error('每日新词数须为1—100');
        s.settings={dailyNew};return s;
      });
      else if(op==='view')state=await access(s=>{
        if(!['index','full','repeats'].includes(payload.page))throw new Error('页面标识无效');
        s.views[payload.page]=payload.value; return s;
      });
      else if(op==='session')state=await access(s=>{s.session=payload;return s;});
      else if(op==='personal-add')state=await access(s=>{s.personal=PersonalCore.mergeCards(s.personal||[],[payload]);return s;});
      else if(op==='personal-import')state=await access(s=>{s.personal=PersonalCore.mergeCards(s.personal||[],payload);return s;});
      else if(op==='import')state=await access(s=>C.mergeBackup(s,payload));
      else throw new Error('不支持的进度操作');
      parent.postMessage({channel:C.PROJECT,id,state},'*');
    }catch(error){parent.postMessage({channel:C.PROJECT,id,error:error.message},'*');}
  });
})();
