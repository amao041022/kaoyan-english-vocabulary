/* 复习规则与备份校验。纯函数独立于页面，便于用固定时间测试。 */
(function (root, factory) {
  const api = factory(typeof module === 'object' && module.exports ? require('./personal-core.js') : root.PersonalCore);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.StudyCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (P) {
  'use strict';
  const PROJECT = 'kaoyan-vocabulary-study-v1';
  const LABELS = {new:'未学', unknown:'不认识', fuzzy:'模糊', familiar:'熟悉'};
  const INTERVALS = [3, 7, 14, 30, 60];
  const DAY = 86400000;
  function day(at) { const d = new Date(at); return `${d.getFullYear()}-${d.getMonth()+1}-${d.getDate()}`; }
  function daysLater(at, days) { const d = new Date(at); d.setDate(d.getDate()+days); return +d; }
  function emptyState() { return {schema:1, project:PROJECT, events:[], settings:{dailyNew:10}, views:{}, session:null, personal:[]}; }
  function fresh() { return {status:'new', due:0, lastAt:0, firstAt:0, attempts:0, step:-1, proofs:{}, advancedDay:'', lastDirection:'', contextIndex:-1}; }
  function fold(events) {
    const states = Object.create(null);
    for (const event of [...events].sort((a,b)=>a.at-b.at || a.id.localeCompare(b.id))) {
      const s = states[event.unitId] || fresh();
      const today = day(event.at);
      if (event.kind === 'downgrade') {
        const rank = {new:0, unknown:1, fuzzy:2, familiar:3};
        if (rank[event.level] >= rank[s.status]) continue;
        s.status=event.level; s.step=-1; s.proofs={};
        s.due=event.level==='unknown' ? event.at+600000 : daysLater(event.at,1);
        s.lastAt=event.at; s.advancedDay=today;
        states[event.unitId]=s; continue;
      }
      const wasDue = s.status==='new' || s.due<=event.at;
      s.firstAt ||= event.at; s.attempts++; s.lastAt=event.at;
      s.lastDirection=event.direction; s.contextIndex=event.contextIndex;
      const result = event.hinted && event.result==='known' ? 'uncertain' : event.result;
      if (result==='wrong' || result==='uncertain') {
        s.status=result==='wrong'?'unknown':'fuzzy'; s.proofs={}; s.step=-1;
        s.due=result==='wrong'?event.at+600000:daysLater(event.at,1);
        s.advancedDay=today;
      } else {
        s.proofs[event.direction] = today;
        const qualified = s.proofs['en-zh'] && s.proofs['zh-en'] && s.proofs['en-zh']!==s.proofs['zh-en'];
        if (qualified && wasDue && s.advancedDay!==today) {
          s.status='familiar'; s.step=Math.min(s.step+1,INTERVALS.length-1);
          s.due=daysLater(event.at,INTERVALS[s.step]); s.advancedDay=today;
        } else if (s.status!=='familiar') {
          s.status='fuzzy'; if(wasDue)s.due=daysLater(event.at,1);
        }
      }
      states[event.unitId]=s;
    }
    return states;
  }
  function shuffle(items, random=Math.random) {
    const out=[...items]; for(let i=out.length-1;i>0;i--){const j=Math.floor(random()*(i+1));[out[i],out[j]]=[out[j],out[i]];} return out;
  }
  function makeQuestion(unit, units, direction, random=Math.random) {
    // 干扰词须同词性，排除同词异义、人工标记的近义词及重叠释义。
    const tokens = value=>value.split(/[；;，,、]/).map(s=>s.trim()).filter(s=>s.length>1);
    if(unit.pos==='unreviewed')return {direction,mode:'flip',options:[]};
    const seen = new Set([unit.gloss]), seenWords=new Set([unit.word.toLowerCase()]);
    const candidates = shuffle(units,random).filter(other=>{
      if(other.id===unit.id || other.pos!==unit.pos || other.lemma.toLowerCase()===unit.lemma.toLowerCase())return false;
      if(unit.exclude.includes(other.id) || other.exclude.includes(unit.id))return false;
      if(tokens(unit.gloss).some(x=>tokens(other.gloss).some(y=>x.includes(y)||y.includes(x))))return false;
      if(seen.has(other.gloss)||seenWords.has(other.word.toLowerCase()))return false; seen.add(other.gloss);seenWords.add(other.word.toLowerCase()); return true;
    });
    if(candidates.length<3)return {direction,mode:'flip',options:[]};
    return {direction,mode:'choice',options:shuffle([unit,...candidates.slice(0,3)],random).map(x=>({id:x.id,text:direction==='en-zh'?x.gloss:x.word}))};
  }
  function plan(units, events, mode, section, limit, at) {
    const states=fold(events);
    const selected=units.filter(u=>!section||u.contexts.some(c=>c.section_id===section));
    const due=selected.filter(u=>states[u.id]&&states[u.id].due<=at).sort((a,b)=>states[a.id].due-states[b.id].due);
    const learnedToday=units.filter(u=>states[u.id]?.firstAt&&day(states[u.id].firstAt)===day(at)).length;
    const remaining=Math.max(0,limit-learnedToday);
    const unlearned=selected.filter(u=>!states[u.id]).slice(0,remaining);
    if(mode==='review')return due.map(u=>u.id);
    if(mode==='article') {
      const later=selected.filter(u=>states[u.id]&&!due.includes(u)).sort((a,b)=>states[a.id].due-states[b.id].due);
      return [...due,...later,...unlearned].map(u=>u.id);
    }
    return [...due,...unlearned].map(u=>u.id);
  }
  function validId(value) { return typeof value==='string' && !['__proto__','constructor','prototype'].includes(value) && /^[A-Za-z0-9_-]{1,100}$/.test(value); }
  function validateEvent(e) {
    if(!e||!validId(e.id)||!validId(e.unitId)||!Number.isSafeInteger(e.at)||e.at<0||e.at>4102444800000)throw new Error('练习记录的编号或时间无效');
    if(e.kind==='downgrade') {
      if(!['unknown','fuzzy'].includes(e.level))throw new Error('降级记录无效');
      return {id:e.id,unitId:e.unitId,at:e.at,kind:'downgrade',level:e.level};
    }
    if(e.kind!=='answer'||!['en-zh','zh-en'].includes(e.direction)||!['wrong','uncertain','known'].includes(e.result)||typeof e.hinted!=='boolean'||!Number.isInteger(e.contextIndex)||e.contextIndex<0||e.contextIndex>10000)throw new Error('答题记录格式无效');
    return {id:e.id,unitId:e.unitId,at:e.at,kind:'answer',direction:e.direction,result:e.result,hinted:e.hinted,contextIndex:e.contextIndex};
  }
  function validateBackup(input) {
    if(!input||input.schema!==1||input.project!==PROJECT||!Array.isArray(input.events)||input.events.length>100000)throw new Error('这不是支持的学习进度备份');
    const events=input.events.map(validateEvent), ids=new Set();
    for(const e of events){if(ids.has(e.id))throw new Error('备份中存在重复记录编号');ids.add(e.id);}
    const dailyNew=input.settings?.dailyNew??10;
    if(!Number.isInteger(dailyNew)||dailyNew<1||dailyNew>100)throw new Error('每日新词数须为1—100');
    return {schema:1,project:PROJECT,events,settings:{dailyNew},personal:P.validateCards(input.personal||[])};
  }
  function mergeBackup(state, input) {
    const incoming=validateBackup(input), map=new Map(state.events.map(e=>[e.id,e]));
    for(const e of incoming.events){if(map.has(e.id)&&JSON.stringify(map.get(e.id))!==JSON.stringify(e))throw new Error('记录编号冲突，请检查备份来源');map.set(e.id,e);}
    if(map.size>100000)throw new Error('学习记录过多，请先导出备份');
    return {...state,events:[...map.values()],settings:incoming.settings,personal:P.mergeCards(state.personal||[],incoming.personal)};
  }
  return {PROJECT,LABELS,INTERVALS,DAY,day,daysLater,emptyState,fresh,fold,shuffle,makeQuestion,plan,validateEvent,validateBackup,mergeBackup};
});
