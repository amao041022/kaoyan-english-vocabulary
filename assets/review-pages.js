/* 总复习与完整版共用筛选、位置恢复和掌握程度。 */
(() => {
  'use strict';
  const U=StudyUI,D=VOCAB_STUDY,query=document.querySelector('#query');
  if(!query){if(!document.querySelector('#study-app')){const spot=document.querySelector('.intro');spot.insertAdjacentHTML('afterend',U.backupControls);}return;}
  const page=document.querySelector('.detail-view')?'full':'index';
  const toolbar=document.querySelector('.toolbar'),year=document.querySelector('#year'),repeat=document.querySelector('#only-repeat');
  toolbar.insertAdjacentHTML('beforeend','<select id="article-filter" aria-label="筛选文章"><option value="">全部文章</option></select><select id="mastery-filter" aria-label="筛选掌握程度"><option value="">全部掌握程度</option><option value="new">未学</option><option value="unknown">不认识</option><option value="fuzzy">模糊</option><option value="familiar">熟悉</option></select><label><input type="checkbox" id="hide-meaning"> 隐藏词义自测</label><button id="reveal-meanings" type="button" hidden>显示全部词义</button>');
  toolbar.insertAdjacentHTML('afterend',U.backupControls);
  const article=document.querySelector('#article-filter'),mastery=document.querySelector('#mastery-filter'),hide=document.querySelector('#hide-meaning'),reveal=document.querySelector('#reveal-meanings');
  let ready=false,timer;
  function refreshYears(){const previous=year.value;const groups=[...new Set([...D.sections.map(s=>s.group),...document.querySelectorAll('.entry')].map(v=>typeof v==='string'?v:v.dataset.year))];year.innerHTML='<option value="">全部来源</option>'+groups.map(g=>`<option value="${U.esc(g)}">${U.esc(g)}</option>`).join('');year.value=previous;}
  window.addEventListener('personalrowschange',()=>{refreshYears();articles();if(ready)filter();});
  function articles(){
    const previous=article.value;
    article.innerHTML='<option value="">全部文章</option>'+D.sections.filter(s=>!year.value||s.group===year.value).map(s=>`<option value="${U.esc(s.id)}">${U.esc(s.title)}</option>`).join('');
    if([...article.options].some(o=>o.value===previous))article.value=previous;
  }
  function filter(){
    const term=query.value.trim().toLocaleLowerCase();let visible=0;
    document.querySelectorAll('.entry').forEach(row=>{
      const status=(U.states[row.dataset.studyId]||StudyCore.fresh()).status;
      row.hidden=!!((year.value&&!(row.dataset.years?JSON.parse(row.dataset.years):[row.dataset.year]).includes(year.value))||(article.value&&!(row.dataset.sections?JSON.parse(row.dataset.sections):[row.dataset.section]).includes(article.value))||(repeat.checked&&row.dataset.repeated!=='yes')||(mastery.value&&status!==mastery.value)||(term&&!row.dataset.search.includes(term)));
      if(!row.hidden)visible++;
    });
    document.querySelectorAll('section').forEach(section=>{if(section.querySelector('.entry'))section.hidden=![...section.querySelectorAll('.entry')].some(row=>!row.hidden);});
    document.querySelector('#count').textContent='显示 '+visible+' 条';document.querySelector('#empty').hidden=visible!==0;
    document.querySelector('main').classList.toggle('hide-meanings',hide.checked);reveal.hidden=!hide.checked;
  }
  function save(){
    if(!ready)return;clearTimeout(timer);timer=setTimeout(()=>{
      const value={query:query.value,group:year.value,article:article.value,mastery:mastery.value,repeated:repeat.checked,hide:hide.checked,scroll:Math.max(0,Math.round(scrollY))};
      Progress.save('view',{page,value}).catch(U.error);
    },200);
  }
  year.addEventListener('input',()=>{articles();filter();save();});
  [query,repeat,article,mastery,hide].forEach(el=>el.addEventListener('input',()=>{filter();save();}));
  article.addEventListener('change',()=>{if(article.value)document.getElementById(article.value)?.scrollIntoView({block:'start'});});
  hide.addEventListener('change',()=>document.querySelectorAll('.revealed').forEach(e=>e.classList.remove('revealed')));
  reveal.onclick=()=>{hide.checked=false;filter();save();};
  document.addEventListener('click',event=>{const meaning=event.target.closest('.meaning');if(meaning&&hide.checked){meaning.classList.toggle('revealed');meaning.closest('.entry').classList.toggle('revealed',meaning.classList.contains('revealed'));}});
  document.querySelectorAll('.meaning').forEach(el=>{el.tabIndex=0;el.title='自测模式中点击或按回车揭示词义';el.addEventListener('keydown',e=>{if(hide.checked&&(e.key==='Enter'||e.key===' ')){e.preventDefault();el.classList.toggle('revealed');el.closest('.entry').classList.toggle('revealed',el.classList.contains('revealed'));}});});
  window.addEventListener('scroll',save,{passive:true});
  window.addEventListener('progresschange',()=>{if(ready)filter();});
  studyReady.then(()=>{
    const saved=Progress.state.views[page]||{};
    query.value=saved.query||'';year.value=saved.group||'';articles();article.value=saved.article||'';mastery.value=saved.mastery||'';repeat.checked=!!saved.repeated;hide.checked=!!saved.hide;
    const requested=new URLSearchParams(location.search).get('year');
    if(requested){const found=[...year.options].find(o=>o.value===requested||o.value.startsWith(requested+' '));if(found){year.value=found.value;articles();article.value='';}}
    filter();ready=true;
    if(!location.hash&&!requested)requestAnimationFrame(()=>scrollTo(0,Number(saved.scroll)||0));
  }).catch(()=>{articles();filter();});
})();
