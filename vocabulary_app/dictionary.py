"""离线词典查询：内置 ECDICT 精简库，支持词形还原与中文释义挑选。"""
from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "dict" / "dict.sqlite"

_lock = threading.Lock()
_connection: sqlite3.Connection | None = None

POS_LABELS = {"n": "n.", "v": "v.", "vt": "vt.", "vi": "vi.", "adj": "adj.", "adv": "adv.",
              "prep": "prep.", "conj": "conj.", "pron": "pron.", "num": "num.",
              "art": "art.", "int": "int.", "aux": "aux.", "abbr": "abbr."}

# 释义中优先展示的常见词性顺序
POS_ORDER = ["n", "v", "vt", "vi", "adj", "adv", "prep", "conj", "pron", "num", "int", "aux", "abbr"]


def available() -> bool:
    return DB.exists()


def _connect() -> sqlite3.Connection | None:
    global _connection
    if not DB.exists():
        return None
    with _lock:
        if _connection is None:
            _connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, check_same_thread=False)
            _connection.row_factory = sqlite3.Row
    return _connection


def _row_to_word(row: sqlite3.Row) -> dict:
    return {
        "word": row["word"],
        "phonetic": row["phonetic"] or "",
        "translation": row["translation"] or "",
        "pos": row["pos"] or "",
        "tag": row["tag"] or "",
        "forms": (row["forms"] or "").split(),
        "collins": row["collins"] or 0,
        "oxford": bool(row["oxford"]),
        "frequency": row["frq"] or 0,
    }


def candidates(word: str) -> list[str]:
    """给出同词可能的原形：复数、过去式、比较级等。"""
    word = word.strip().lower()
    guesses = [word]
    if word.endswith("ies") and len(word) > 4:
        guesses.append(word[:-3] + "y")
    if word.endswith("es") and len(word) > 3:
        guesses.append(word[:-2])
    if word.endswith("s") and len(word) > 3:
        guesses.append(word[:-1])
    if word.endswith("ed") and len(word) > 3:
        guesses.extend([word[:-2], word[:-1]])
        if len(word) > 4 and word[-3] == word[-4]:
            guesses.append(word[:-3])
    if word.endswith("ing") and len(word) > 5:
        stem = word[:-3]
        guesses.extend([stem, stem + "e"])
        if len(stem) > 2 and stem[-1] == stem[-2]:
            guesses.append(stem[:-1])
    if word.endswith("er") and len(word) > 4:
        guesses.append(word[:-2])
    if word.endswith("est") and len(word) > 5:
        guesses.append(word[:-3])
    if word.endswith("ly") and len(word) > 4:
        guesses.append(word[:-2])
    return list(dict.fromkeys(guesses))


INFLECTION_NOTE = re.compile(r"的(过去式|过去分词|现在分词|复数|第三人称单数|比较级|最高级)")


def _prefer_base(word: str) -> list[str]:
    """变形词条在 ECDICT 里常以“xx 的过去式”作释义；优先查原形，释义更像词典。"""
    guesses = candidates(word)
    bases = [value for value in guesses[1:] if len(value) >= 2 and value != word]
    return [*bases, word]


def lookup(word: str) -> dict | None:
    """查询一个词：按“原形优先”的顺序直查，再查词形索引。"""
    connection = _connect()
    if connection is None or not word:
        return None
    cleaned = re.sub(r"[^A-Za-z' -]", "", word).strip().lower()
    if not cleaned:
        return None
    order = _prefer_base(cleaned)
    row = None
    with _lock:
        for guess in order:
            row = connection.execute("SELECT * FROM words WHERE word=?", (guess,)).fetchone()
            if row is not None:
                break
        if row is None:
            index = connection.execute("SELECT word FROM forms WHERE form=?", (cleaned,)).fetchone()
            if index is not None:
                row = connection.execute("SELECT * FROM words WHERE word=?", (index["word"],)).fetchone()
    if row is None:
        return None
    result = _row_to_word(row)
    result["queried"] = word
    result["inflected_note"] = bool(INFLECTION_NOTE.search(result["translation"]))
    result["senses"] = pick_senses(result["translation"], cleaned)
    return result


def pick_senses(translation: str, word: str = "") -> list[dict]:
    """把 ECDICT 的长释义整理成“词性 + 若干义项”的清单，便于挑选。"""
    senses: list[dict] = []
    for line in translation.splitlines():
        line = line.strip()
        if not line or line.startswith("["):
            continue
        match = re.match(r"^([a-z]{1,5})\.\s*(.+)$", line)
        if match:
            sense_pos = match.group(1)
            body = match.group(2)
        else:
            sense_pos = ""
            body = line
        items = [item.strip(" ；;") for item in re.split(r"[；;]", body) if item.strip(" ；;")]
        for item in items[:6]:
            senses.append({"pos": POS_LABELS.get(sense_pos, sense_pos), "meaning": item})
    order = {key: index for index, key in enumerate(POS_ORDER)}
    senses.sort(key=lambda item: order.get(item["pos"].rstrip("."), 99))
    return senses[:12]


def brief(word: str, limit: int = 2) -> str:
    """一句话摘要，用于列表里快速预览。"""
    result = lookup(word)
    if not result:
        return ""
    senses = result["senses"][:limit]
    return "；".join(f"{item['pos']} {item['meaning']}" if item["pos"] else item["meaning"]
                     for item in senses)
