"""把 ECDICT CSV 切分为离线词典。运行：python scripts/build_dictionary.py CSV路径 LICENSE路径。"""
from __future__ import annotations
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]

def build(csv_path: Path, license_path: Path) -> None:
    target=ROOT/'data/dictionary';target.mkdir(parents=True,exist_ok=True)
    shards={key:{'entries':{},'aliases':{}} for key in 'abcdefghijklmnopqrstuvwxyz_'}
    def key(word: str) -> str:
        c=word[:1].lower();return c if c in shards else '_'
    count=0
    with csv_path.open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            word=row['word'].strip();term=word.casefold()
            if not term or len(term)>100 or not row['translation'].strip():continue
            translation=row['translation'].replace('\\n','\n').strip()
            exchange=dict(part.split(':',1) for part in row['exchange'].split('/') if ':' in part)
            shards[key(term)]['entries'][term]=[word,row['phonetic'],translation,exchange]
            for typ,value in exchange.items():
                if typ in ('p','d','i','3','r','t','s'):
                    for variant in value.split(','):
                        variant=variant.strip().casefold()
                        if variant and variant!=term and len(variant)<=100:
                            aliases=shards[key(variant)]['aliases'].setdefault(variant,[])
                            if term not in aliases:aliases.append(term)
            count+=1
    for key,content in shards.items():
        payload=json.dumps(content,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
        (target/f'{key}.js').write_text(f'window.DICT_SHARDS=window.DICT_SHARDS||{{}};window.DICT_SHARDS["{key}"]='+payload+';\n',encoding='utf-8')
    shutil.copy2(license_path,target/'LICENSE.txt')
    manifest={'name':'ECDICT','entries':sum(len(s['entries']) for s in shards.values()),'shards':list(shards),
              'source':'https://github.com/skywind3000/ECDICT','download_url':'https://codeload.github.com/skywind3000/ECDICT/zip/refs/heads/master',
              'built_at':datetime.now(timezone.utc).isoformat(),'csv_sha256':hashlib.sha256(csv_path.read_bytes()).hexdigest(),
              'license':'MIT','phonetic_note':'来源词典音标，以英音为主；未统一标为美音。',
              'note':'词形关联来自词典exchange字段，是候选关系，用户选择后才用于真题匹配。通用释义不等同于文中含义。'}
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False))

if __name__=='__main__':build(Path(sys.argv[1]),Path(sys.argv[2]))
