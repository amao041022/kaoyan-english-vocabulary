/* 共用的状态标签、记录弹窗与备份操作。 */
(() => {
  'use strict';
  const C=StudyCore,D=VOCAB_STUDY,units=new Map(D.units.map(u=>[u.id,u]));
  let states={};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const uid=()=>crypto.randomUUID ? crypto.randomUUID() : 'id-'+Date.now()+'-'+Math.random().toString(36).slice(2);
  const date=at=>at?new Date(at).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'尚无记录';
  function error(err) {const banner=document.querySelector('#save-warning');banner.hidden=false;banner.textContent=err.message+'。本次操作尚未确认保存，请重试或导出进度。';}
  function badge(id){const status=(states[id]||C.fresh()).status;return `<button class="mastery" data-unit-id="${esc(id)}" data-state="${status}" type="button"><span>${C.LABELS[status]}</span></button>`;}
  function audio(src,label){return `<button type="button" class="speak" ${src.startsWith('tts:')?'data-speech-text="'+esc(src.slice(4))+'"':'data-audio="'+esc(src)+'"'} data-label="${esc(label)}" aria-label="美音朗读${esc(label)}">▶ ${esc(label)}</button>`;}
  function highlight(text,forms){
    const alternatives=[...forms].sort((a,b)=>b.length-a.length).map(s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|');
    const re=new RegExp('(?<![A-Za-z])(?:'+alternatives+')(?![A-Za-z])','gi');
    let out='',last=0;for(const match of text.matchAll(re)){out+=esc(text.slice(last,match.index))+'<mark>'+esc(match[0])+'</mark>';last=match.index+match[0].length;}return out+esc(text.slice(last));
  }
  function contextHTML(unit,context){
    const collocations=context.collocations.length?`<section class="lesson-part"><h3>搭配与用法</h3>${context.collocations.map(c=>`<div class="collocation"><span lang="en">${esc(c.text)}</span> ${audio(c.audio,'搭配')}<span>${esc(c.meaning)}</span><small>${esc(c.source)} · ${esc(c.kind)}</small></div>`).join('')}</section>`:'';
    return `<section class="lesson-part"><h3>词义</h3><div class="lesson-word"><strong lang="en">${esc(unit.word)}</strong>${audio(unit.audio,'单词')}<span class="ipa">${esc(context.ipa)}</span></div><p class="meaning">${esc(context.meaning)}</p><p class="note">原文词形：${esc(context.form)}　常见词义：${esc(context.common)}</p></section><section class="lesson-part"><h3>${context.location==='词典收词；尚无原文例句'?'尚未选择原文例句':'原文例句'}</h3><p lang="en" class="lesson-sentence">${highlight(context.example,unit.forms)} ${audio(context.audio,'例句')}</p><p>${esc(context.translation)}</p><p class="note">${esc(context.section_title)} · ${esc(context.location)} · ${context.photos.map(p=>`<a href="${esc(p.url)}" target="_blank" rel="noopener">原图</a>`).join(' / ')}</p>${context.note?`<p class="note">${esc(context.note)}</p>`:''}</section>${collocations}`;
  }
  function refresh(){
    units.clear();D.units.forEach(u=>units.set(u.id,u));
    states=C.fold(Progress.state.events);
    document.querySelectorAll('.mastery[data-unit-id]').forEach(el=>{
      const state=states[el.dataset.unitId]||C.fresh();el.dataset.state=state.status;
      const span=el.querySelector('span');if(span)span.textContent=C.LABELS[state.status];
      el.title=`${C.LABELS[state.status]} · 下次复习：${date(state.due)}（点击查看）`;
    });
  }
  function modal(html){
    document.querySelector('#study-dialog')?.remove();
    const dialog=document.createElement('dialog');dialog.id='study-dialog';dialog.innerHTML=`<button type="button" class="dialog-close" aria-label="关闭">×</button>${html}`;
    document.body.append(dialog);dialog.querySelector('.dialog-close').onclick=()=>dialog.close();
    dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});dialog.showModal();return dialog;
  }
  async function download(){
    const data=await Progress.export();const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='生词学习进度_'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
  }
  document.addEventListener('click',async event=>{
    const tag=event.target.closest('.mastery[data-unit-id]');
    if(tag){
      const unit=units.get(tag.dataset.unitId);if(!unit)return;
      const s=states[unit.id]||C.fresh();
      const controls=s.status==='familiar'?'<button data-lower="fuzzy">调为模糊</button><button data-lower="unknown">调为不认识</button>':s.status==='fuzzy'?'<button data-lower="unknown">调为不认识</button>':'';
      const dialog=modal(`<h2>${esc(unit.word)} · ${C.LABELS[s.status]}</h2><p>${esc(unit.gloss)}</p><p>最近练习：${date(s.lastAt)}</p><p>下次复习：${s.due?date(s.due):'加入新词学习'}</p><p>已作答 ${s.attempts} 次</p><div class="actions">${controls}<a class="button" href="背词练习.html?unit=${encodeURIComponent(unit.id)}">练习此词</a></div><p class="note">同词同义共用记录，不同义项分别学习。</p>`);
      dialog.querySelectorAll('[data-lower]').forEach(button=>button.onclick=async()=>{
        button.disabled=true;
        try {await Progress.save('record',{event:{id:uid(),unitId:unit.id,kind:'downgrade',at:Date.now(),level:button.dataset.lower},session:Progress.state.session});dialog.close();}
        catch(err){button.disabled=false;error(err);}
      });
    }
    if(event.target.closest('[data-export-progress]'))try{await download();}catch(err){error(err);}
  });
  document.addEventListener('change',async event=>{
    if(!event.target.matches('[data-import-progress]'))return;
    const file=event.target.files[0];event.target.value='';if(!file)return;
    try {
      if(file.size>30*1024*1024)throw new Error('备份文件不能超过30 MB');
      const incoming=C.validateBackup(JSON.parse(await file.text()));C.mergeBackup(Progress.state,incoming);
      const oldIds=new Set(Progress.state.events.map(e=>e.id));const newCount=incoming.events.filter(e=>!oldIds.has(e.id)).length;
      const dialog=modal(`<h2>导入学习进度</h2><p>检测到 ${incoming.events.length} 条记录，其中 ${newCount} 条为新增。已有记录保留，相同记录不会重复计入。</p><p>备份同时包含 ${incoming.personal.length} 个个人词义。每日新词设置将采用备份中的 ${incoming.settings.dailyNew} 个。</p><button id="confirm-import" class="primary">合并导入</button>`);
      dialog.querySelector('#confirm-import').onclick=async event=>{
        event.target.disabled=true;
        try{await Progress.save('import',incoming);dialog.close();window.dispatchEvent(new Event('progressimported'));}
        catch(err){event.target.disabled=false;error(err);}
      };
    }catch(err){error(new Error('导入未完成：'+err.message));}
  });
  window.addEventListener('progresschange',refresh);
  window.addEventListener('progresserror',e=>error(e.detail));
  const controls=document.querySelector('.audio-toolbar');
  if(controls)new ResizeObserver(()=>document.documentElement.style.setProperty('--audio-height',controls.getBoundingClientRect().height+'px')).observe(controls);
  window.StudyUI={esc,uid,date,badge,audio,highlight,contextHTML,modal,error,units,get states(){return states;},backupControls:'<details class="backup-menu"><summary>词库与进度备份</summary><div><button type="button" data-export-progress>导出词库与进度</button><label class="button">导入词库与进度<input type="file" accept=".json,application/json" data-import-progress hidden></label><p class="note">进度保存在当前浏览器。备份包含个人词库和学习进度。更换设备或清理浏览器前，请导出备份。</p></div></details>'};
  window.studyReady=Progress.load().then(()=>{refresh();return Progress.state;}).catch(err=>{error(err);throw err;});
})();
