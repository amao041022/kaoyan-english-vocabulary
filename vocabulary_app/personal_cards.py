"""个人词库卡片：与页面上的 PersonalCore 完全一致的校验、编号与形状。

工作台收集的词最终以“个人词条卡片”的形式进入浏览器里的个人词库，
所以编号算法和字段限制必须和 `assets/personal-core.js` 逐字一致：
只要有一张卡片不符合，页面的 PersonalLibrary.sync() 就会抛错，
整套个人词库都会失效。这里用 Python 复刻同一套规则，
并在 tests/test_personal_cards.py 里与 node 端的结果逐条比对。
"""
from __future__ import annotations

import re
import unicodedata

# 字段长度上限，取自 personal-core.js 的 text(value,max,...) 调用
LIMITS = {
    "lemma": 100, "word": 100, "meaning": 1000, "common": 10000,
    "ipa": 200, "ipaLabel": 100, "targetId": 100,
}
CONTEXT_LIMITS = {"example": 10000, "translation": 10000, "section_id": 120,
                  "section_title": 200, "source_group": 100, "location": 200,
                  "kind": 40, "sourceUrl": 400}
CONTEXT_KINDS = {"passage", "paragraph_option", "option", "question",
                 "directions", "writing", "saved", "manual"}
RESERVED_IDS = {"__proto__", "constructor", "prototype"}
POS_PREFIX = re.compile(r"^(?:(?:n|v|vt|vi|adj|adv|a|prep|pron|conj)\.\s*)+")
TRAILING = re.compile(r"[。；;\s]+$")

# 本机应用场景 → 个人词库的例句类型
KIND_BY_CATEGORY = {
    "exam": "passage",
    "news": "saved",
    "book": "saved",
    "other": "manual",
}
CATEGORY_LABEL = {"exam": "真题试卷", "news": "外刊文章", "book": "书籍", "other": "其他材料"}


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", text).strip().lower()


def meaning_key(value: str) -> str:
    return TRAILING.sub("", POS_PREFIX.sub("", normalize(value)))


def _fnv(text: str) -> str:
    """复刻 JS 的双 32 位哈希：a 用 FNV-1a，b 用 djb2 异或。"""
    a, b = 2166136261, 5381
    for char in text:
        code = ord(char)
        a = (a ^ code) * 16777619 & 0xFFFFFFFF
        b = ((b * 33) & 0xFFFFFFFF) ^ code
    return f"{a:08x}{b:08x}"


def card_id(lemma: str, meaning: str, target_id: str = "") -> str:
    return "pc-" + _fnv(f"{normalize(lemma)}\n{meaning_key(meaning)}\n{target_id}")


def valid_id(value: str) -> bool:
    return bool(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value or "")
                and value not in RESERVED_IDS)


def _check(value: object, limit: int, label: str, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"{label}格式无效或过长")
    return value.strip()


def build_context(payload: dict) -> dict:
    """按 personal-core.js 的 context() 生成例句对象。"""
    out = {key: _check(payload.get(key) or "", limit, f"例句{key}", key == "example")
           for key, limit in CONTEXT_LIMITS.items()}
    if out["sourceUrl"] and not re.fullmatch(r"exams/\d{4}\.html#[A-Za-z0-9_-]+", out["sourceUrl"]):
        raise ValueError("例句来源链接无效")
    if out["kind"] not in CONTEXT_KINDS:
        raise ValueError("例句类型无效")
    return out


def link_note(link: str, name: str = "") -> str:
    """个人词库的例句没有链接字段，把出处写进位置说明里，仍然可回溯。"""
    link = (link or "").strip()
    if not link:
        return ""
    return f"原文链接：{link}"[:CONTEXT_LIMITS["location"] - 4]


