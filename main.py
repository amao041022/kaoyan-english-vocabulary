"""从统一词库生成复习页面。仅使用 Python 标准库，运行：python main.py。"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote
from study_build import build_study, PRACTICE_BODY
from exam_bank import build_browser_data

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "vocabulary.json"
ADDITIONS = ROOT / "data" / "vocabulary_additions.json"
OUT = ROOT / "output"


def load_vocabulary() -> dict:
    """主词库保持只读；本机应用工作台新增的词在 vocabulary_additions.json，这里合并。

    这样历史条目、学习进度和原有校验都不会被工作台改写，
    删除 additions 文件即可回到原状。
    """
    data = json.loads(DATA.read_text(encoding="utf-8"))
    if not ADDITIONS.exists():
        return data
    additions = json.loads(ADDITIONS.read_text(encoding="utf-8"))
    existing = {entry["id"] for entry in data["entries"]}
    merged = [entry for entry in additions.get("entries", []) if entry.get("id") not in existing]
    if not merged:
        return data
    photos = {image["filename"] for image in data["source_images"]}
    data["entries"] = [*data["entries"], *merged]
    data["source_images"] = [*data["source_images"],
                             *[image for image in additions.get("source_images", [])
                               if image.get("filename") not in photos]]
    return data


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def pattern(forms: list[str]) -> re.Pattern[str]:
    """只匹配明确保存的原形/变形，避免 inherit 与 inherent 等误合并。"""
    alternatives = "|".join(re.escape(s) for s in sorted(set(forms), key=len, reverse=True))
    return re.compile(r"(?<![A-Za-z])(?:" + alternatives + r")(?![A-Za-z])", re.I)


def context_key(context: dict) -> tuple[str, str]:
    # 同句共用例句只计一次；位置说明的差异不制造新的复现。
    sentence = re.sub(r"\s+", " ", context["example"]).strip()
    return context["section_id"], sentence


def build_index(data: dict) -> tuple[dict, dict]:
    contexts: dict[tuple, dict] = {}
    families: dict[str, list[dict]] = defaultdict(list)
    for entry in data["entries"]:
        families[entry["lemma"].casefold()].append(entry)
        for context in [entry, *entry.get("additional_evidence", [])]:
            contexts.setdefault(context_key(context), context)
    for context in data.get("extra_contexts", []):
        contexts.setdefault(context_key(context), context)
    index = {}
    for lemma, entries in families.items():
        matcher = pattern([form for entry in entries for form in entry["forms"]])
        hits = [context for context in contexts.values() if matcher.search(context["example"])]
        hits.sort(key=lambda c: (c.get("year") or 9999, c["section_id"], c["location"]))
        index[lemma] = {"entries": entries, "matcher": matcher, "hits": hits,
                        "passages": len({c["section_id"] for c in hits})}
    return index, contexts


def validate(data: dict) -> None:
    ids: set[str] = set()
    images = {source["filename"] for source in data["source_images"]}
    # 只有页面渲染必须用到的字段是硬性要求；photo 与释义/翻译允许留空，
    # 本机应用工作台新增的词可以先入库、之后再补（页面对空字段跳过不显示）。
    required = ("id", "section_id", "section_title", "lemma", "form",
                "ipa", "short_meaning", "location", "example", "forms")
    for entry in data["entries"]:
        if any(not entry.get(key) for key in required):
            raise ValueError(f"词条字段缺失：{entry.get('id')}")
        if entry["id"] in ids:
            raise ValueError(f"词条 ID 重复：{entry['id']}")
        if entry.get("year") is None and not entry.get("source_group"):
            raise ValueError(f"年份未知时须填写来源分组：{entry['id']}")
        ids.add(entry["id"])
        if entry.get("photo") and entry["photo"] not in images:
            raise ValueError(f"来源照片未登记：{entry['id']}")
        if not pattern(entry["forms"]).search(entry["example"]):
            raise ValueError(f"例句不含对应词形：{entry['id']}")


def highlighted(text: str, matcher: re.Pattern[str]) -> str:
    parts, last = [], 0
    for match in matcher.finditer(text):
        parts.extend([escape(text[last:match.start()]), "<mark>" + escape(match.group()) + "</mark>"])
        last = match.end()
    parts.append(escape(text[last:]))
    return "".join(parts)


def excerpt(sentence: str, matcher: re.Pattern[str], width: int = 132) -> str:
    """仅截取原句连续片段，保留完整词语，省略位置明确显示省略号。"""
    if len(sentence) <= width:
        return sentence
    match = matcher.search(sentence)
    start = max(0, (match.start() if match else 0) - 42)
    if start:
        previous_space = sentence.rfind(" ", 0, start)
        start = previous_space + 1
    end = min(len(sentence), max(start + width, match.end() if match else 0))
    if end < len(sentence):
        next_space = sentence.find(" ", end)
        end = next_space if next_space >= 0 else len(sentence)
    return ("… " if start else "") + sentence[start:end] + (" …" if end < len(sentence) else "")


def repeat_anchor(lemma: str) -> str:
    return "r-" + hashlib.sha256(lemma.encode("utf-8")).hexdigest()[:12]


def badge(lemma: str, info: dict) -> str:
    if len(info["hits"]) < 2:
        return ""
    label = f"跨篇复现 · {info['passages']}篇" if info["passages"] > 1 else f"同篇复现 · {len(info['hits'])}处"
    return f'<a class="repeat" href="复现词汇.html#{repeat_anchor(lemma)}">↻ {label}</a>'



# 音频按实际朗读文本寻址，同一句共用音频；页面仍完整保留原文。
AUDIO_TEXTS: dict[str, str] = {}
STUDY: dict = {"units": [], "entryUnits": {}}


def speech_text(text: str) -> str:
    """保留英文内容；空格读 blank，常见金额缩写展开以免误读。"""
    text = re.sub(r"__\d+__|_{2,}", " blank ", text)
    text = re.sub(r"\$(\d+(?:\.\d+)?)bn\b", r"\1 billion dollars", text)
    text = re.sub(r"\$(\d+(?:\.\d+)?)m\b", r"\1 million dollars", text)
    return re.sub(r"\s+", " ", text).strip()


def audio_url(text: str) -> str:
    spoken = speech_text(text)
    key = hashlib.sha256(spoken.encode("utf-8")).hexdigest()[:24]
    AUDIO_TEXTS[key] = spoken
    return f"audio/{key}.wav"


def audio_button(text: str, label: str) -> str:
    url = audio_url(text)
    return (f'<button type="button" class="speak" data-audio="{url}" '
            f'data-label="{escape(label)}" aria-label="美音朗读{escape(label)}" '
            f'title="美音朗读{escape(label)}">▶ <span>{escape(label)}</span></button>')



def mastery_tag(uid: str, label: str = "") -> str:
    if not uid:
        return ""
    return (f'<button type="button" class="mastery" data-unit-id="{escape(uid)}" '
            f'title="查看学习记录">{escape(label)}<span>未学</span></button>')


def repeat_mastery(lemma: str, context: dict | None = None) -> str:
    units = [u for u in STUDY["units"] if u["lemma"].casefold() == lemma.casefold()]
    if context:
        exact = [u for u in units if any(c["section_id"] == context["section_id"] and
                 c["example"] == context["example"] for c in u["contexts"])]
        if not exact:
            return '<span class="note">补充语境；请按上方已收录义项查看掌握程度</span>'
        units = exact
    return " ".join(mastery_tag(u["id"], (u["gloss"] + " · ") if len(units)>1 else "") for u in units)


def source_group(entry: dict) -> str:
    return entry.get("source_group") or f'{entry["year"]} 英语（一）'


AUDIO_CONTROLS = """<div class="audio-toolbar" aria-label="美音朗读设置">
<strong>美音朗读</strong><span class="note">Zira · 离线音频</span>
<label>语速 <select id="audio-rate" aria-label="朗读语速">
<option value="0.7">0.7× 慢速</option><option value="0.85">0.85×</option>
<option value="1" selected>1.0× 正常</option><option value="1.2">1.2×</option>
<option value="1.5">1.5×</option></select></label>
<button type="button" id="audio-stop">停止</button>
<span id="audio-status" role="status" aria-live="polite">点击单词或例句旁的 ▶ 朗读</span>
</div>"""

CSS = """
*{box-sizing:border-box}body{margin:0;background:#fff;color:#243341;font:14px/1.5 'Microsoft YaHei','Segoe UI',sans-serif}main{max-width:1460px;margin:auto;padding:18px 24px}h1{font-size:22px;margin:0}header{border-bottom:2px solid #216458;padding-bottom:10px;display:flex;flex-wrap:wrap;align-items:center;gap:12px 24px}nav{display:flex;flex-wrap:wrap;gap:16px}a{color:#216458;text-underline-offset:3px}.intro,.note{color:#63736d;font-size:12px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:8px 0;background:white}.toolbar input[type=search]{min-width:220px;flex:1}.toolbar input,.toolbar select{font:inherit;padding:6px 8px;border:1px solid #c5d4ca;border-radius:5px}h2{font-size:16px;background:#f0f5f1;border-left:3px solid #216458;padding:6px 9px;margin:16px 0 0;color:#215b4e}.entry{padding:7px 8px;border-bottom:1px solid #e4e9e5;break-inside:avoid}.definition{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}.word{font-size:15px}.num{color:#89978d;font-size:11px;min-width:22px}.ipa{font-family:'Segoe UI',Arial,sans-serif;color:#60706a;font-size:13px}.meaning{color:#215b4e}.repeat{font-size:11px;background:#fff1cb;color:#80540b;padding:1px 6px;border-radius:4px;text-decoration:none}.sentence{font:13px/1.5 'Segoe UI',Arial,sans-serif;overflow-wrap:anywhere}.entry details{margin:3px 0 0 34px}summary{cursor:pointer;list-style:none}summary::-webkit-details-marker{display:none}summary:hover{color:#216458}summary:focus-visible{outline:2px solid #216458}summary .kind{font-size:10px;color:#7d8e82;margin-left:12px}summary .kind:after{content:' ＋'}details[open] .kind:after{content:' −'}mark{background:#e8f2e8;color:#154f3f;font-weight:700;padding:0 2px}.full{margin:8px 0 4px;padding:9px 13px;border-left:2px solid #b8d1bf;background:#f6f8f5;font-size:13px}.full p{margin:5px 0;overflow-wrap:anywhere}.full .sentence{font-size:15px}.detail-view .entry{padding:16px;margin:12px 0;border:1px solid #dce6dc;border-radius:8px}.detail-view .full{margin-left:0}.hit{margin:8px 0;padding:8px 12px;border-left:2px solid #d4dfd4;background:#f7f9f6}.hit p{margin:5px 0;overflow-wrap:anywhere}.hit .where{font-size:12px;color:#63736d}footer{margin-top:24px;font-size:12px;color:#718076}#empty{padding:25px;color:#64756a}[hidden]{display:none!important}.jump-list{line-height:2.2;display:flex;flex-wrap:wrap;gap:2px 14px}
.speak{font-family:inherit;line-height:1.4;font-size:11px;cursor:pointer;border:1px solid #c4d8cd;color:#216458;background:#f5faf6;border-radius:4px;padding:1px 5px;margin:0 5px;white-space:nowrap;vertical-align:baseline}.speak:hover,.speak.playing{background:#d8eddd}.speak:focus-visible{outline:2px solid #216458}.audio-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:7px 9px;margin:8px 0;border:1px solid #dce6dc;border-radius:5px;font-size:12px}.audio-toolbar select,.audio-toolbar button{font:inherit;padding:3px 6px}.audio-toolbar #audio-status{color:#53695d}.audio-toolbar #audio-status.error{color:#a43228}.audio-toolbar button{cursor:pointer}.entry summary .speak{float:right}
.source-link{font-size:11px;background:#eef4f7;color:#2a5aa8;padding:1px 6px;border-radius:4px;text-decoration:none;border:1px solid #d3e0ea}
.source-link:hover{background:#e2edf5}
@media(max-width:640px){main{padding:12px 10px}h1{font-size:18px}.definition{gap:3px 9px}.meaning{width:100%;padding-left:31px}.entry{padding:7px 3px}.entry details{margin-left:31px}.toolbar{gap:7px}.toolbar select{max-width:100%}.repeat{margin-left:31px}.full .meaning{padding-left:0}}
@media print{@page{margin:10mm}main{padding:0}nav,.toolbar,.intro,footer,.audio-toolbar,.speak{display:none}header{padding-bottom:5px}h1{font-size:16px}h2{font-size:13px;break-after:avoid}.entry{padding:5px 3px}.word{font-size:12px}.ipa,.meaning,.sentence{font-size:10px}.repeat{border:1px solid #d2b86d}.full{font-size:10px}.full .sentence{font-size:11px}}
"""

SCRIPT = """
const query=document.querySelector('#query'),year=document.querySelector('#year'),repeat=document.querySelector('#only-repeat');
function filterEntries(){
 const term=query.value.trim().toLocaleLowerCase();let visible=0;
 document.querySelectorAll('.entry').forEach(row=>{row.hidden=!!((year.value&&row.dataset.year!==year.value)||(repeat.checked&&row.dataset.repeated!=='yes')||(term&&!row.dataset.search.includes(term)));if(!row.hidden)visible++;});
 document.querySelectorAll('section').forEach(section=>{section.hidden=!Array.from(section.querySelectorAll('.entry')).some(row=>!row.hidden);});
 document.querySelector('#count').textContent='显示 '+visible+' 条';document.querySelector('#empty').hidden=visible!==0;
}
if(query){[query,year,repeat].forEach(control=>control.addEventListener('input',filterEntries));const requestedYear=new URLSearchParams(location.search).get('year');if(requestedYear){const found=Array.from(year.options).find(option=>option.value===requestedYear||option.value.startsWith(requestedYear+' '));if(found)year.value=found.value;}filterEntries();}
"""


def document(title: str, body: str, index: dict, detailed: bool = False) -> str:
    cross = sum(info["passages"] > 1 for info in index.values())
    bank_link = '<a href="真题检索.html">真题检索</a>' if (ROOT / 'data' / 'exam_bank' / 'manifest.json').exists() else ''
    app_link = '<a href="../webapp/app.html" title="上传试卷、识别圈画生词、摘录外刊">上传整理</a>' if (ROOT / 'webapp' / 'app.html').exists() else ''
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>{CSS}</style><link rel="stylesheet" href="study.css"></head>
<body><div id="save-warning" role="alert" hidden></div><main class="{'detail-view' if detailed else 'compact-view'}"><header><h1>{escape(title)}</h1><nav><a href="index.html">简短总复习</a><a href="全部生词_完整版.html">完整版</a><a href="复现词汇.html">复现词汇</a><a href="背词练习.html">背词练习</a>{bank_link}{app_link}<a href="查词与收词.html">查词与收词</a><a href="2017英语一_阅读生词本_简短版.html">2017原版</a></nav></header>
<p class="intro">原始词库 {len(index)} 个词／搭配（个人收词另列于下方） · {cross} 个跨篇复现词。复现范围为已保存并核对的语境，不是试卷全文词频；不同语境均保留。原有音标保留原标注；个人查词音标以词典来源为准。</p>{AUDIO_CONTROLS}{body}<footer>原图与词库保存在项目内。复现按原形与明确词形变化匹配，派生词不自动合并。历史2017页面保持原样。</footer></main><script src="study-data.js"></script><script src="personal-cards.js"></script><script src="personal-core.js"></script><script src="study-core.js"></script><script src="progress.js"></script><script src="personal-library.js"></script><script src="speech.js"></script><script src="study-ui.js"></script><script src="personal-review.js"></script><script src="review-pages.js"></script><script src="practice.js"></script></body></html>'''


def source_link(context: dict) -> str:
    photos = context.get("source_photos") or [context["photo"]]
    links = [f'<a href="../images/{quote(photo)}">{"原卷PDF" if photo.lower().endswith(".pdf") else "原图"}{i + 1 if len(photos) > 1 else ""}</a>' for i, photo in enumerate(photos)]
    if context.get('exam_anchor') and context.get('year'):
        links.append(f'<a href="exams/{int(context["year"])}.html#{escape(context["exam_anchor"])}">查看原文位置</a>')
    return " · ".join(links)


def render_entries(data: dict, index: dict, detailed: bool) -> str:
    sections: dict[str, list[dict]] = defaultdict(list)
    for entry in data["entries"]:
        sections[entry["section_id"]].append(entry)
    years = sorted({source_group(entry) for entry in data["entries"]})
    body = ['<div class="toolbar"><input id="query" type="search" placeholder="搜索单词、词义或来源" aria-label="搜索单词、词义或来源"><select id="year" aria-label="筛选材料"><option value="">全部材料</option>']
    body += [f'<option value="{escape(year)}">{escape(year)}</option>' for year in years]
    body.append('</select><label><input id="only-repeat" type="checkbox"> 仅看复现词</label><span id="count" class="note"></span></div>')
    body.append('<p class="note">每词一行词义、一行例句；长句以“…”显示原句节选，点击展开完整句和翻译。题目选项不代表正确答案。完形空格按题号保留。</p>')
    number = 0
    for sid, entries in sections.items():
        body.append(f'<section id="{escape(sid)}"><h2>{escape(entries[0]["section_title"])} · {len(entries)} 条</h2>')
        for entry in entries:
            number += 1
            lemma = entry["lemma"].casefold()
            info = index[lemma]
            matcher = info["matcher"]
            search = " ".join(str(entry.get(k, "")) for k in ("lemma", "display", "form", "common", "meaning", "section_title", "example")).lower()
            repeated = "yes" if len(info["hits"]) > 1 else "no"
            body.append(f'<article class="entry" id="{escape(entry["id"])}" data-year="{escape(source_group(entry))}" data-study-id="{escape(STUDY["entryUnits"].get(entry["id"],""))}" data-section="{escape(sid)}" data-repeated="{repeated}" data-search="{escape(search)}">')
            display = entry.get("display", entry["lemma"])
            link = entry.get("link") or ""
            link_html = (f'<a class="source-link" href="{escape(link)}" target="_blank" rel="noopener">回原文</a>'
                         if link else "")
            body.append(f'<div class="definition"><span class="num">{number:03}</span><strong class="word" title="原文词形：{escape(entry["form"])}">{escape(display)}</strong>{mastery_tag(STUDY["entryUnits"].get(entry["id"],""))}{audio_button(entry.get("speech_word", display), "单词")}<span class="ipa">{escape(entry["ipa"])}</span><span class="meaning">{escape(entry["short_meaning"])}</span>{link_html}{badge(lemma,info)}</div>')
            origin = entry.get("source_name") or ""
            link = entry.get("link") or ""
            link_html = (f'<a class="source-link" href="{escape(link)}" target="_blank" rel="noopener">回原文</a>'
                         if link else "")
            full = (f'<div class="full"><p class="note">{escape(entry["location"])}'
                    f'{" · 来源：" + escape(origin) if origin else ""}'
                    f' · 原文词形：{escape(entry["form"])} · {source_link(entry)}'
                    f'{" · " + link_html if link_html else ""}</p>')
            if entry.get("common"):
                full += f'<p>常见词义：{escape(entry["common"])}</p>'
            if entry.get("meaning"):
                full += f'<p>此处含义：{escape(entry["meaning"])}</p>'
            full += (f'<p class="sentence" lang="en">{highlighted(entry["example"],matcher)}'
                     f'{audio_button(entry["example"], "例句")}</p>')
            if entry.get("translation"):
                full += f'<p>{escape(entry["translation"])}</p>'
            if entry.get("note"):
                full += f'<p class="note">{escape(entry["note"])}</p>'
            full += "</div>"
            if detailed:
                body.append(full)
            else:
                location = entry["location"]
                kind = "正文" if "例句取正文" in location else "选项" if "选项" in location else "题干" if "题干" in location else "正文"
                body.append(f'<details><summary aria-label="展开{escape(display)}的原句与翻译"><span class="sentence" lang="en">{highlighted(excerpt(entry["example"],matcher),matcher)}</span><span class="kind">{kind}</span>{audio_button(entry["example"], "例句")}</summary>{full}</details>')
            body.append("</article>")
        body.append("</section>")
    body.append('<p id="empty" hidden>没有匹配词条，请调整搜索或筛选条件。</p>')
    return "".join(body)


def render_repeats(index: dict) -> str:
    repeated = [(lemma, info) for lemma, info in index.items() if len(info["hits"]) > 1]
    repeated.sort(key=lambda pair: (-pair[1]["passages"], pair[0]))
    parts = ['<p class="note">跨篇复现：出现在两个及以上不同篇章；同篇复现：同篇有两个及以上不同已保存语境。包含已核对的未划线复现位置。同一句只计一次。</p><div class="jump-list">']
    parts += [f'<a href="#{repeat_anchor(lemma)}">{escape(lemma)}（{info["passages"]}篇/{len(info["hits"])}处）</a>' for lemma, info in repeated]
    parts.append("</div>")
    for lemma, info in repeated:
        label = "跨篇复现" if info["passages"] > 1 else "同篇复现"
        parts.append(f'<section id="{repeat_anchor(lemma)}"><h2>{escape(lemma)} {repeat_mastery(lemma)} {audio_button(lemma, "单词")} · {label} · {info["passages"]}篇 / {len(info["hits"])}处已录入语境</h2>')
        for context in info["hits"]:
            parts.append(f'<div class="hit"><p class="where">{escape(context["section_title"])} · {escape(context["location"])} · {source_link(context)} · {repeat_mastery(lemma, context)}</p><p class="sentence" lang="en">{highlighted(context["example"],info["matcher"])}{audio_button(context["example"], "例句")}</p><p>{escape(context["translation"])}</p></div>')
        parts.append("</section>")
    return "".join(parts)


def main() -> None:
    global STUDY
    if sys.version_info < (3, 10):
        raise SystemExit("生成页面需要 Python 3.10 或更高版本；当前为 "
                         f"{sys.version_info.major}.{sys.version_info.minor}。"
                         "macOS 上请用 Homebrew 的 python3（例如 /opt/homebrew/bin/python3）。")
    AUDIO_TEXTS.clear()
    data = load_vocabulary()
    validate(data)
    additions = json.loads(ADDITIONS.read_text(encoding="utf-8")) if ADDITIONS.exists() else {}
    index, contexts = build_index(data)
    config = json.loads((ROOT / "data" / "study_config.json").read_text(encoding="utf-8"))
    STUDY = build_study(data, config, audio_url)
    OUT.mkdir(exist_ok=True)
    for filename, title, detailed in [("index.html", "考研英语 · 简短总复习", False), ("全部生词_完整版.html", "考研英语 · 生词完整版", True)]:
        (OUT / filename).write_text(document(title, render_entries(data,index,detailed), index, detailed), encoding="utf-8")
    (OUT / "复现词汇.html").write_text(document("考研英语 · 复现词汇",render_repeats(index),index),encoding="utf-8")
    (OUT / "背词练习.html").write_text(document("考研英语 · 背词练习", PRACTICE_BODY, index), encoding="utf-8")
    (OUT / "study-data.js").write_text("window.VOCAB_STUDY = " + json.dumps(STUDY, ensure_ascii=False) + ";\n", encoding="utf-8")
    # 工作台收集的词同时以个人词库卡片的形式发布，页面启动时并入个人词库
    cards = additions.get("personal_cards", [])
    (OUT / "personal-cards.js").write_text(
        "window.VOCAB_PERSONAL_CARDS = " + json.dumps(cards, ensure_ascii=False).replace("</", "<\\/") + ";\n",
        encoding="utf-8")
    summary = {"records":len(data["entries"]),"unique_lemmas":len(index),"study_units":len(STUDY["units"]),"saved_contexts":len(contexts),
               "cross_passage_words":{word:info["passages"] for word,info in index.items() if info["passages"]>1},
               "same_passage_repeats":{word:len(info["hits"]) for word,info in index.items() if info["passages"]==1 and len(info["hits"])>1},
               "by_section":dict((sid,sum(e["section_id"]==sid for e in data["entries"])) for sid in dict.fromkeys(e["section_id"] for e in data["entries"]))}
    (OUT / "整理统计.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT / "audio_manifest.json").write_text(json.dumps(
        [{"key": key, "text": text} for key, text in sorted(AUDIO_TEXTS.items())],
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for asset in (ROOT / "assets").iterdir():
        if asset.suffix in (".js", ".css", ".html"):
            shutil.copyfile(asset, OUT / asset.name)
    build_browser_data()
    if "--audio" in sys.argv:
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(ROOT / "scripts" / "generate_audio.ps1")], check=True)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
