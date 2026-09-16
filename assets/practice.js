/* 一题一屏：作答与自评分开保存，刷新后可继续尚未确认的题目。 */
(() => {
  'use strict';
  const app=document.querySelector('#study-app');if(!app)return;
  const U=StudyUI,C=StudyCore,D=VOCAB_STUDY;
  let session=null,screen='home',busy=false;
  const stopAudio=()=>window.VocabAudio?.stop();
  function home(){
    screen='home';session=null;
    const counts={new:0,unknown:0,fuzzy:0,familiar:0};let due=0,learnedToday=0;
    for(const u of D.units){const s=U.states[u.id]||C.fresh();counts[s.status]++;if(s.status!=='new'&&s.due<=Date.now())due++;if(s.firstAt&&C.day(s.firstAt)===C.day(Date.now()))learnedToday++;}
    const unfinished=Progress.state.session;
    app.innerHTML=`<div class="study-intro"><div><p class="eyebrow">把阅读里遇到的词，记在原来的语境里</p><h2>今天，从这些词开始</h2><p class="note">${D.units.length} 个学习单元 · 中英双向练习 · 先复习，再学新词</p></div>${U.backupControls}</div><div class="study-stats"><div><b>${due}</b><span>到期待复习</span></div><div><b>${learnedToday} / ${Progress.state.settings.dailyNew}</b><span>今日新学 / 计划</span></div><div><b>${counts.familiar}</b><span>已熟悉</span></div></div><div class="level-summary">${Object.entries(counts).map(([k,n])=>`<span data-state="${k}">${C.LABELS[k]} ${n}</span>`).join('')}</div>${unfinished?'<div class="resume-panel"><strong>还有一轮未完成的练习</strong><button id="resume-session" class="primary">继续上次练习</button></div>':''}<div class="study-settings"><label>每日新词 <input id="daily-new" type="number" min="1" max="100" value="${Progress.state.settings.dailyNew}"> 个</label><button id="save-daily">保存计划</button><span id="daily-message" class="note"></span></div><div class="start-actions"><button class="primary" data-start="today">开始今日学习</button><button data-start="review">只复习到期词</button></div><div class="article-study"><label for="study-section">按文章练习</label><select id="study-section"><option value="">请选择文章</option>${D.sections.map(s=>`<option value="${U.esc(s.id)}">${U.esc(s.title)}</option>`).join('')}</select><button data-start="article">开始文章练习</button><p class="note">文章练习可提前复习已学词；提前答对不延长间隔。新词仍计入每日计划。</p></div><details class="rules"><summary>熟悉程度和复习规则</summary><p>初次答对、猜对或使用提示记为模糊；不同日期，两种方向均无提示答对且确认知道，才记为熟悉。</p><p>不认识：约10分钟后；模糊：次日；熟悉后依次为3、7、14、30、60天。答错会回退。本轮错词最多额外回练两次。</p><p>这些间隔是可调整的学习规则。关闭网页也不会丢失到期任务。</p></details>`;
    app.querySelector('#save-daily').onclick=async event=>{
      event.target.disabled=true;
      try {await Progress.save('settings',{dailyNew:Number(app.querySelector('#daily-new').value)});home();app.querySelector('#daily-message').textContent='计划已保存';}
      catch(err){U.error(err);}finally{event.target.disabled=false;}
    };
    app.querySelectorAll('[data-start]').forEach(button=>button.onclick=()=>{
      const mode=button.dataset.start,section=mode==='article'?app.querySelector('#study-section').value:'';
      if(mode==='article'&&!section){app.querySelector('#study-section').focus();return;}
      const run=()=>start(mode,section).catch(U.error);
      if(Progress.state.session){const dialog=U.modal('<h2>开始新一轮？</h2><p>已保存的答题记录保留，未完成的题目队列将被替换。也可以关闭此窗口，继续上次练习。</p><button class="primary" id="start-fresh">开始新一轮</button>');dialog.querySelector('#start-fresh').onclick=()=>{dialog.close();run();};}else run();
    });
    app.querySelector('#resume-session')?.addEventListener('click',()=>{
      const saved=Progress.state.session;
      if(!saved?.queue?.length||saved.queue.some(item=>!U.units.has(item.unitId))){U.error(new Error('上次练习中有当前词库不存在的词，请开始新一轮；已学记录保留'));return;}
      session=structuredClone(saved);screen='practice';showQuestion().catch(U.error);
    });
  }
  async function persist(){await Progress.save('session',session);}
  async function start(mode,section='',ids=null){
    if(busy)return;busy=true;
    try{
    const queue=ids||C.plan(D.units,Progress.state.events,mode,section,Progress.state.settings.dailyNew,Date.now());
    if(!queue.length){U.modal('<h2>本次没有待练习的词</h2><p>当前范围没有到期词，或今日新词计划已完成。你可以选择其他文章、调整新词计划，或稍后再来复习。</p>');return;}
    stopAudio();
    session={id:U.uid(),startedAt:Date.now(),mode,section,queue:queue.map(unitId=>({unitId,retry:0})),index:0,question:null,results:{},missed:[],newIds:queue.filter(id=>!U.states[id]),attempts:0};
    screen='practice';await persist();await showQuestion();
    }finally{busy=false;}
  }
  function contextIndex(unit,state){
    const possible=unit.contexts.map((c,i)=>i).filter(i=>!session.section||unit.contexts[i].section_id===session.section);
    const current=possible.indexOf(state.contextIndex);return possible[(current+1)%possible.length]??0;
  }
  async function showQuestion(){
    stopAudio();
    if(session.index>=session.queue.length){await finish(true);return;}
    const item=session.queue[session.index],unit=U.units.get(item.unitId);
    if(!session.question){
      const state=U.states[unit.id]||C.fresh();
      const direction=state.lastDirection==='en-zh'?'zh-en':state.lastDirection==='zh-en'?'en-zh':session.index%2?'zh-en':'en-zh';
      session.question={id:U.uid(),unitId:unit.id,...C.makeQuestion(unit,D.units,direction),contextIndex:contextIndex(unit,state),hinted:false,phase:'question',graded:false,retry:item.retry};
      await persist();
    }
    renderQuestion();
  }
  function renderQuestion(){
    screen='practice';const q=session.question,unit=U.units.get(q.unitId),context=unit.contexts[q.contextIndex];
    const progress=Math.round(session.index/session.queue.length*100);
    app.innerHTML=`<div class="practice-heading"><span>第 ${session.index+1} / ${session.queue.length} 题${q.retry?' · 错词回练':''}</span><div><button id="pause-session">保存并返回</button><button id="end-session">结束本轮</button></div></div><div class="session-progress" role="progressbar" aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100"><span style="width:${progress}%"></span></div><div class="question-card"><p class="eyebrow">${q.mode==='flip'?(q.direction==='en-zh'?'看英文，回忆所选词义':'看所选词义，回忆英文'):(q.direction==='en-zh'?'看英文，选择文中含义':'看文中含义，选择英文')}${q.mode==='flip'?' · 翻卡自测':''}</p><h2 class="question-prompt" lang="${q.direction==='en-zh'?'en':'zh-CN'}">${U.esc(q.direction==='en-zh'?unit.word:unit.gloss)}${q.direction==='en-zh'?U.audio(unit.audio,'单词'):''}</h2><p class="question-source">${U.esc(context.section_title)} · ${U.esc(context.location)}</p><div id="question-body"></div></div>`;
    app.querySelector('#pause-session').onclick=async()=>{if(busy)return;busy=true;stopAudio();try{await persist();home();}catch(err){U.error(err);}finally{busy=false;}};
    app.querySelector('#end-session').onclick=()=>finish().catch(U.error);
    const body=app.querySelector('#question-body');
    if(q.phase==='question'){
      body.innerHTML=q.mode==='choice'?`<div class="answer-options">${q.options.map((option,i)=>`<button class="answer-option" data-answer="${U.esc(option.id)}"><span class="option-number">${i+1}</span><span>${U.esc(option.text)}</span></button>`).join('')}</div>`:'<p class="note">本词暂不使用选择题。先在心里回忆答案，再翻卡核对。</p><button class="primary" id="flip-card">显示词义与讲解</button>';
      body.insertAdjacentHTML('beforeend',`<div class="question-tools"><button id="unknown-answer">不认识</button><button id="show-hint" ${q.hinted?'disabled':''}>查看原句提示</button><span class="note">使用提示后，本次最高记为模糊。</span></div><p class="hint" ${q.hinted?'':'hidden'} lang="en">${U.highlight(context.example,unit.forms)}</p><p class="note">${q.mode==='choice'?'也可按数字键1—4作答。':''}</p>`);
      body.querySelectorAll('[data-answer]').forEach(b=>b.onclick=()=>submit(b.dataset.answer).catch(U.error));
      body.querySelector('#unknown-answer').onclick=()=>submit(null).catch(U.error);
      body.querySelector('#show-hint').onclick=async()=>{if(busy)return;busy=true;try{q.hinted=true;await persist();renderQuestion();}catch(err){U.error(err);}finally{busy=false;}};
      body.querySelector('#flip-card')?.addEventListener('click',()=>submit('flip').catch(U.error));
    }else{
      const correct=q.chosen===unit.id;
      body.innerHTML=`<div class="answer-result ${q.chosen==='flip'?'':correct?'correct':'incorrect'}">${q.chosen==='flip'?'核对你刚才想到的答案':correct?'答对了':'正确答案：'+U.esc(q.direction==='en-zh'?unit.gloss:unit.word)}${q.chosen&&q.chosen!=='flip'&&!correct?'<small>你选择了：'+U.esc(q.options.find(o=>o.id===q.chosen)?.text||'')+'</small>':''}</div>${U.contextHTML(unit,context)}<div class="grading" id="grading"></div>`;
      const grading=body.querySelector('#grading');
      if(q.graded){
        const s=U.states[unit.id]||C.fresh();
        grading.innerHTML=`<p>已记录为 ${U.badge(unit.id)} · 下次复习：${U.date(s.due)}</p><button class="primary" id="next-question">下一题 →</button>`;
        grading.querySelector('#next-question').onclick=async()=>{if(busy)return;busy=true;const before=structuredClone(session);try{session.index++;session.question=null;await persist();await showQuestion();}catch(err){session=before;renderQuestion();U.error(err);}finally{busy=false;}};
      }else if(q.chosen!==unit.id&&q.chosen!=='flip'){
        grading.innerHTML='<p>本次答错尚未确认保存。</p><button id="retry-save">重新保存</button>';
        grading.querySelector('#retry-save').onclick=()=>grade('wrong').catch(U.error);
      }else{
        grading.innerHTML='<h3>看到答案之前，你是否确定？</h3><div class="actions">'+(q.chosen==='flip'?'<button data-grade="wrong">没有想起来</button>':'')+'<button data-grade="uncertain">猜对的／不确定</button><button class="primary" data-grade="known">确实知道</button></div><p class="note">答后阅读讲解不降低等级；初次答对仍需在之后的日期验证。</p>';
        grading.querySelectorAll('[data-grade]').forEach(b=>b.onclick=()=>grade(b.dataset.grade).catch(U.error));
      }
    }
  }
  async function submit(chosen){
    if(busy||session.question.phase!=='question')return;busy=true;
    try{
      const q=session.question;q.chosen=chosen;q.phase='feedback';
      await persist();
      if(chosen!==q.unitId&&chosen!=='flip')await commit('wrong');
      renderQuestion();
    }catch(err){renderQuestion();throw err;}finally{busy=false;}
  }
  async function commit(result){
    const q=session.question;if(q.graded)return;
    if(q.chosen!==q.unitId&&q.chosen!=='flip')result='wrong';
    if(q.hinted&&result==='known')result='uncertain';
    q.at ||= Date.now();
    const before=structuredClone(session);
    q.graded=true;q.result=result;session.attempts++;session.results[q.unitId]=result;
    if(result==='wrong'){
      if(!session.missed.includes(q.unitId))session.missed.push(q.unitId);
      if(q.retry<2)session.queue.splice(Math.min(session.index+4,session.queue.length),0,{unitId:q.unitId,retry:q.retry+1});
    }
    q.at ||= Date.now();
    try{await Progress.save('record',{event:{id:q.id,unitId:q.unitId,at:q.at,kind:'answer',direction:q.direction,result,hinted:q.hinted,contextIndex:q.contextIndex},session});}
    catch(err){session=before;throw err;}
  }
  async function grade(result){if(busy||session.question.graded)return;busy=true;try{await commit(result);renderQuestion();}finally{busy=false;}}
  async function finish(force=false){
    if(busy&&!force)return;const previousBusy=busy;busy=true;stopAudio();
    try{
    if(session?.question?.phase==='feedback'&&!session.question.graded)await commit('uncertain');
    const completed=session;if(!completed){home();return;}
    await Progress.save('session',null);session=null;screen='summary';
    const ids=Object.keys(completed.results),levels={unknown:0,fuzzy:0,familiar:0};for(const id of ids)levels[(U.states[id]||C.fresh()).status]++;
    const newCount=ids.filter(id=>completed.newIds.includes(id)).length;
    app.innerHTML=`<div class="study-summary"><p class="eyebrow">本轮学习已保存</p><h2>给记忆留一点时间</h2><p>新学 ${newCount} 个 · 复习 ${ids.length-newCount} 个 · 共作答 ${completed.attempts} 次</p><div class="level-summary">${Object.entries(levels).map(([k,n])=>`<span data-state="${k}">${C.LABELS[k]} ${n}</span>`).join('')}</div><div class="actions"><button class="primary" id="back-home">返回学习首页</button>${completed.missed.length?'<button id="retry-missed">再练本次错词</button>':''}</div>${U.backupControls}</div>`;
    app.querySelector('#back-home').onclick=home;
    app.querySelector('#retry-missed')?.addEventListener('click',()=>start('mistakes','',completed.missed).catch(U.error));
    }finally{busy=previousBusy;}
  }
  document.addEventListener('keydown',event=>{
    if(screen!=='practice'||busy||session?.question.phase!=='question'||event.ctrlKey||event.altKey||event.metaKey||event.repeat||event.target.closest('input,select,textarea,dialog'))return;
    const index=Number(event.key)-1;if(index>=0&&index<4&&session.question.options[index]){event.preventDefault();submit(session.question.options[index].id).catch(U.error);}
  });
  window.addEventListener('progressimported',()=>{if(screen==='home')home();});
  window.addEventListener('focus',()=>{if(screen==='home')Progress.load().then(home).catch(U.error);});
  studyReady.then(()=>{
    home();const requested=new URLSearchParams(location.search).get('unit');
    if(requested&&U.units.has(requested)&&!Progress.state.session)start('word','',[requested]).catch(U.error);
  }).catch(()=>{});
})();