def build_card(payload: dict, now_ms: int, target_id: str = "") -> dict:
    """把工作台的一条记录变成合法的个人词库卡片。

    抛 ValueError 表示这条卡片不合法（调用方应当提示用户补全，而不是写进去）。
    """
    lemma = _check(payload.get("lemma") or payload.get("word") or "", LIMITS["lemma"], "lemma", True)
    word = _check(payload.get("form") or payload.get("word") or lemma, LIMITS["word"], "word", True)
    meaning = _check(payload.get("meaning") or payload.get("short_meaning")
                     or payload.get("common") or "", LIMITS["meaning"], "meaning", True)
    if not re.search(r"[A-Za-z]", lemma) or re.search(r"[<>\x00-\x1f]", lemma + word):
        raise ValueError("请输入有效英文词或短语")
    if target_id and not valid_id(target_id):
        raise ValueError("关联学习单元无效")
    card = {
        "lemma": lemma,
        "word": word,
        "meaning": meaning,
        "common": _check(payload.get("common") or "", LIMITS["common"], "common"),
        "ipa": _check(payload.get("ipa") or "", LIMITS["ipa"], "ipa"),
        "ipaLabel": _check(payload.get("ipaLabel") or "", LIMITS["ipaLabel"], "ipaLabel"),
        "targetId": target_id,
    }
    card["id"] = card_id(lemma, meaning, target_id)
    forms = payload.get("forms") or [word]
    forms = [str(value) for value in forms if str(value).strip()][:30]
    if not forms:
        forms = [word]
    card["forms"] = list(dict.fromkeys([lemma, *forms]))[:30]
    if len(card["forms"]) > 30:
        raise ValueError("词形超过30个")
    contexts = payload.get("contexts") or []
    if len(contexts) > 30:
        raise ValueError("例句过多，每个义项最多30条")
    card["contexts"] = [build_context(item) for item in contexts]
    created = payload.get("createdAt") if isinstance(payload.get("createdAt"), int) else now_ms
    updated = payload.get("updatedAt") if isinstance(payload.get("updatedAt"), int) else created
    for key, value in (("createdAt", created), ("updatedAt", updated)):
        if not isinstance(value, int) or not (0 <= value <= 4102444800000):
            raise ValueError("词条时间无效")
        card[key] = value
    return card


def context_from_entry(entry: dict, category: str) -> dict:
    """从生词条目的原句与位置生成个人词库的例句对象。"""
    location = entry.get("location") or "摘录段落"
    note = link_note(entry.get("link") or "", entry.get("source_name") or "")
    if note:
        location = f"{location} · {note}"[:CONTEXT_LIMITS["location"]]
    source_url = ""
    if category == "exam" and entry.get("year") and entry.get("exam_record_id"):
        anchor = str(entry["exam_record_id"]).split(":")[-1]
        candidate = f"exams/{int(entry['year'])}.html#{anchor}"
        if re.fullmatch(r"exams/\d{4}\.html#[A-Za-z0-9_-]+", candidate):
            source_url = candidate
    return build_context({
        "example": entry.get("example") or "",
        "translation": entry.get("translation") or "",
        "section_id": entry.get("section_id") or "personal",
        "section_title": entry.get("section_title") or "个人收词",
        "source_group": entry.get("source_group") or "个人收词",
        "location": location,
        "kind": KIND_BY_CATEGORY.get(category, "manual"),
        "sourceUrl": source_url,
    })


def validate_card(card: dict) -> dict:
    """独立复核：确认一张卡片能被页面的 PersonalCore.validateCard 接受。"""
    if not isinstance(card, dict):
        raise ValueError("个人词条格式无效")
    for key, limit in LIMITS.items():
        _check(card.get(key) or "", limit, key, key in ("lemma", "word", "meaning"))
    if card["targetId"] and not valid_id(card["targetId"]):
        raise ValueError("关联学习单元无效")
    expected = card_id(card["lemma"], card["meaning"], card["targetId"])
    if card.get("id") != expected:
        raise ValueError(f"词条编号与词义不一致：{card.get('id')} != {expected}")
    forms = card.get("forms")
    if not isinstance(forms, list) or len(forms) > 30:
        raise ValueError("词形数量无效")
    contexts = card.get("contexts")
    if not isinstance(contexts, list) or len(contexts) > 30:
        raise ValueError("例句过多，每个义项最多30条")
    for item in contexts:
        build_context(item)
    for key in ("createdAt", "updatedAt"):
        value = card.get(key)
        if not isinstance(value, int) or not (0 <= value <= 4102444800000):
            raise ValueError("词条时间无效")
    return card


def cards_from_entries(entries: list[dict], now_ms: int) -> tuple[list[dict], list[str]]:
    """把工作台记录批量转成卡片；返回 (卡片列表, 错误说明)。"""
    cards: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        category = entry.get("category") or ("exam" if entry.get("year") else "other")
        try:
            card = build_card({
                "lemma": entry.get("lemma"),
                "word": entry.get("form") or entry.get("lemma"),
                "meaning": entry.get("meaning") or entry.get("short_meaning") or entry.get("common"),
                "common": entry.get("common") or "",
                "ipa": entry.get("ipa") or "",
                "forms": entry.get("forms") or [],
                "contexts": [context_from_entry(entry, category)],
                "capturedAt": entry.get("captured_at"),
            }, now_ms=now_ms)
            if card["id"] in seen:
                errors.append(f"{card['lemma']}：同一义项重复")
                continue
            seen.add(card["id"])
            card["capturedAt"] = entry.get("captured_at") or ""
            card["category"] = category
            cards.append(card)
        except ValueError as error:
            errors.append(f"{entry.get('lemma') or entry.get('form') or '?'}：{error}")
    return cards, errors
