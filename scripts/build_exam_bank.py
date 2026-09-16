"""从已下载 HTML/PDF 建立真题库。需 lxml、pypdf；日常检索不依赖这些库。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from lxml import html
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bank import SECTION_NAMES, build_browser_data

BANK = ROOT / 'data' / 'exam_bank'
RAW = ROOT / 'images' / 'exam_bank'
MAPPING = {'section1': 'cloze', **{f'section2-part-a-{i}': f'text{i}' for i in range(1, 5)},
           'section2-part-b': 'new_type', 'section2-part-c': 'translation',
           'section3-part-a': 'writing_a', 'section3-part-b': 'writing_b'}


def clean(node) -> str:
    node = deepcopy(node)
    # 编号空格保留为 __题号__；不能将网页透明占位文字误当试题。
    for element in node.xpath('.//u'):
        value = ''.join(element.itertext()).strip()
        if value.isdigit():
            element.clear()
            element.text = f' __{value}__ '
    for element in node.xpath('.//*[contains(@style,"color:transparent")]'):
        element.text = ' ______ '
    for element in node.xpath('.//br'):
        element.tail = '\n' + (element.tail or '')
    return re.sub(r'\s+', ' ', node.text_content()).strip()


def normalized(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())


def build_year(year: int) -> dict:
    source = json.loads((BANK / f'{year}.source.json').read_text(encoding='utf-8'))
    for kind in ('html', 'pdf'):
        assert hashlib.sha256((ROOT / source[kind]['path']).read_bytes()).hexdigest() == source[kind]['sha256']
    paper = html.fromstring((ROOT / source['html']['path']).read_bytes()).get_element_by_id('paper')
    pdf_pages = [page.extract_text() or '' for page in PdfReader(ROOT / source['pdf']['path']).pages]
    (BANK / f'{year}.pdf.txt').write_text('\n\n'.join(f'【PDF 第 {i} 页】\n{text}' for i, text in enumerate(pdf_pages, 1)), encoding='utf-8')
    normalized_pages = [normalized(p) for p in pdf_pages]
    records, sections, figures = [], [], []

    def add(node, section: str, kind: str, location: str, anchor: str, text: str | None = None) -> None:
        value = clean(node) if text is None else text
        if not value:
            return
        # 连续英文片段定位，短选项不推测页码；找不到就只链接整卷。
        key = normalized(value)
        pages = []
        if len(key) >= 32:
            pages = [i + 1 for i, page in enumerate(normalized_pages) if key[:48] in page]
        records.append({'id': f'{year}:{section}:{kind}:{anchor}:{len(records) + 1}', 'section': section,
                        'kind': kind, 'location': location, 'anchor': anchor, 'text': value, 'pdf_pages': pages})

    modules = paper.xpath('.//*[@data-module-slug]')
    assert len(modules) == 9, (year, '题型模块数量不符')
    for module in modules:
        slug = module.get('data-module-slug')
        section = MAPPING[slug]
        sections.append(section)
        directions = paper.xpath(f'.//*[@id="directions-{slug}"]')
        for node in directions:
            add(node, section, 'writing' if section.startswith('writing') else 'directions', '题目说明', node.get('id'))
        paragraphs = module.xpath('.//*[@id and starts-with(@id,"p-")]')
        for i, node in enumerate(paragraphs, 1):
            letters = node.xpath('.//*[@data-pdh-letter]')
            kind = 'paragraph_option' if letters else 'passage'
            location = '段落 ' + letters[0].get('data-pdh-letter') if letters else f'第 {i} 段'
            add(node, section, kind, location, node.get('id'))
        questions = module.xpath('.//*[@id and starts-with(@id,"qp-")]')
        for question in questions:
            anchor = question.get('id')
            number = anchor.removeprefix('qp-')
            stems = question.xpath('.//*[@data-pdh-stem]')
            for node in stems:
                add(node, section, 'question', f'第 {number} 题题干', anchor)
            for node in question.xpath('.//*[@data-pdh-letter]'):
                add(node, section, 'option', f'第 {number} 题 {node.get("data-pdh-letter")} 选项', anchor)
        # 新题型的选句/标题通常独立于题号和正文，必须单独收录。
        for node in module.xpath('.//*[@data-pdh-letter]'):
            ancestors = node.xpath('ancestor::*[@id and (starts-with(@id,"p-") or starts-with(@id,"qp-"))]')
            if not ancestors:
                letter = node.get('data-pdh-letter')
                add(node, section, 'option', f'新题型 {letter} 选项', f'mod-{slug}')
        # PDF 整理版缺配图，使用页面另存的配图；alt 说明不混入例句。
        for node in module.xpath('.//img'):
            figures.append({'section': section, 'url': node.get('src'),
                            'source_description': node.get('alt', ''), 'description_is_exam_text': False})
    saved_figures = json.loads((BANK / f'{year}.figures.json').read_text(encoding='utf-8'))
    assert [f['url'] for f in saved_figures] == [f['url'] for f in figures]
    for figure in saved_figures:
        assert hashlib.sha256((ROOT / figure['path']).read_bytes()).hexdigest() == figure['sha256']
    figures = saved_figures
    counts = {section: sum(r['section'] == section for r in records) for section in sections}
    options = [r for r in records if r['kind'] == 'option']
    assert len([r for r in options if r['section'] == 'cloze']) == 80, year
    for section in ('text1', 'text2', 'text3', 'text4'):
        assert len([r for r in options if r['section'] == section]) == 20, (year, section)
        assert len([r for r in records if r['section'] == section and r['kind'] == 'question']) == 5, (year, section)
        assert any(r['section'] == section and r['kind'] == 'passage' for r in records)
    assert all(counts.values()), (year, counts)
    assert not any('占位符' in r['text'] for r in records)
    result = {'schema_version': 1, 'year': year, 'title': source['title'], 'source_url': source['page_url'],
              'pdf': source['pdf']['path'], 'pdf_page_count': len(pdf_pages), 'sections': counts,
              'records': records, 'figures': figures,
              'quality_note': '第三方整理版。已检查9个题型模块、完形20题选项、阅读20题题干选项及PDF可读性；未逐字人工校对。来源PDF缺作文配图，配图已单独保存并补入本地整卷页。新题型不重排、不填答案。原句自动切分，入生词库前结合原段核对。'}
    (BANK / f'{year}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [f'# {source["title"]}', f'来源：{source["page_url"]}', '', result['quality_note']]
    for section in sections:
        lines.extend(['', '## ' + SECTION_NAMES[section], ''])
        for record in records:
            if record['section'] == section:
                lines.extend([f'### {record["location"]}（{record["kind"]}）', record['text'], ''])
    (BANK / f'{year}.md').write_text('\n'.join(lines), encoding='utf-8')
    # 离线整卷页只保留卷面，不保留来源站脚本、答案解析和外部资源。
    local = deepcopy(paper)
    allowed = {'div', 'span', 'p', 'br', 'strong', 'b', 'i', 'em', 'u', 'img', 'section', 'h1', 'h2', 'h3', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'sup', 'sub'}
    for node in list(local.iterdescendants()):
        if not isinstance(node.tag, str):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
            continue
        if node.tag not in allowed:
            node.drop_tree()
            continue
        if 'color:transparent' in node.get('style', ''):
            node.text = '____________'
        for attribute in list(node.attrib):
            if attribute not in ('id', 'class', 'src', 'width', 'height', 'lang', 'colspan', 'rowspan'):
                del node.attrib[attribute]
        if node.tag == 'img':
            figure = next(f for f in figures if f['url'] == node.get('src'))
            node.set('src', '../../' + figure['path'])
            node.set('alt', '原题作文配图')
    from html import escape
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    page += f'<title>{escape(source["title"])}</title><style>body{{max-width:920px;margin:32px auto;padding:0 20px;font:17px/1.8 Georgia,"Microsoft YaHei",serif;color:#243341}}a{{color:#216458}}.flex{{display:flex;gap:8px}}.flex-c{{display:flex;flex-direction:column;gap:10px}}.flex-1{{flex:1}}[id^="p-"]{{margin:12px 0}}[id^="mod-"]{{margin-top:28px}}[id^="qp-"]{{margin:10px 0}}img{{max-width:100%;height:auto}}header{{font-family:sans-serif;font-size:14px;border-bottom:1px solid #ccd9ce;padding-bottom:12px}}u{{text-underline-offset:4px}}:target{{background:#fff4cf}}@media(max-width:600px){{body{{font-size:15px;margin:16px auto}}}}</style>'
    page += f'<header><a href="../真题检索.html?year={year}">返回真题检索</a> · <a href="../../{source["pdf"]["path"]}">来源PDF（配图另见本页）</a><h1>{escape(source["title"])}</h1><p>{escape(result["quality_note"])}</p><a href="{source["page_url"]}">来源页面</a></header>'
    page += html.tostring(local, encoding='unicode') + '</html>'
    exam_pages = ROOT / 'output' / 'exams'
    exam_pages.mkdir(parents=True, exist_ok=True)
    (exam_pages / f'{year}.html').write_text(page, encoding='utf-8')
    print(f'{year}: {len(pdf_pages)}页，{len(records)}段/题干/选项', flush=True)
    return result


def main() -> None:
    papers = [build_year(year) for year in range(2006, 2026)]
    manifest = {'schema_version': 1, 'built_at': datetime.now(timezone.utc).isoformat(),
                'years': list(range(2006, 2026)), 'paper_count': len(papers), 'reading_passages': 80,
                'record_count': sum(len(p['records']) for p in papers),
                'sources': [json.loads((BANK / f'{p["year"]}.source.json').read_text(encoding='utf-8')) for p in papers]}
    (BANK / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'output').mkdir(exist_ok=True)
    build_browser_data()


if __name__ == '__main__':
    main()
