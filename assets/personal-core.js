/* 个人词库的纯函数：验证、同义项去重、备份合并。 */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.PersonalCore=api;})(globalThis,function(){
  'use strict';
  const normalize=s=>String(s).normalize('NFKC').trim().replace(/\s+/g,' ').toLowerCase();
  const meaningKey=s=>normalize(s).replace(/^(?:(?:n|v|vt|vi|adj|adv|a|prep|pron|conj)\.\s*)+/,'').replace(/[。；;\s]+$/,'');
  function hash(text){let a=2166136261,b=5381;for(const c of text){a=Math.imul(a^c.charCodeAt(0),16777619);b=Math.imul(b,33)^c.charCodeAt(0);}return (a>>>0).toString(16).padStart(8,'0')+(b>>>0).toString(16).padStart(8,'0');}
  function cardId(lemma,meaning,targetId=''){return 'pc-'+hash(normalize(lemma)+'\n'+meaningKey(meaning)+'\n'+targetId);}
  function text(value,max,label,required=false){if(typeof value!=='string'||value.length>max||(required&&!value.trim()))throw new Error(label+'格式无效或过长');return value.trim();}
  const validId=s=>typeof s==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(s)&&!['__proto__','constructor','prototype'].includes(s);
  function context(input){
    if(!input||typeof input!=='object')throw new Error('例句格式无效');
    const out={};
    for(const [key,max] of Object.entries({example:10000,translation:10000,section_id:120,section_title:200,source_group:100,location:200,kind:40,sourceUrl:400}))out[key]=text(input[key]||'',max,'例句'+key,key==='example');
    if(out.sourceUrl&&!/^exams\/\d{4}\.html#[A-Za-z0-9_-]+$/.test(out.sourceUrl))throw new Error('例句来源链接无效');
    if(!['passage','paragraph_option','option','question','directions','writing','saved','manual'].includes(out.kind))throw new Error('例句类型无效');
    return out;
  }
  function validateCard(input){
    if(!input||typeof input!=='object')throw new Error('个人词条格式无效');
    const c={};
    for(const [key,max] of Object.entries({lemma:100,word:100,meaning:1000,common:10000,ipa:200,ipaLabel:100,targetId:100}))c[key]=text(input[key]||'',max,key,['lemma','word','meaning'].includes(key));
    if(!/[A-Za-z]/.test(c.lemma)||/[<>\x00-\x1f]/.test(c.lemma+c.word))throw new Error('请输入有效英文词或短语');
    if(c.targetId&&!validId(c.targetId))throw new Error('关联学习单元无效');
    c.id=cardId(c.lemma,c.meaning,c.targetId);if(input.id!==c.id)throw new Error('词条编号与词义不一致');
    if(!Array.isArray(input.forms)||input.forms.length>30)throw new Error('词形数量无效');
    c.forms=[...new Set([c.lemma,...input.forms.map(s=>text(s,100,'词形',true))])];
    if(!Array.isArray(input.contexts)||input.contexts.length>30)throw new Error('例句过多，每个义项最多30条');
    c.contexts=input.contexts.map(context);
    if(c.forms.length>30)throw new Error('词形超过30个');
    for(const key of ['createdAt','updatedAt']){if(!Number.isSafeInteger(input[key])||input[key]<0||input[key]>4102444800000)throw new Error('词条时间无效');c[key]=input[key];}
    return c;
  }
  function validateCards(input){if(!Array.isArray(input)||input.length>5000)throw new Error('个人词库格式无效或超过5000个义项');const cards=input.map(validateCard);if(new Set(cards.map(c=>c.id)).size!==cards.length)throw new Error('个人词库有重复编号');return cards;}
  function mergeCards(existing,incoming){
    const map=new Map(validateCards(existing||[]).map(c=>[c.id,c]));
    for(const card of validateCards(incoming||[])){
      const old=map.get(card.id);if(!old){map.set(card.id,card);continue;}
      if(normalize(old.lemma)!==normalize(card.lemma)||meaningKey(old.meaning)!==meaningKey(card.meaning)||old.targetId!==card.targetId)throw new Error('个人词条编号冲突');
      const contexts=[...old.contexts];
      for(const item of card.contexts){const prior=contexts.find(c=>c.example===item.example&&c.section_id===item.section_id);if(!prior)contexts.push(item);else if(!prior.translation&&item.translation)prior.translation=item.translation;}
      const next={...old,forms:[...new Set([...old.forms,...card.forms])],contexts,updatedAt:Math.max(old.updatedAt,card.updatedAt)};
      map.set(card.id,validateCard(next));
    }
    if(map.size>5000)throw new Error('个人词库超过5000个义项');return [...map.values()];
  }
  return {normalize,meaningKey,hash,cardId,validateCard,validateCards,mergeCards};
});
