"""生词库读写：把工作台确认的词条写进 data/vocabulary_additions.json。

主词库 data/vocabulary.json 保持只读，由 main.py 统一合并生成页面，
这样历史条目、学习进度和原有校验规则都不会被工作台破坏。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "data" / "vocabulary.json"
ADDITIONS = ROOT / "data" / "vocabulary_additions.json"
PENDING = ROOT / "data" / "pending_words.json"

SECTION_NAMES = {"cloze": "完形填空", **{f"text{i}": f"阅读 Text {i}" for i in range(1, 5)},
                 "new_type": "新题型", "translation": "翻译",
                 "writing_a": "小作文", "writing_b": "大作文"}
WORD_RE = re.compile(r"^[A-Za-z][A-Za-z' -]{0,40}$")

# 阅读场景：决定来源分组怎么显示，也方便生词本按场景筛选
CATEGORY_LABELS = {
    "exam": "真题试卷",
    "news": "外刊文章",
    "book": "书籍",
    "other": "其他材料",
}
CATEGORY_ORDER = ["exam", "news", "book", "other"]


def empty_additions() -> dict:
    return {"schema_version": 1, "title": "工作台新增生词", "notes": [
        "由 vocabulary_app 工作台写入；main.py 会把它合并进生词库生成页面。",
        "每条记录保留来源、原句与位置；词形变化必须在原文中出现过。",
        "personal_cards 是同一批词的个人词库卡片，页面启动时并入个人词库。",
    ], "entries": [], "source_images": [], "personal_cards": []}


def load_additions() -> dict:
    if not ADDITIONS.exists():
        return empty_additions()
    data = json.loads(ADDITIONS.read_text(encoding="utf-8"))
    data.setdefault("entries", [])
    data.setdefault("source_images", [])
    data.setdefault("personal_cards", [])
    return data


def save_additions(data: dict) -> None:
    ADDITIONS.parent.mkdir(parents=True, exist_ok=True)
    ADDITIONS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_personal_cards(cards: list[dict]) -> int:
    """把个人词库卡片写进 additions；同编号覆盖，避免重复。"""
    if not cards:
        return 0
    data = load_additions()
    existing = {card.get("id"): index for index, card in enumerate(data["personal_cards"])}
    added = 0
    for card in cards:
        position = existing.get(card.get("id"))
        if position is None:
            data["personal_cards"].append(card)
            added += 1
        else:
            data["personal_cards"][position] = card
    save_additions(data)
    return added


def load_personal_cards() -> list[dict]:
    return load_additions().get("personal_cards", [])


def load_pending() -> dict:
    if not PENDING.exists():
        return {"schema_version": 1, "words": []}
    return json.loads(PENDING.read_text(encoding="utf-8"))


def save_pending(data: dict) -> None:
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_pending(word: str, locations: list[dict] | None = None, source: str = "") -> dict:
    """查词时“加入待整理”：只记词和位置，不写入生词本，避免误当生词。"""
    word = (word or "").strip()
    if not WORD_RE.match(word):
        raise ValueError(f"不能加入待整理清单的词形：{word!r}")
    data = load_pending()
    known = {item["word"].casefold() for item in data["words"]}
    if word.casefold() in known:
        return {"added": False, "word": word}
    data["words"].append({"word": word, "source": source,
                          "locations": (locations or [])[:6],
                          "added_at": __import__("datetime").datetime.now().isoformat(timespec="seconds")})
    save_pending(data)
    return {"added": True, "word": word}


def load_main() -> dict:
    return json.loads(MAIN.read_text(encoding="utf-8")) if MAIN.exists() else empty_additions()


def all_entries() -> list[dict]:
    main = load_main()
    additions = load_additions()
    return [*main.get("entries", []), *additions.get("entries", [])]


def lemma_index() -> dict[str, dict]:
    """把词形变化映射回词条，用于“这个词已经在生词本里吗”。"""
    index: dict[str, dict] = {}
    for entry in all_entries():
        for value in {entry.get("lemma", ""), entry.get("form", ""), *entry.get("forms", [])}:
            if value:
                index.setdefault(value.casefold(), entry)
    return index


def next_id(prefix: str, entries: list[dict]) -> str:
    used = {entry["id"] for entry in entries}
    stem = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-") or "word"
    serial = 1
    while f"{stem}-{serial:02d}" in used:
        serial += 1
    return f"{stem}-{serial:02d}"


def form_pattern(forms: list[str]) -> re.Pattern[str]:
    """只匹配明确列出的词形，边界按字母判断，避免 inherit 命中 inherent。"""
    values = [value for value in dict.fromkeys(forms) if value and value.strip()]
    if not values:
        raise ValueError("没有可匹配的词形")
    alternatives = "|".join(re.escape(value) for value in sorted(values, key=len, reverse=True))
    return re.compile(r"(?<![A-Za-z])(?:" + alternatives + r")(?![A-Za-z])", re.I)


def normalise_link(value: str) -> str:
    """只保留 http/https 链接，并去掉跟踪参数，方便以后回原文。"""
    value = (value or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.I):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", value, re.I):
            value = "https://" + value
        else:
            return ""
    value = value[:2000]
    try:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        parts = urlsplit(value)
        drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                "fbclid", "gclid", "ref", "ref_src"}
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                           if k not in drop])
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except ValueError:
        return value


def _section_id(category: str, name: str, material_id: str) -> str:
    """给来源一个可读且稳定的分组标识，例如 read-news-纽约时报-a1b2c3。"""
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", name or "")[:14]
    tail = re.sub(r"[^0-9a-z]+", "", (material_id or "")[:6])
    return "-".join(part for part in ("read", category or "other", slug, tail) if part)


def source_label(category: str, name: str) -> str:
    """来源分组标题：按场景归一，避免同一来源被拆成多组。"""
    prefix = CATEGORY_LABELS.get(category, "")
    name = (name or "").strip()
    if category == "exam":
        return name or "真题试卷"
    if prefix and name:
        return f"{prefix}｜{name}"
    return name or prefix or "阅读材料"


def make_entry(payload: dict, entries: list[dict]) -> dict:
    """按主词库的字段规范补全一条记录；缺字段直接报错，不写入半成品。"""
    lemma = (payload.get("lemma") or "").strip()
    if not WORD_RE.match(lemma):
        raise ValueError(f"词形不合法：{lemma!r}")
    example = (payload.get("example") or "").strip()
    if not example:
        raise ValueError("缺少原句：没有原文证据的词不写入生词本")
    raw_forms = [value.strip() for value in (payload.get("forms") or []) if value and value.strip()]
    # 词形表至少包含原形与文中形式，否则复现统计会漏掉这个词
    forms = list(dict.fromkeys([*raw_forms, lemma, (payload.get("form") or lemma).strip()]))
    if not form_pattern(forms).search(example):
        raise ValueError(f"原句里找不到 {lemma} 的任何已知词形，请核对词形或改回原文写法")
    category = (payload.get("category") or "").strip()
    if category not in CATEGORY_LABELS:
        category = "exam" if payload.get("year") else ("book" if payload.get("book_title") else "other")
    source_name = (payload.get("source_name") or payload.get("book_title") or "").strip()
    link = normalise_link(payload.get("link") or payload.get("url") or "")
    source_group = (payload.get("source_group") or "").strip() or source_label(category, source_name) or (
        f"{payload['year']} 英语（一）" if payload.get("year") else "阅读材料")
    entry = {
        "id": payload.get("id") or next_id(f"{payload.get('year') or 'rd'}-{lemma}", entries),
        "section_id": payload.get("section_id") or _section_id(category, source_name,
                                                              payload.get("material_id", "")),
        "section_title": payload.get("section_title") or f"{source_group}｜{payload.get('material_name', '阅读材料')}",
        "year": payload.get("year"),
        "category": category,
        "source_group": source_group,
        "source_name": source_name,
        "link": link,
        "photo": payload.get("photo") or "",
        "lemma": lemma,
        "form": (payload.get("form") or lemma).strip(),
        "ipa": (payload.get("ipa") or "").strip(),
        "pos": (payload.get("pos") or "").strip(),
        "common": (payload.get("common") or "").strip(),
        "meaning": (payload.get("meaning") or "").strip(),
        "short_meaning": (payload.get("short_meaning") or payload.get("meaning")
                          or payload.get("common") or "").strip(),
        "location": (payload.get("location") or "阅读材料").strip(),
        "example": example,
        "translation": (payload.get("translation") or "").strip(),
        "note": (payload.get("note") or "").strip(),
        "forms": forms,
        "additional_evidence": payload.get("additional_evidence") or [],
    }
    if not entry["short_meaning"]:
        # 释义留空也允许先入库，但不能是空字符串导致页面校验失败
        entry["short_meaning"] = entry["common"] or entry["lemma"]
    for key in ("exam_record_id", "crop", "page", "mark_kind", "capture", "captured_at"):
        if payload.get(key):
            entry[key] = payload[key]
    return entry
