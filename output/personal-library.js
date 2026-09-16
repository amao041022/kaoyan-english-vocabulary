/* 将浏览器个人词库并入页面中的学习资料；正式词库文件不被改写。 */
(() => {
  'use strict';
  const D=VOCAB_STUDY,P=PersonalCore,base=structuredClone(D),baseIds=new Set(base.units.map(u=>u.id));
  let signature='';
  const speech=s=>{for(const u of base.units){if(P.normalize(u.word)===P.normalize(s))return u.audio;const c=u.contexts.find(c=>c.example===s);if(c)return c.audio;}return 'tts:'+s;};
  function context(card,c){return {entry_id:card.id,section_id:c.section_id||'personal',section_title:c.section_title||'个人收词',source_group:c.source_group||'个人收词',location:c.location||'自行收录',example:c.example,translation:c.translation||'翻译待补充（离线版不自动翻译）',ipa:card.ipa||'词典未提供音标',common:card.common,meaning:card.meaning,form:card.forms.join(' / '),note:'个人选择的释义，请结合原段核对。'+card.ipaLabel,collocations:[],photos:c.sourceUrl?[{name:'原文位置',url:c.sourceUrl}]:[],audio:speech(c.example)};}
  function unit(card){const contexts=card.contexts.length?card.contexts.map(c=>context(card,c)):[context(card,{example:card.word,kind:'manual',location:'词典收词；尚无原文例句'})];return {id:card.targetId||card.id,lemma:card.lemma,word:card.word,gloss:card.meaning,pos:'unreviewed',forms:card.forms,members:[card.id],contexts,exclude:[],audio:speech(card.word),personal:true};}
  function sync(){
    const cards=P.validateCards(Progress.state.personal||[]),next=JSON.stringify(cards);if(next===signature)return false;
    const units=structuredClone(base.units),map=new Map(units.map(u=>[u.id,u]));
    const entryUnits={...base.entryUnits},sections=structuredClone(base.sections);
    for(const card of cards){const added=unit(card),old=map.get(added.id);
      if(old){if(P.normalize(old.lemma)!==P.normalize(card.lemma)||P.meaningKey(old.gloss)!==P.meaningKey(card.meaning))throw new Error('个人补充词条与原学习单元不一致');for(const c of card.contexts.length?added.contexts:[])if(!old.contexts.some(v=>v.section_id===c.section_id&&v.example===c.example))old.contexts.push(c);old.forms=[...new Set([...old.forms,...card.forms])];}
      else{units.push(added);map.set(added.id,added);}
      entryUnits[card.id]=added.id;
      for(const c of added.contexts)if(!sections.some(s=>s.id===c.section_id))sections.push({id:c.section_id,title:c.section_title,group:c.source_group});
    }
    D.units.splice(0,D.units.length,...units);D.sections.splice(0,D.sections.length,...sections);D.entryUnits=entryUnits;
    signature=next;window.dispatchEvent(new Event('personallibrarychange'));return true;
  }
  async function add(card){const checked=P.validateCard(card);const target=base.units.find(u=>u.id===checked.targetId);if(target&&P.normalize(target.lemma)!==P.normalize(checked.lemma))throw new Error('不能合并不同单词');await Progress.save('personal-add',checked);}
  window.PersonalLibrary={sync,add,unit,get cards(){return Progress.state.personal||[];},base,baseIds};
  window.addEventListener('progresschange',()=>{try{sync();}catch(error){window.dispatchEvent(new CustomEvent('progresserror',{detail:error}));}});
})();
