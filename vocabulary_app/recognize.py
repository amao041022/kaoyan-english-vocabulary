"""离线试卷识别：把上传的 PDF／照片变成“词—原句—位置—圈画证据”的结构化结果。

只使用标准库 + numpy/Pillow；文字识别走内置的 macOS Vision 引擎，
没有该引擎时回退到 Tesseract。全流程不联网。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import ink

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "vocabulary_app" / "engine" / "vision_engine"
WORK = ROOT / "data" / "uploads"
BANK = ROOT / "data" / "exam_bank"

WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'\u2019-]*$")
LETTER_RE = re.compile(r"[A-Za-z]")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
TEXT_RE = re.compile(r"\bText\s*([1-4])\b", re.I)

# 功能词：圈画时往往跟着被圈的实词一起出现，单独出现不算生词候选
STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "and",
    "or", "but", "if", "so", "than", "that", "this", "these", "those", "it", "its", "he",
    "she", "they", "them", "their", "his", "her", "we", "our", "you", "your", "i", "me",
    "my", "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "has",
    "have", "had", "will", "would", "can", "could", "may", "might", "must", "shall",
    "should", "not", "no", "there", "here", "when", "while", "which", "who", "whom",
    "what", "how", "why", "all", "any", "both", "each", "more", "most", "some", "such",
    "only", "also", "too", "very", "up", "out", "off", "into", "over", "about", "after",
    "before", "between", "during", "without", "within", "because", "though", "although",
    "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't", "can't",
    "couldn't", "won't", "wouldn't", "shouldn't", "it's", "that's", "there's", "i'm",
}

SECTION_NAMES = {"cloze": "完形填空", **{f"text{i}": f"阅读 Text {i}" for i in range(1, 5)},
                 "new_type": "新题型", "translation": "翻译",
                 "writing_a": "小作文", "writing_b": "大作文"}


class EngineMissing(RuntimeError):
    pass


# ---------------------------------------------------------------- 文字识别

def engine_available() -> bool:
    if sys.platform != "darwin" or not ENGINE.exists():
        return False
    try:
        subprocess.run([str(ENGINE), "probe"], capture_output=True, timeout=20, check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def rotate_image(path: Path, degrees: int) -> Path:
    """把横放的照片转正；用系统 sips，不依赖第三方库。"""
    if not shutil.which("sips"):
        raise RuntimeError("本机没有 sips，无法自动转正；请在系统预览里旋转后再上传")
    target = path.with_name(f"{path.stem}-rot{degrees}{path.suffix}")
    subprocess.run(["sips", "-r", str(degrees), str(path), "--out", str(target)],
                   capture_output=True, timeout=180, check=True)
    if not target.exists():
        raise RuntimeError("图片旋转失败")
    return target


def _unused_looks_rotated(raw: dict) -> bool:
    """判断整页是否需要转 90 度：文字块的长轴与页面长轴不一致说明照片是横放的。"""
    widths, heights = [], []
    for page in raw.get("pages", []):
        xs0 = [line["x"] for line in page["lines"]]
        xs1 = [line["x"] + line["w"] for line in page["lines"]]
        ys0 = [1 - line["y"] - line["h"] for line in page["lines"]]
        ys1 = [1 - line["y"] for line in page["lines"]]
        if not xs0:
            continue
        widths.append(max(xs1) - min(xs0))
        heights.append(max(ys1) - min(ys0))
    if not widths:
        return False
    text_wide = sum(widths) / len(widths) > sum(heights) / len(heights) * 1.35
    page_tall = raw["pages"][0]["height"] >= raw["pages"][0]["width"]
    return (text_wide and page_tall) or (not text_wide and not page_tall and
                                         sum(heights) / len(heights) > sum(widths) / len(widths) * 1.35)


def _confidence(raw: dict) -> float:
    values = [line.get("confidence", 1.0) for page in raw.get("pages", []) for line in page["lines"]]
    return sum(values) / len(values) if values else 0.0


def orientation_score(raw: dict) -> float:
    """判断这一遍识别的方向对不对：接近 1 表示文字框横长（正常横排），
    接近 0 表示文字框竖长（照片转过了 90°）。"""
    horizontal = vertical = 0
    for page in raw.get("pages", []):
        for line in page["lines"]:
            if len(line["text"].strip()) < 4:
                continue
            width = line["w"] * page["width"]
            height = line["h"] * page["height"]
            if width >= height * 1.2:
                horizontal += 1
            elif height >= width * 1.2:
                vertical += 1
    total = horizontal + vertical
    if total < 3:
        return 0.5
    return horizontal / total


def ocr(path: Path, work_dir: Path, max_edge: int = 2400, language: str = "en-US",
        first: int = 1, last: int = 10_000, rotate: int = 0) -> dict:
    """识别 PDF／图片，返回引擎结果，并在 work_dir 写出降采样页图与墨迹图。

    照片方向不对时文字识别仍会出结果，但文字框会竖起来、坐标全错。
    这里按文字框形状自动判断方向（rotate=0），也可以强制指定 90/180/270。
    """
    if not engine_available():
        return _ocr_tesseract(path, work_dir, max_edge, first, last)

    def run(source: Path, directory: Path) -> dict:
        command = [str(ENGINE), "ocr", str(source), "--work-dir", str(directory),
                   "--max-edge", str(max_edge), "--lang", language,
                   "--first", str(first), "--last", str(last)]
        result = subprocess.run(command, capture_output=True, timeout=900)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "识别引擎失败")
        return json.loads(result.stdout.decode("utf-8"))

    def adopt(trial: dict, trial_dir: Path, degrees: int) -> dict:
        shutil.rmtree(work_dir, ignore_errors=True)
        trial_dir.rename(work_dir)
        for page in trial.get("pages", []):            # 目录改名后修正内部路径
            for key in ("image", "mask", "stroke"):
                if page.get(key):
                    page[key] = str(work_dir / Path(page[key]).name)
        trial["rotated"] = degrees
        return trial

    raw = run(path, work_dir)
    if path.suffix.lower() == ".pdf":
        return raw
    if rotate:
        rotated = rotate_image(path, rotate)
        trial_dir = work_dir.parent / (work_dir.name + f"-r{rotate}")
        shutil.rmtree(trial_dir, ignore_errors=True)
        trial = run(rotated, trial_dir)
        result = adopt(trial, trial_dir, rotate)
        rotated.unlink(missing_ok=True)
        return result
    if orientation_score(raw) < 0.75:
        for degrees in (90, -90):
            trial_dir = work_dir.parent / (work_dir.name + f"-r{degrees}")
            shutil.rmtree(trial_dir, ignore_errors=True)
            try:
                rotated = rotate_image(path, degrees)
                trial = run(rotated, trial_dir)
            except (OSError, subprocess.SubprocessError, RuntimeError):
                shutil.rmtree(trial_dir, ignore_errors=True)
                continue
            if orientation_score(trial) > orientation_score(raw):
                result = adopt(trial, trial_dir, degrees)
                rotated.unlink(missing_ok=True)
                return result
            shutil.rmtree(trial_dir, ignore_errors=True)
            rotated.unlink(missing_ok=True)
    return raw


def _ocr_tesseract(path: Path, work_dir: Path, max_edge: int, first: int, last: int) -> dict:
    """非 macOS 或缺少引擎时的回退：Tesseract TSV 同样给出词级框。"""
    if not shutil.which("tesseract"):
        raise EngineMissing("没有可用的文字识别引擎：本机缺少 macOS Vision，也未安装 Tesseract。")
    work_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    from PIL import Image
    sources: list[tuple[int, Path]] = []
    if path.suffix.lower() == "pdf":
        rendered = work_dir / "render"
        rendered.mkdir(exist_ok=True)
        engine_ok = ENGINE.exists() and sys.platform == "darwin"
        if engine_ok:
            subprocess.run([str(ENGINE), "render", str(path), "--out", str(rendered),
                            "--dpi", "200", "--first", str(first), "--last", str(last)],
                           capture_output=True, timeout=600, check=True)
            sources = [(int(p.stem.split("-")[-1]), p) for p in sorted(rendered.glob("page-*.png"))]
        else:
            raise EngineMissing("PDF 渲染需要内置引擎；请直接上传图片，或在 macOS 上运行。")
    else:
        sources = [(1, path)]
    for number, source in sources:
        if number < first or number > last:
            continue
        image = Image.open(source).convert("L")
        if max(image.size) > max_edge:
            ratio = max_edge / max(image.size)
            image = image.resize((int(image.width * ratio), int(image.height * ratio)), Image.LANCZOS)
        image_path = work_dir / f"page-{number:03d}.jpg"
        image.convert("RGB").save(image_path, quality=82)
        mask_path = work_dir / f"page-{number:03d}-ink.png"
        image.save(mask_path)
        tsv = subprocess.run(["tesseract", str(mask_path), "stdout", "-l", "eng", "--psm", "6", "tsv"],
                             capture_output=True, timeout=300, check=True).stdout.decode("utf-8", "replace")
        lines: dict[tuple, dict] = {}
        for row in tsv.splitlines()[1:]:
            parts = row.split("\t")
            if len(parts) < 12 or parts[0] != "5":
                continue
            text = parts[11].strip()
            if not text:
                continue
            left, top, width, height = (int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9]))
            key = (parts[2], parts[3], parts[4])
            entry = lines.setdefault(key, {"text": "", "confidence": float(parts[10]) / 100,
                                           "left": left, "top": top,
                                           "right": left + width, "bottom": top + height,
                                           "words": []})
            entry["text"] = (entry["text"] + " " + text).strip()
            entry["left"] = min(entry["left"], left)
            entry["top"] = min(entry["top"], top)
            entry["right"] = max(entry["right"], left + width)
            entry["bottom"] = max(entry["bottom"], top + height)
            entry["words"].append({"text": text, "left": left, "top": top,
                                   "right": left + width, "bottom": top + height})
        width, height = image.size
        pages.append({"page": number, "width": width, "height": height,
                      "image": str(image_path), "mask": str(mask_path),
                      "lines": _tsv_lines(lines, width, height)})
    return {"engine": "tesseract", "pages": pages}


def _tsv_lines(lines: dict, width: int, height: int) -> list[dict]:
    output = []
    for entry in lines.values():
        words = [{"text": w["text"],
                  "x": w["left"] / width, "y": w["top"] / height,
                  "w": (w["right"] - w["left"]) / width, "h": (w["bottom"] - w["top"]) / height,
                  "confidence": entry["confidence"]}
                 for w in entry["words"]]
        output.append({"text": entry["text"], "confidence": entry["confidence"],
                       "x": entry["left"] / width, "y": entry["top"] / height,
                       "w": (entry["right"] - entry["left"]) / width,
                       "h": (entry["bottom"] - entry["top"]) / height,
                       "alternatives": [], "words": words})
    return output


# ---------------------------------------------------------------- 版面重建

def line_boxes(lines: list[dict], width: int, height: int) -> list[dict]:
    """把 Vision 的归一化框（原点左下）换成左上原点的像素框，并按阅读顺序排序。"""
    boxes = []
    for line in lines:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        x0 = line["x"] * width
        x1 = (line["x"] + line["w"]) * width
        y0 = (1 - line["y"] - line["h"]) * height
        y1 = (1 - line["y"]) * height
        boxes.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                      "confidence": line.get("confidence", 1.0),
                      "alternatives": line.get("alternatives", []),
                      "blue": line.get("blueRatio", 0.0), "red": line.get("redRatio", 0.0)})
    boxes.sort(key=lambda item: (round(item["y0"] / 12), item["x0"]))
    return boxes


def word_spans(line: dict, page: ink.PageInk) -> list[tuple[float, float]]:
    """在行框内按墨迹空隙切出每个单词的真实左右边界。

    Vision 只给行框，按字符数平均分配宽度会累积误差（长短字母、连字符），
    所以这里直接用墨迹的纵向投影找词间空格，得到和原图对齐的词框。
    """
    y0 = max(0, int(line["y0"]) - 3)
    y1 = min(page.height, int(math.ceil(line["y1"])) + 4)
    x0 = max(0, int(line["x0"]) - 2)
    x1 = min(page.width, int(math.ceil(line["x1"])) + 3)
    if y1 <= y0 or x1 <= x0:
        return []
    band = page.dark[y0:y1, x0:x1] | page.colored[y0:y1, x0:x1]
    columns = band.sum(axis=0)
    if not columns.any():
        return []
    limit = max(1.0, columns.max() * 0.06)
    inked = columns > limit
    runs: list[tuple[int, int]] = []
    start = None
    for position, value in enumerate(inked):
        if value and start is None:
            start = position
        elif not value and start is not None:
            runs.append((start, position))
            start = None
    if start is not None:
        runs.append((start, len(inked)))
    if not runs:
        return []
    widths = sorted(end - begin for begin, end in runs)
    median = widths[len(widths) // 2] or 1
    gap_limit = max(3.0, median * 0.55)
    spans: list[tuple[float, float]] = []
    current_start, current_end = runs[0]
    for begin, end in runs[1:]:
        if begin - current_end > gap_limit:
            spans.append((current_start + x0, current_end + x0))
            current_start = begin
        current_end = end
    spans.append((current_start + x0, current_end + x0))
    return spans


def tokenize(line: dict, page: ink.PageInk | None = None) -> list[dict]:
    """把一行切成词：边界优先用墨迹空格，取不到时退回按字符宽度估算。"""
    text = line["text"]
    pieces = [(match.group(0), match.start(), match.end())
              for match in re.finditer(r"\S+", text)]
    if not pieces:
        return []
    spans = word_spans(line, page) if page is not None else []
    if len(spans) != len(pieces):
        # 墨迹分词与识别文本不一致（连字符、脚注、识别误差）时退回估算
        weights = [max(1, len(LETTER_RE.findall(piece))) for piece, _, _ in pieces]
        total = sum(weights)
        span = line["x1"] - line["x0"]
        cursor = line["x0"]
        spans = []
        for weight in weights:
            width = span * weight / total
            spans.append((cursor, cursor + width))
            cursor += width
    tokens = []
    for (piece, _, _), (left, right) in zip(pieces, spans):
        tokens.append({"raw": piece,
                       "text": piece.strip(".,;:!?()[]{}\"“”‘’…—–-").replace("\u2019", "'"),
                       "x0": left, "x1": right,
                       "y0": line["y0"], "y1": line["y1"],
                       "line": line})
    return tokens


def paragraphs(lines: list[dict]) -> list[list[dict]]:
    """按行距聚类成段；段落是定位“第几段”的依据之一。"""
    if not lines:
        return []
    heights = sorted(line["y1"] - line["y0"] for line in lines)
    median = heights[len(heights) // 2] or 1.0
    groups: list[list[dict]] = [[lines[0]]]
    for previous, current in zip(lines, lines[1:]):
        if current["y0"] - previous["y1"] > median * 0.85 or current["x0"] - lines[0]["x0"] > median * 2.2:
            groups.append([current])
        else:
            groups[-1].append(current)
    return groups


def sentence_text(lines: list[dict]) -> str:
    return re.sub(r"\s+", " ", " ".join(line["text"] for line in lines)).strip()


# ---------------------------------------------------------------- 圈画判定

def marked_words(page: ink.PageInk, tokens: list[dict], lines: list[dict] | None = None,
                 sensitivity: str = "standard") -> list[dict]:
    """先用笔迹形状找出全部圈画，再判断哪些词落在笔迹范围内。

    印刷文字框用于把印刷体从墨迹里排除；同一个圈常横跨两个词，两个词都会命中，
    这是刻意的——工作台里保留需要的那一个即可。
    """
    line_boxes = [ink.Box(line["x0"], line["y0"], line["x1"], line["y1"]) for line in (lines or [])]
    marks = ink.detect_marks(page, line_boxes, sensitivity)
    width, height = page.width, page.height
    results: list[dict] = []
    for token in tokens:
        text = token["text"]
        if not WORD_RE.match(text) or len(text) < 2:
            continue
        box = ink.Box(token["x0"], token["y0"], token["x1"], token["y1"])
        line = token["line"]
        related = ink.marks_for_box(marks, box, ink.Box(line["x0"], line["y0"], line["x1"], line["y1"]))
        kind, score, detail = ink.best_kind(related)
        if not kind:
            continue
        results.append({"text": text, "kind": kind, "score": score,
                        "colored": detail.get("colored_pixels", 0) > 60,
                        "evidence": detail,
                        # 功能词只是跟着被圈到的实词一起进了笔迹范围，默认不选
                        "auxiliary": len(text) <= 5 and text.casefold() in STOPWORDS,
                        "pixel_box": [box.x0, box.y0, box.x1, box.y1],
                        "box": {"x0": round(box.x0 / width, 5), "y0": round(box.y0 / height, 5),
                                "x1": round(box.x1 / width, 5), "y1": round(box.y1 / height, 5)},
                        "sentence": token["line"]["text"]})
    results.sort(key=lambda item: (item["box"]["y0"], -item["score"]))
    flag_ambiguous(results, marks)
    return results


def flag_ambiguous(results: list[dict], marks: list[ink.Mark], ratio: float = 1.3) -> None:
    """一个笔迹覆盖了多个词时，不猜用户想要哪个。

    - 只命中一个词：正常候选，默认勾选。
    - 命中多个词且其中有两个以上实词：全部标为待确认，默认不勾选。
    - 命中多个词但只有一个是实词：勾选它，其余（功能词）标为待确认。
    """
    def coverage(item: dict, mark: ink.Mark) -> float:
        width = item["pixel_box"][2] - item["pixel_box"][0]
        overlap = min(item["pixel_box"][2], mark.box.x1) - max(item["pixel_box"][0], mark.box.x0)
        return overlap / max(1.0, width)

    for mark in marks:
        touched = [item for item in results
                   if item["evidence"].get("kind") == mark.kind and _mark_match(item, mark)
                   and coverage(item, mark) >= 0.5]
        if len(touched) < 2:
            continue
        touched.sort(key=lambda item: coverage(item, mark), reverse=True)
        content = [item for item in touched if not item.get("auxiliary")]
        if len(content) >= 2:
            # 一个圈盖住多个实词（常见于圈短语），或者多个碎笔迹，一律交人确认
            for item in touched:
                item["ambiguous"] = True
        elif len(content) == 1:
            chosen = content[0]
            chosen["best_covered"] = True
            for item in touched:
                if item is not chosen:
                    item["ambiguous"] = True
        else:
            touched[0]["best_covered"] = True
            for item in touched[1:]:
                item["ambiguous"] = True


def _mark_match(item: dict, mark: ink.Mark) -> bool:
    x0, y0, x1, y1 = item["pixel_box"]
    return not (x1 < mark.box.x0 or mark.box.x1 < x0 or y1 < mark.box.y0 or mark.box.y1 < y0)


# ---------------------------------------------------------------- 题库比对

_BANK_CACHE: dict[int, dict] = {}


def _paper(year: int) -> dict | None:
    if year not in _BANK_CACHE:
        path = BANK / f"{year}.json"
        _BANK_CACHE[year] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _BANK_CACHE[year] or None


def _normalise(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"__\d+__", " ", text)
    text = re.sub(r"[^a-z0-9' ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()      # 标点换成空格后要压掉重复空格


def _similarity(needle: str, haystack: str) -> float:
    """短句（常只有三五个词）用整体相似度会被长原段稀释，这里补一个词序判据。"""
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 0.99
    # 反过来包含只在长度接近时才算命中：否则 "with" 这种选项会命中任何句子
    if haystack in needle and len(haystack) >= max(12, len(needle) * 0.5):
        return 0.95
    ratio = difflib.SequenceMatcher(None, needle, haystack).ratio()
    words = needle.split()
    if len(words) <= 8:
        positions = []
        for word in words:
            found = haystack.find(word)
            if found < 0:
                positions = []
                break
            positions.append(found)
        if positions and all(b >= a for a, b in zip(positions, positions[1:])):
            span = (positions[-1] + len(words[-1])) - positions[0]
            coverage = sum(len(word) for word in words) / max(1, span)
            ratio = max(ratio, 0.68 + 0.32 * min(1.0, coverage))
    return ratio


def guess_context(sentence: str, year: int | None, section: str | None = None,
                  threshold: float = 0.62) -> dict | None:
    """在本地真题库里找回原句与位置；低于阈值不硬套，宁可留空。"""
    papers = [_paper(year)] if year else [_paper(y) for y in range(2025, 2005, -1)]
    needle = _normalise(sentence)
    if len(needle) < 8:
        return None
    best: tuple[float, dict] | None = None
    for paper in papers:
        if not paper:
            continue
        for record in paper["records"]:
            if section and record["section"] != section:
                continue
            # 只认正文与待选段落：题干、选项、作答说明太短，容易误命中
            if record["kind"] not in ("passage", "paragraph_option"):
                continue
            haystack = _normalise(record["text"])
            if not haystack:
                continue
            score = _similarity(needle, haystack)
            if score >= threshold and (best is None or score > best[0]):
                best = (score, {"year": paper["year"], "record_id": record["id"],
                                "section": record["section"],
                                "section_title": f"{paper['year']} 英语（一）{SECTION_NAMES.get(record['section'], record['section'])}",
                                "location": record["location"], "kind": record["kind"],
                                "text": record["text"], "anchor": record["anchor"],
                                "pdf_pages": record.get("pdf_pages", []),
                                "score": round(score, 3)})
    return best[1] if best else None


def detect_year(text: str) -> int | None:
    for match in YEAR_RE.finditer(text):
        year = int(match.group(0))
        if 2006 <= year <= 2025:
            return year
    return None


def detect_section(text: str) -> str | None:
    match = TEXT_RE.search(text)
    if match:
        return f"text{match.group(1)}"
    if re.search(r"Use of English|完形填空", text, re.I):
        return "cloze"
    return None


def context_sentence(record: dict, word: str) -> str:
    """从题库原段里切出包含该词的整句，保持原文连续。"""
    text = record["text"]
    pattern = re.compile(r"(?<![A-Za-z])" + re.escape(word) + r"[a-z]{0,3}(?![A-Za-z])", re.I)
    match = pattern.search(text)
    if not match:
        return text
    start = 0
    for boundary in re.finditer(r"[.!?][\"')\]]?\s", text[:match.start()]):
        start = boundary.end()
    end = len(text)
    tail = re.search(r"[.!?][\"')\]]?(\s|$)", text[match.end():])
    if tail:
        end = match.end() + tail.end()
    return text[start:end].strip()


# ---------------------------------------------------------------- 主流程

def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_phrase(value: str) -> str:
    return value.strip().strip(".,;:!?()[]{}\"“”‘’…—–-").replace("\u2019", "'")


def split_sentences(text: str) -> list[str]:
    """保守切句：缩写和小数不切开。"""
    abbreviations = {"mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "vs.", "etc.", "e.g.",
                     "i.e.", "jr.", "sr.", "inc.", "co.", "ltd.", "no.", "fig.", "u.s."}
    parts: list[str] = []
    start = 0
    for match in re.finditer(r"[.!?]+[\"')\]]*(?=\s+|$)", text):
        prefix = text[:match.start() + 1]
        token = prefix.split()[-1].lower() if prefix.split() else ""
        if text[match.start()] == "." and token in abbreviations:
            continue
        chunk = text[start:match.end()].strip()
        if chunk:
            parts.append(chunk)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts or ([text.strip()] if text.strip() else [])


def candidates_from_text(text: str, name: str, year: int | None = None,
                         section: str | None = None, limit: int = 400,
                         category: str = "", link: str = "", location: str = "") -> dict:
    """从粘贴或截图识别出的文字生成候选词。

    适用于任何阅读场景：外刊文章、书页、真题段落、练习册句子或纯词表。
    没有圈画痕迹时“候选”只代表“出现过”，最终由使用者勾选，
    不会被自动当成生词写入。
    """
    from . import dictionary, store

    blocks = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    blocks = [block for block in blocks if block]
    sentences = split_sentences(" ".join(blocks)) if len(blocks) <= 2 else blocks

    seen: dict[str, dict] = {}
    for sentence in sentences:
        for raw in re.findall(r"[A-Za-z][A-Za-z'\u2019-]*", sentence):
            word = clean_phrase(raw)
            if len(word) < 2 or not WORD_RE.match(word) or word.casefold() in STOPWORDS:
                continue
            key = word.casefold()
            if key in seen:
                continue
            seen[key] = {"text": word, "kind": "listed", "score": 0.0, "colored": False,
                         "evidence": {}, "page": 0, "crop": "", "sentence": sentence}
            if len(seen) >= limit:
                break

    known = store.lemma_index()
    _BANK_CACHE.clear()
    prepared: list[dict] = []
    for key, item in seen.items():
        entry = known.get(key)
        item["known"] = bool(entry)
        item["known_lemma"] = entry["lemma"] if entry else ""
        item["meaning"] = entry["short_meaning"] if entry else ""
        # 原句一定要落到 example：题库命中的用真题原段切句，
        # 没有命中的（外刊、书、练习册）就用摘录到的这句话本身。
        item["example"] = item["sentence"]
        if not entry:
            item["dict"] = dictionary.lookup(item["text"])
        else:
            item["dict"] = None
            if entry.get("example"):
                item["example"] = entry["example"]
        # 带年份、或句子足够长时才去题库比对：外刊里的短句容易和真题某句
        # “看起来像”，宁可不去套，也不要给出错误的原文位置。
        resolved_year = year or detect_year(text)
        if resolved_year or len(item["sentence"]) >= 60:
            found = guess_context(item["sentence"], resolved_year, section)
            if found:
                item["context"] = found
                if not entry:
                    item["example"] = context_sentence(found, item["text"])
        prepared.append(item)

    return {
        "id": "paste",
        "source": name,
        "engine": "paste",
        "category": category,
        "link": link,
        "location": location,
        "resolution": {"year": year or detect_year(text), "section": section or detect_section(text)},
        "pages": [{"page": 0, "text": re.sub(r"\n+", "\n", text).strip(), "lines": len(blocks),
                   "words": len(seen), "candidates": len(prepared),
                   "image": "", "width": 0, "height": 0}],
        "candidates": prepared,
        "stats": {"pages": 1, "candidates": len(prepared),
                  "known": sum(1 for item in prepared if item["known"])},
    }


def extract(path: Path, source_name: str | None = None, year: int | None = None,
            section: str | None = None, pages: tuple[int, int] | None = None,
            progress=None) -> dict:
    """识别一份材料，返回可供工作台核对的结构化结果。"""
    path = Path(path)
    digest = file_digest(path)
    work_dir = WORK / digest[:16]
    work_dir.mkdir(parents=True, exist_ok=True)

    def note(message: str) -> None:
        if progress:
            progress(message)

    note("正在识别文字…")
    first, last = pages or (1, 10_000)
    raw = ocr(path, work_dir, first=first, last=last)

    page_results = []
    marks: list[dict] = []
    for entry in raw["pages"]:
        image_path = entry.get("image")
        mask_path = entry.get("mask")
        stroke_path = entry.get("stroke")
        if mask_path and Path(mask_path).exists():
            page_ink = ink.load_mask(mask_path, stroke_path,
                                     image_path if image_path and Path(image_path).exists() else None)
        elif image_path and Path(image_path).exists():
            page_ink = ink.load_image(image_path)
            mask_path = image_path
        else:
            continue
        if not image_path or not Path(image_path).exists():
            image_path = mask_path
        lines = line_boxes(entry["lines"], entry["width"], entry["height"])
        tokens = [token for line in lines for token in tokenize(line)]
        found = marked_words(page_ink, tokens, lines)
        text = "\n".join(line["text"] for line in lines)
        page_results.append({"page": entry["page"], "width": entry["width"], "height": entry["height"],
                             "image": image_path, "text": text,
                             "lines": len(lines), "words": len(tokens),
                             "candidates": len(found)})
        for index, item in enumerate(found, start=1):
            item["page"] = entry["page"]
            pixel_box = item.pop("pixel_box")
            try:
                thumbnail = ink.crop_bytes(image_path, ink.Box(*pixel_box))
                crop_name = f"crop-p{entry['page']:03d}-{index:02d}.jpg"
                (work_dir / crop_name).write_bytes(thumbnail)
                item["crop"] = crop_name
            except Exception:                      # 裁剪失败不影响词条本身
                item["crop"] = ""
            marks.append(item)

    full_text = "\n".join(page["text"] for page in page_results)
    resolution = {"year": year or detect_year(full_text),
                  "section": section or detect_section(full_text)}

    note("正在与本地真题库比对原句…")
    for item in marks:
        context = guess_context(item["sentence"], resolution["year"], resolution["section"])
        if context:
            item["context"] = context
            item["example"] = context_sentence(context, item["text"])
            if not resolution["year"]:
                resolution["year"] = context["year"]

    note("正在核对是否已在生词本中…")
    from . import dictionary, store
    known = store.lemma_index()
    for item in marks:
        entry = known.get(item["text"].casefold())
        item["known"] = bool(entry)
        item["known_lemma"] = entry["lemma"] if entry else ""
        item["meaning"] = entry["short_meaning"] if entry else ""
        if not entry:
            gloss = dictionary.lookup(item["text"])
            item["dict"] = gloss

    result = {
        "id": digest[:16],
        "sha256": digest,
        "source": source_name or path.name,
        "stored": str(path.relative_to(ROOT)) if str(path).startswith(str(ROOT)) else str(path),
        "engine": raw.get("engine"),
        "resolution": resolution,
        "pages": page_results,
        "candidates": marks,
        "stats": {"pages": len(page_results), "candidates": len(marks),
                  "known": sum(1 for item in marks if item["known"])},
    }
    out = WORK / f"{result['id']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
