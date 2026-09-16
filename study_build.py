"""把审核过的词义与搭配生成为浏览器可直接读取的学习资料。"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable
from urllib.parse import quote


def build_study(data: dict, config: dict, audio_url: Callable[[str], str]) -> dict:
    entries = {e['id']: e for e in data['entries']}
    aliases = config.get('aliases', {})
    for alias, target in aliases.items():
        if alias not in entries or target not in entries or target in aliases:
            raise ValueError(f'学习单元合并关系无效：{alias}')
        if entries[alias]['lemma'].casefold() != entries[target]['lemma'].casefold():
            raise ValueError(f'不能合并不同单词：{alias}')
    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in entries.values():
        grouped[aliases.get(e['id'], e['id'])].append(e)
    units = []
    entry_units = {}
    for uid, members in grouped.items():
        first = entries[uid]
        spec = config.get('entries', {}).get(uid, {})
        # 新词暂未审核题目时仍能翻卡学习，不自动拼凑干扰项。
        gloss = spec.get('quiz_gloss', re.sub(r'^[A-Za-z./ -]+', '', first['short_meaning']))
        unit = {'id': uid, 'lemma': first['lemma'], 'word': first.get('display', first['lemma']),
                'gloss': gloss, 'pos': spec.get('pos', 'unreviewed'), 'members': [],
                'contexts': [], 'forms': [], 'exclude': [], 'audio': audio_url(first.get('display', first['lemma']))}
        seen = set()
        for e in members:
            entry_units[e['id']] = uid
            unit['members'].append(e['id'])
            unit['forms'] += e['forms']
            collocations = []
            for item in config.get('entries', {}).get(e['id'], {}).get('collocations', []):
                if item['source'] not in ('原文搭配', '补充搭配') or not item['text'] or not item['meaning']:
                    raise ValueError(f'搭配资料不完整：{e["id"]}')
                collocations.append({**item, 'audio': audio_url(item['text'])})
            # 一个原句只出现一次；附加证据仍保留自己的来源、词形和语境。
            for source in [e, *e.get('additional_evidence', [])]:
                key = (source['section_id'], source['example'])
                if key in seen:
                    continue
                seen.add(key)
                example = source['example']
                context = {k: source[k] for k in ('section_id','section_title','location','example','translation')}
                context.update(entry_id=e['id'], source_group=source.get('source_group') or f'{source["year"]} 英语（一）',
                               ipa=e['ipa'], common=e['common'], meaning=e['meaning'], form=e['form'],
                               note=e.get('note',''), collocations=collocations, audio=audio_url(example),
                               photos=[{'name':p, 'url':'../images/'+quote(p)} for p in source.get('source_photos',[source['photo']])])
                if source is not e:
                    context['meaning'] = gloss + '（具体语境见本句翻译）'
                    context['form'] = ' / '.join(dict.fromkeys(m.group() for m in re.finditer(
                        r'(?<![A-Za-z])(?:'+'|'.join(re.escape(f) for f in sorted(unit['forms'],key=len,reverse=True))+r')(?![A-Za-z])', example, re.I)))
                unit['contexts'].append(context)
        unit['forms'] = list(dict.fromkeys(unit['forms']))
        units.append(unit)
    for unit in units:
        excluded = set()
        for group in config.get('confusable_groups', []):
            if unit['lemma'].casefold() in {x.casefold() for x in group}:
                excluded.update(u['id'] for u in units if u['lemma'].casefold() in {x.casefold() for x in group})
        unit['exclude'] = sorted(excluded - {unit['id']})
    sections = {e['section_id']: {'id':e['section_id'],'title':e['section_title'],
                                'group':e.get('source_group') or f'{e["year"]} 英语（一）'} for e in entries.values()}
    return {'schema':1,'units':units,'entryUnits':entry_units,'sections':list(sections.values())}


PRACTICE_BODY = '''<div id="study-app" class="study-app" aria-live="polite">
<p>正在加载学习记录…</p></div>
<noscript>背词练习需要启用浏览器的 JavaScript。</noscript>'''
