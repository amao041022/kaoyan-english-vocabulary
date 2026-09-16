"""生成本机应用用的离线词典查询库（SQLite）。

数据来源是仓库里已有的 `data/dictionary/` 词典分片（ECDICT，浏览器端
`assets/dictionary.js` 用的同一份数据），所以项目里只有一份词典：

    python3 vocabulary_app/build_dict.py --shards data/dictionary

也可以直接从 ECDICT 的 CSV 生成（备用）：

    python3 vocabulary_app/build_dict.py /path/to/ecdict.csv

输出 data/dict/dict.sqlite，已在 .gitignore 里，不进版本库；
缺少时“启动生词本”会自动生成一次。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SHARDS = ROOT / "data" / "dictionary"
OUT = ROOT / "data" / "dict" / "dict.sqlite"

POS_KEEP = {"n", "v", "vt", "vi", "adj", "adv", "prep", "conj", "pron", "art",
            "num", "int", "aux", "abbr", "a", "ad", "pl", "na", "u", "c"}

NOISE = re.compile(r"\[网络\]|\[医\]|\[化\]|\[机\]|\[法\]|\[经\]|\[电\]|\[生\]|\[计\]")
EXCHANGE_KEYS = {"p", "d", "i", "3", "r", "t", "s"}   # 过去式/过去分词/现在分词/三单/比较级/最高级/复数


def clean_translation(value: str) -> str:
    """压掉词典里的行业噪声行，保留分层词义。"""
    if not value:
        return ""
    lines = []
    for line in value.replace("\\r\\n", "\n").replace("\\n", "\n").splitlines():
        line = line.strip()
        if not line or NOISE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def parse_exchange(value: str) -> list[str]:
    """CSV 版本的 exchange 形如 p:did/d:done/i:doing/3:does。"""
    forms: list[str] = []
    for chunk in (value or "").split("/"):
        if ":" in chunk:
            _, _, item = chunk.partition(":")
            item = item.strip()
            if item and re.fullmatch(r"[A-Za-z][A-Za-z' -]*", item):
                forms.append(item)
    return forms


def normalise_pos(value: str) -> str:
    if not value:
        return ""
    parts = [p.strip() for p in re.split(r"[/,;]", value) if p.strip()]
    return "/".join(p for p in parts if p in POS_KEEP)[:24]


def connect(out: Path) -> sqlite3.Connection:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    db = sqlite3.connect(out)
    db.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE words(
            word TEXT PRIMARY KEY, phonetic TEXT, translation TEXT,
            pos TEXT, tag TEXT, forms TEXT, collins INTEGER, oxford INTEGER, frq INTEGER);
        CREATE TABLE forms(form TEXT PRIMARY KEY, word TEXT);
    """)
    return db


def write_rows(db: sqlite3.Connection, rows, form_rows: dict[str, str], stats: dict) -> None:
    for row in rows:
        word = str(row["word"]).strip().lower()
        if not word or len(word) > 40 or not re.fullmatch(r"[A-Za-z][A-Za-z' -]*", word):
            continue
        forms = [value for value in row["forms"] if value]
        if not row["translation"] and not forms:
            continue
        db.execute("INSERT OR REPLACE INTO words VALUES(?,?,?,?,?,?,?,?,?)", (
            word, row["phonetic"], row["translation"], row["pos"], "", " ".join(forms),
            0, 0, 0))
        stats["words"] += 1
        for form in forms:
            key = str(form).strip().lower()
            if key and key != word:
                form_rows.setdefault(key, word)


def shard_row(entry: list) -> dict:
    """把分片条目转成数据库行，并取出词形。"""
    exchange = entry[3] if len(entry) > 3 and isinstance(entry[3], dict) else {}
    return {"word": str(entry[0] or ""),
            "phonetic": str(entry[1] or "").strip(),
            "translation": clean_translation(str(entry[2] or "")),
            "pos": "",
            "forms": [str(value) for key, value in exchange.items()
                      if key in EXCHANGE_KEYS and value]}


