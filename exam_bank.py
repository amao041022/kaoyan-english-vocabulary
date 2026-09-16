"""本地真题检索，仅使用标准库；例：python exam_bank.py --year 2017 --words undermine eligible。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
BANK = ROOT / 'data' / 'exam_bank'
SECTION_NAMES = {'cloze': '完形填空', **{f'text{i}': f'阅读 Text {i}' for i in range(1, 5)},
                 'new_type': '新题型', 'translation': '翻译', 'writing_a': '小作文', 'writing_b': '大作文'}
KIND_NAMES = {'passage': '正文', 'question': '题干', 'option': '选项（不代表正确答案）',
              'paragraph_option': '新题型待选段落', 'directions': '作答说明', 'writing': '写作题目'}


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """保守按句末切分；缩写和小数不切开，结果始终是原文连续片段。"""
    result, start = [], 0
    abbreviations = {'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'st.', 'vs.', 'etc.', 'e.g.', 'i.e.',
                     'jr.', 'sr.', 'inc.', 'co.', 'ltd.', 'no.', 'fig.', 'ind.'}
    for match in re.finditer(r'[.!?]+[\"”’\x27)]*(?=\s+|$)', text):
        end = match.end()
        prefix = text[:match.start() + 1]
        token = prefix.split()[-1].lower() if prefix.split() else ''
        if text[match.start()] == '.' and (token in abbreviations or
                re.search(r'(?:\b[A-Za-z]\.){2,}$', prefix) or re.search(r'\b[A-Z]\.$', prefix)):
            continue
        if end > start:
            result.append((start, end))
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text):
        result.append((start, len(text)))
    return result or [(0, len(text))]


def token_pattern(forms: list[str]) -> re.Pattern[str]:
    parts = [re.escape(s).replace(r'\ ', r'\s+') for s in sorted(set(forms), key=len, reverse=True) if s.strip()]
    if not parts:
        raise ValueError('查询词不能为空')
    return re.compile(r'(?<![A-Za-z])(?:' + '|'.join(parts) + r')(?![A-Za-z])', re.I)


def known_forms(word: str, root: Path = ROOT) -> list[str]:
    """只使用已有词库中明确登记的词形，不把派生词或猜测词形当作同词。"""
    path = root / 'data' / 'vocabulary.json'
    forms = [word]
    if path.exists():
        for entry in json.loads(path.read_text(encoding='utf-8'))['entries']:
            values = [entry['lemma'], *entry.get('forms', [])]
            if word.casefold() in {v.casefold() for v in values}:
                forms.extend(values)
    return list(dict.fromkeys(forms))


def search(paper: dict, word: str, forms: list[str] | None = None, section: str | None = None) -> list[dict]:
    matcher = token_pattern(forms or [word])
    hits = []
    for record in paper['records']:
        if section and record['section'] != section:
            continue
        text = record['text']
        if not matcher.search(text):
            continue
        spans = sentence_spans(text) if record['kind'] in ('passage', 'paragraph_option') else [(0, len(text))]
        for start, end in spans:
            sentence = text[start:end]
            matches = list(matcher.finditer(sentence))
            if not matches:
                continue
            hits.append({'record_id': record['id'], 'year': paper['year'], 'section': record['section'],
                         'location': record['location'], 'kind': record['kind'],
                         'matched_forms': list(dict.fromkeys(m.group() for m in matches)),
                         'example': sentence, 'paragraph': text, 'start': start, 'end': end,
                         'pdf_pages': record.get('pdf_pages', []), 'pdf': paper['pdf'],
                         'source_url': paper['source_url'] + '#' + record['anchor']})
    priority = {'passage': 0, 'paragraph_option': 1, 'question': 2, 'option': 3, 'writing': 4, 'directions': 5}
    return sorted(hits, key=lambda hit: priority.get(hit['kind'], 9))


def build_browser_data(root: Path = ROOT) -> None:
    """生成 file:// 可直接使用的数据脚本；重新生成复习页面时同步词形表。"""
    bank = root / 'data' / 'exam_bank'
    if not (bank / 'manifest.json').exists():
        return
    aliases: dict[str, list[str]] = {}
    vocabulary = root / 'data' / 'vocabulary.json'
    if vocabulary.exists():
        for entry in json.loads(vocabulary.read_text(encoding='utf-8'))['entries']:
            forms = list(dict.fromkeys([entry['lemma'], *entry.get('forms', [])]))
            for form in forms:
                aliases[form.casefold()] = list(dict.fromkeys(aliases.get(form.casefold(), []) + forms))
    papers = [json.loads((bank / f'{year}.json').read_text(encoding='utf-8')) for year in range(2006, 2026)]
    for paper in papers:
        for record in paper['records']:
            record['sentences'] = [record['text'][start:end] for start, end in sentence_spans(record['text'])] if record['kind'] in ('passage', 'paragraph_option') else [record['text']]
    payload = json.dumps({'papers': papers, 'aliases': aliases}, ensure_ascii=False).replace('</', '<\\/')
    (root / 'output').mkdir(exist_ok=True)
    (root / 'output' / 'exam-bank-data.js').write_text('window.EXAM_BANK = ' + payload + ';\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, required=True, choices=range(2006, 2026))
    parser.add_argument('--words', nargs='+', required=True, help='多个词用空格；短语使用引号')
    parser.add_argument('--section', choices=list(SECTION_NAMES))
    parser.add_argument('--forms', nargs='+', default=[], help='手动指定已经确认的词形；只允许查询一个词时使用')
    parser.add_argument('--json', action='store_true', help='输出完整原句、原段、定位信息，便于后续整理')
    args = parser.parse_args()
    if args.forms and len(args.words) != 1:
        parser.error('--forms 仅能配合一个查询词')
    paper = json.loads((BANK / f'{args.year}.json').read_text(encoding='utf-8'))
    results = []
    for word in args.words:
        forms = list(dict.fromkeys(known_forms(word) + args.forms))
        hits = search(paper, word, forms, args.section)
        results.append({'word': word, 'searched_forms': forms, 'count': len(hits), 'hits': hits})
    if args.json:
        print(json.dumps({'paper': paper['title'], 'results': results}, ensure_ascii=False, indent=2))
    else:
        print(paper['title'])
        for result in results:
            print(f"\n【{result['word']}】{result['count']} 处；查询词形：{', '.join(result['searched_forms'])}")
            for hit in result['hits']:
                print(f"- {SECTION_NAMES[hit['section']]} · {hit['location']} · {KIND_NAMES[hit['kind']]}\n  {hit['example']}")
            if not result['hits']:
                print('  未找到；请核对年份、英语一/二、拼写或使用 --forms 指定原文词形。不得生成替代例句。')


if __name__ == '__main__':
    main()
