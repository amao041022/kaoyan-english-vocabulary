/* 按首字母加载本地词典；不发出网络请求。 */
(() => {
  'use strict';
  const pending=new Map(),norm=PersonalCore.normalize;
  const key=s=>/^[a-z]/.test(s)?s[0]:'_';
  function load(word){const k=key(word);if(!pending.has(k))pending.set(k,new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='../data/dictionary/'+k+'.js';s.onload=()=>resolve(window.DICT_SHARDS[k]);s.onerror=()=>{pending.delete(k);s.remove();reject(new Error('本地词典文件加载失败，请保留 data/dictionary 文件夹'));};document.head.append(s);}));return pending.get(k);}
  async function lookup(word){word=norm(word);const shard=await load(word),raw=shard.entries[word];const keys=[...new Set([...(raw?.[3]?.['0']||'').split(',').filter(Boolean),...(shard.aliases[word]||[]),...(raw?[word]:[])])].slice(0,20),result=[];
    for(const k of keys){const entry=(await load(k)).entries[k];if(entry)result.push(entry);}
    return {entries:result,suggestions:result.length?[]:Object.keys(shard.entries).filter(k=>k.startsWith(word)).slice(0,10)};
  }
  function forms(entry){return [...new Set([entry[0],...Object.entries(entry[3]||{}).filter(([k])=>['p','d','i','3','r','t','s'].includes(k)).flatMap(([,v])=>v.split(','))])].filter(Boolean).slice(0,30);}
  window.OfflineDictionary={lookup,forms};
})();