def build_from_shards(directory: Path, out: Path, quiet: bool = False) -> dict:
    manifest = directory / "manifest.json"
    if not manifest.exists():
        raise SystemExit(f"找不到词典清单：{manifest}")
    info = json.loads(manifest.read_text(encoding="utf-8"))
    shards = info.get("shards") or [path.stem for path in sorted(directory.glob("*.js"))]
    db = connect(out)
    form_rows: dict[str, str] = {}
    stats = {"words": 0, "shards": 0}
    started = time.time()
    for name in shards:
        path = directory / f"{name}.js"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        marker = text.find("window.DICT_SHARDS[")
        if marker < 0:
            continue
        _, _, payload = text[marker:].partition("=")
        try:
            data = json.loads(payload.rstrip().rstrip(";"))
        except json.JSONDecodeError as error:
            print(f"  跳过 {name}.js：{error}", file=sys.stderr)
            continue
        write_rows(db, (shard_row(entry) for entry in (data.get("entries") or {}).values()),
                   form_rows, stats)
        for key, targets in (data.get("aliases") or {}).items():
            key = str(key).strip().lower()
            if key and isinstance(targets, list) and targets:
                form_rows.setdefault(key, str(targets[0]).lower())
        stats["shards"] += 1
        if not quiet:
            print(f"  {name}: 累计 {stats['words']} 个词条")
    db.executemany("INSERT OR REPLACE INTO forms VALUES(?,?)", form_rows.items())
    db.commit()
    db.execute("VACUUM")
    db.close()
    stats.update({"forms": len(form_rows), "seconds": round(time.time() - started, 1),
                  "source": f"data/dictionary（{info.get('name', 'ECDICT')}，"
                            f"{info.get('entries', '?')} 条，{info.get('license', '')}）"})
    return stats


def build_from_csv(csv_path: Path, out: Path) -> dict:
    db = connect(out)
    form_rows: dict[str, str] = {}
    stats = {"words": 0, "shards": 0, "forms": 0, "source": csv_path.name}
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        def rows():
            for row in csv.DictReader(handle):
                if not (row.get("word") or "").strip():
                    continue
                yield {"word": row["word"], "phonetic": (row.get("phonetic") or "").strip(),
                       "translation": clean_translation(row.get("translation") or ""),
                       "pos": normalise_pos(row.get("pos") or ""),
                       "forms": parse_exchange(row.get("exchange") or "")}
        write_rows(db, rows(), form_rows, stats)
    db.executemany("INSERT OR REPLACE INTO forms VALUES(?,?)", form_rows.items())
    db.commit()
    db.execute("VACUUM")
    db.close()
    stats["forms"] = len(form_rows)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", nargs="?", type=Path, help="ECDICT 的 ecdict.csv")
    parser.add_argument("--shards", type=Path, default=DEFAULT_SHARDS,
                        help="词典分片目录（默认 data/dictionary）")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--quiet", action="store_true", help="不逐个分片打印进度")
    args = parser.parse_args()
    if args.csv_path:
        if not args.csv_path.exists():
            print(f"找不到 CSV：{args.csv_path}", file=sys.stderr)
            return 1
        stats = build_from_csv(args.csv_path, args.out)
    else:
        if not args.shards.exists():
            print(f"找不到分片目录：{args.shards}；请用 --shards 指定，或提供 ecdict.csv",
                  file=sys.stderr)
            return 1
        stats = build_from_shards(args.shards, args.out, quiet=args.quiet)
    size = args.out.stat().st_size / 1048576
    print(f"写入 {stats['words']} 个词条、{stats['forms']} 条词形索引 -> {args.out}（{size:.1f} MB）"
          + (f"，耗时 {stats['seconds']}s" if "seconds" in stats else ""))
    print(f"来源：{stats['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
