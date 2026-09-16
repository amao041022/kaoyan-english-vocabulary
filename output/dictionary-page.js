(() => {
  'use strict';
  const U=StudyUI,P=PersonalCore,dict=OfflineDictionary,$=id=>document.getElementById(id),E=U.esc;
  const names={cloze:'完形填空',text1:'阅读 Text 1',text2:'阅读 Text 2',text3:'阅读 Text 3',text4:'阅读 Text 4',new_type:'新题型',translation:'翻译',writing_a:'小作文',writing_b:'大作文'};
  const kinds={passage:'正文原句',paragraph_option:'待选段落',question:'题干',option:'选项（不代表正确答案）',directions:'作答说明',writing:'写作题目'};
  let entry=null,forms=[],matches=[],shown=0,selected=new Map(),targetId='',generation=0;
  const params=new URLSearchParams(location.search);
  for(const p of EXAM_BANK.papers.slice().reverse())$('lookup-year').insertAdjacentHTML('beforeend',`<option value="${p.year}">${p.year}</option>`);
  for(const [id,name] of Object.entries(names))$('lookup-section').insertAdjacentHTML('beforeend',`<option value="${id}">${name}</option>`);
  $('lookup-word').value=params.get('word')||'';$('lookup-year').value=params.get('year')||'';$('lookup-section').value=params.get('section')||'';
  $('backup').innerHTML=U.backupControls;
  function personal(){const cards=PersonalLibrary.cards;$('personal-count').textContent=`· ${cards.length} 个义项`;$('personal-list').innerHTML=cards.slice(-20).reverse().map(c=>`<p><a href="背词练习.html?unit=${encodeURIComponent(c.targetId||c.id)}">${E(c.word)}</a> · ${E(c.meaning)}</p>`).join('')||'<p>尚未收录</p>';}
  window.addEventListener('personallibrarychange',personal);studyReady.then(personal).catch(()=>{});
  function selection(){ $('selection-count').textContent=`已选择 ${selected.size} 条例句；${targetId?'将补充到已有义项，沿用学习进度':'按本次词义收录，同词同义不重复添加'}。`; }
  function more(){for(let i=shown;i<Math.min(shown+30,matches.length);i++){const c=matches[i];const row=document.createElement('article');row.className='hit';row.innerHTML=`<label><input type="checkbox" data-hit="${i}"><span><span class="where">${E(c.section_title)} · ${E(c.location)} · ${E(kinds[c.kind])}</span><br><span class="sentence">${U.highlight(c.example,forms)}</span></span></label>${U.audio('tts:'+c.example,'例句')} <a href="${E(c.sourceUrl)}" target="_blank" rel="noopener">核对原文</a><details><summary>查看原段／添加译文</summary><p class="sentence">${E(c.paragraph)}</p><textarea data-translation="${i}" rows="2" maxlength="10000" placeholder="译文可留空，保存后标为待补充" aria-label="例句译文"></textarea></details>`;$('hits').append(row);}
    shown=Math.min(shown+30,matches.length);$('more-hits').hidden=shown>=matches.length;
  }
  function selectEntry(value){entry=value;forms=dict.forms(entry);targetId='';selected=new Map();shown=0;$('chosen-meaning').value='';$('message').textContent='';$('definition').hidden=false;
    $('headword').textContent=entry[0];$('phonetic').textContent=entry[1]?`/${entry[1]}/ · ECDICT 原音标（主要为英音）`:'词典未提供音标';$('word-audio').innerHTML=U.audio(PersonalLibrary.base.units.find(u=>P.normalize(u.word)===P.normalize(entry[0]))?.audio||'tts:'+entry[0],'单词');
    $('senses').innerHTML=entry[2].split('\n').filter(Boolean).map(s=>`<button type="button" data-sense="${E(s)}">${E(s)}</button>`).join('')||'<p>词典未收录，可自行填写已核对的词义。</p>';
    const existing=PersonalLibrary.base.units.filter(u=>P.normalize(u.lemma)===P.normalize(entry[0]));$('existing').innerHTML=existing.length?'<h3>已有义项（选择后补充例句）</h3>'+existing.map(u=>`<button type="button" data-target="${E(u.id)}">${E(u.gloss)}</button>`).join(''):'';
    const re=new RegExp('(?<![A-Za-z])(?:'+forms.map(s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')(?![A-Za-z])','i');matches=[];
    for(const paper of EXAM_BANK.papers){if($('lookup-year').value&&String(paper.year)!==$('lookup-year').value)continue;for(const r of paper.records){if($('lookup-section').value&&r.section!==$('lookup-section').value)continue;for(const example of r.sentences||[r.text]){if(!re.test(example))continue;matches.push({example,translation:'',section_id:`${paper.year}-${r.section.replace(/^text/,'t').replace('_','-')}`,section_title:`${paper.year} 英语（一） · ${names[r.section]||r.section}`,source_group:`${paper.year} 英语（一）`,location:r.location,kind:r.kind,sourceUrl:`exams/${paper.year}.html#${r.anchor}`,paragraph:r.text});}}}
    matches.sort((a,b)=>(a.kind==='passage'?0:1)-(b.kind==='passage'?0:1));matches=matches.filter((c,i,all)=>all.findIndex(x=>x.section_id===c.section_id&&x.example===c.example)===i);
    $('hit-count').textContent=`· ${matches.length} 处`;$('hits').replaceChildren();if(!matches.length)$('hits').textContent='本题库没有匹配原句。可只收词义，也可换年份、题型或词形重查。';more();selection();
    $('status').textContent=`当前词条：${entry[0]}。匹配词形：${forms.join(' / ')}。词形由词典提供，请核对。`;
  }
  async function lookup(event){event?.preventDefault();const word=P.normalize($('lookup-word').value);if(!word)return;const token=++generation;$('definition').hidden=true;$('candidates').replaceChildren();$('status').textContent='正在读取本地词典…';try{const result=await dict.lookup(word);if(token!==generation)return;const entries=result.entries.length?result.entries:[[word,'','',{}]];for(const value of entries){const button=document.createElement('button');button.textContent=value[0];button.onclick=()=>selectEntry(value);$('candidates').append(button);}selectEntry(entries[0]);if(result.suggestions.length){const p=document.createElement('p');p.textContent='相近词：'+result.suggestions.join(' / ');$('candidates').append(p);}}catch(err){if(token===generation)$('status').textContent=err.message;}}
  $('dictionary-form').onsubmit=lookup;$('more-hits').onclick=more;
  $('senses').onclick=e=>{const b=e.target.closest('[data-sense]');if(b){targetId='';$('chosen-meaning').value=b.dataset.sense;selection();}};
  $('existing').onclick=e=>{const b=e.target.closest('[data-target]');if(b){targetId=b.dataset.target;$('chosen-meaning').value=PersonalLibrary.base.units.find(u=>u.id===targetId).gloss;selection();}};
  $('chosen-meaning').oninput=()=>{targetId='';selection();};
  $('hits').onchange=e=>{if(e.target.matches('[data-hit]')){const i=Number(e.target.dataset.hit);if(e.target.checked){if(selected.size>=30){e.target.checked=false;$('message').textContent='每个义项最多选择30条例句。';return;}selected.set(i,matches[i]);}else selected.delete(i);selection();}};
  $('hits').oninput=e=>{if(e.target.matches('[data-translation]'))matches[Number(e.target.dataset.translation)].translation=e.target.value;};
  $('add-word').onclick=async()=>{if(!entry)return;const meaning=$('chosen-meaning').value.trim();if(!meaning){$('message').textContent='请先选择或填写本次收录的词义。';$('chosen-meaning').focus();return;}
    const existing=PersonalLibrary.base.units.find(u=>P.normalize(u.lemma)===P.normalize(entry[0])&&P.meaningKey(u.gloss)===P.meaningKey(meaning));const target=targetId||existing?.id||'';const now=Date.now();const card={id:P.cardId(entry[0],meaning,target),lemma:entry[0],word:entry[0],meaning,common:entry[2],ipa:entry[1]?'/'+entry[1]+'/':'',ipaLabel:'ECDICT 原音标（主要为英音）',targetId:target,forms,contexts:[...selected.values()],createdAt:now,updatedAt:now};
    $('add-word').disabled=true;try{await studyReady;const previous=PersonalLibrary.cards.find(c=>c.id===card.id);await PersonalLibrary.add(card);$('message').textContent=previous?'已合并到原有义项；相同例句不会重复添加。':'已加入总复习、完整版和背词练习。请导出备份以便换设备。';}catch(err){$('message').textContent='未能保存：'+err.message;}finally{$('add-word').disabled=false;}
  };
  if($('lookup-word').value)lookup();
})();
