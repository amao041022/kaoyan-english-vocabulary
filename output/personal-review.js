/* 个人收词在复习页动态显示，正式词库原有条目保持不变。 */
(() => {
  'use strict';
  if(document.querySelector('#study-app')||!document.querySelector('main'))return;
  const U=StudyUI,E=U.esc,full=!!document.querySelector('.detail-view'),repeatPage=decodeURIComponent(location.pathname).endsWith('/复现词汇.html');
  function render(){
    let box=document.getElementById('personal-review');if(!box){box=document.createElement('section');box.id='personal-review';document.querySelector('footer').before(box);}
    const cards=PersonalLibrary.cards;let html='<h2>个人收词'+(repeatPage?' · 复现语境':'')+'</h2><p class="note">来自离线查词；个人选择的释义需结合原文核对。以下复现仅统计已保存语境。</p>',count=0;
    for(const card of cards){const unit=PersonalLibrary.unit(card),first=unit.contexts[0];const all=VOCAB_STUDY.units.filter(u=>PersonalCore.normalize(u.lemma)===PersonalCore.normalize(card.lemma)).flatMap(u=>u.contexts).filter(c=>c.location!=='词典收词；尚无原文例句');const unique=[...new Map(all.map(c=>[c.section_id+'\n'+c.example,c])).values()];const repeated=unique.length>1;if(repeatPage&&!repeated)continue;count++;
      const contexts=repeatPage?unique:unit.contexts,details=contexts.map(c=>U.contextHTML(unit,c)).join('');
      html+=`<article class="entry" id="${E(card.id)}" data-study-id="${E(unit.id)}" data-year="${E(first.source_group)}" data-years="${E(JSON.stringify([...new Set(contexts.map(c=>c.source_group))]))}" data-sections="${E(JSON.stringify([...new Set(contexts.map(c=>c.section_id))]))}" data-section="${E(first.section_id)}" data-repeated="${repeated?'yes':'no'}" data-search="${E([card.word,card.meaning,card.common,...contexts.map(c=>c.example)].join(' ').toLowerCase())}"><div class="definition"><strong class="word">${E(card.word)}</strong>${U.badge(unit.id)}${U.audio(unit.audio,'单词')}<span class="ipa">${E(card.ipa)}</span><span class="meaning">${E(card.meaning)}</span>${repeated?`<span class="repeat">已保存 ${unique.length} 处语境</span>`:''}<span class="note">${card.targetId?'个人补充':'个人收词'}</span></div>`;
      html+=full||repeatPage?`<div class="full">${details}</div>`:`<details><summary><span class="sentence">${U.highlight(first.example,card.forms)}</span> ${U.audio(first.audio,'例句')}<span class="kind">展开</span></summary><div class="full">${details}</div></details>`;html+='</article>';
    }
    box.innerHTML=html;box.querySelectorAll('.meaning').forEach(el=>{el.tabIndex=0;el.onkeydown=e=>{if((e.key==='Enter'||e.key===' ')&&document.querySelector('main').classList.contains('hide-meanings')){e.preventDefault();el.click();}};});box.hidden=count===0;window.dispatchEvent(new Event('personalrowschange'));
  }
  window.addEventListener('personallibrarychange',render);studyReady.then(render).catch(()=>{});
})();
