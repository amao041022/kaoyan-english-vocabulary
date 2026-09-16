"""考研英语生词本 · 本机应用服务（纯标准库，离线运行）。

用法：
    python3 vocabulary_app/server.py            # 自动挑选端口并打开浏览器
    python3 vocabulary_app/server.py --port 8765 --no-browser

服务只监听 127.0.0.1，只读写本项目目录内的文件；
识别、查词、生成复习页全部在本机完成，不把材料上传到任何服务器。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import shutil
import socket
import subprocess
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vocabulary_app import dictionary, ink, personal_cards, recognize, runtime, store  # noqa: E402

WEBAPP = ROOT / "webapp"
OUTPUT = ROOT / "output"
UPLOADS = ROOT / "data" / "uploads"
INPUTS = UPLOADS / "inbox"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp", ".ico": "image/x-icon"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif"}
DOC_SUFFIXES = {".pdf", ".txt"}
MAX_UPLOAD = 40 * 1024 * 1024

# 运行中的任务进度，供前端轮询
TASKS: dict[str, dict] = {}
TASK_LOCK = threading.Lock()
_audio_lock = threading.Lock()


# ---------------------------------------------------------------- 通用工具

def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")


def safe_name(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)
    return name[:120] or "upload"


def unique_path(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 1000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}-{len(list(directory.iterdir()))}{suffix}"


def within(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def convert_heic(path: Path) -> Path:
    """iPhone 默认拍 HEIC；用系统 sips 转成 JPEG，失败则原样返回。"""
    if path.suffix.lower() not in {".heic", ".heif"} or not shutil.which("sips"):
        return path
    target = path.with_suffix(".jpg")
    try:
        subprocess.run(["sips", "-s", "format", "jpeg", str(path), "--out", str(target)],
                       capture_output=True, timeout=120, check=True)
        return target if target.exists() else path
    except (OSError, subprocess.SubprocessError):
        return path


def set_task(task_id: str, **changes) -> None:
    with TASK_LOCK:
        TASKS.setdefault(task_id, {"id": task_id, "state": "pending", "message": "", "progress": 0})
        TASKS[task_id].update(changes)


def get_task(task_id: str) -> dict | None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        return dict(task) if task else None


# ---------------------------------------------------------------- 查词

def lookup_word(word: str, year: int | None = None, section: str | None = None,
                limit: int = 24) -> dict:
    """两级查词：已录入生词给完整资料；没录入的只回到原文定位，不给释义。"""
    cleaned = word.strip()
    if not cleaned or len(cleaned) > 60:
        return {"word": cleaned, "level": "none", "message": "请输入一个单词或短语（60 个字符以内）。"}
    index = store.lemma_index()
    entry = index.get(cleaned.casefold())
    if entry is None and cleaned.endswith("'s"):
        entry = index.get(cleaned[:-2].casefold())
    locations = locate_in_bank(cleaned, entry, year, section, limit)
    if entry is not None:
        gloss = dictionary.lookup(entry.get("lemma") or cleaned)
        return {"word": cleaned, "level": "vocabulary", "entry": entry, "dictionary": gloss,
                "locations": locations,
                "message": f"已在生词本中（原形 {entry['lemma']}），共 {len(locations)} 处原文位置。"}
    # 不在生词本：先看题库里认不认识这个词形，认识也仍然只给定位
    dict_result = dictionary.lookup(cleaned)
    return {"word": cleaned, "level": "location", "dictionary": None,
            "dictionary_available": bool(dict_result),
            "locations": locations,
            "message": (f"未录入生词本：只显示原文位置（{len(locations)} 处），不提供释义。"
                        if locations else "未录入生词本，本地题库中也没有找到该词形。")}


def locate_in_bank(word: str, entry: dict | None, year: int | None, section: str | None,
                   limit: int = 24) -> list[dict]:
    forms = {word}
    if entry:
        forms |= {entry.get("lemma", ""), entry.get("form", ""), *entry.get("forms", [])}
    else:
        alias = store.lemma_index().get(word.casefold())
        if alias:
            forms |= {alias.get("lemma", ""), *alias.get("forms", [])}
    forms = {value for value in forms if value}
    pattern = re.compile(r"(?<![A-Za-z])(?:" +
                         "|".join(re.escape(value) for value in sorted(forms, key=len, reverse=True)) +
                         r")(?![A-Za-z])", re.I)

    years = [year] if year else list(range(2025, 2005, -1))
    hits: list[dict] = []
    for value in years:
        path = ROOT / "data" / "exam_bank" / f"{value}.json"
        if not path.exists():
            continue
        paper = json.loads(path.read_text(encoding="utf-8"))
        for record in paper["records"]:
            if section and record["section"] != section:
                continue
            if not pattern.search(record["text"]):
                continue
            hits.append({
                "year": paper["year"],
                "record_id": record["id"],
                "section": record["section"],
                "section_name": recognize.SECTION_NAMES.get(record["section"], record["section"]),
                "kind": record["kind"],
                "location": record["location"],
                "text": record["text"],
                "anchor": record["anchor"],
                "paper": f"exams/{paper['year']}.html",
                "pdf_pages": record.get("pdf_pages", []),
                "matched": list({match.group() for match in pattern.finditer(record["text"])}),
            })
            if len(hits) >= limit:
                return hits
    priority = {"passage": 0, "paragraph_option": 1, "question": 2, "option": 3, "writing": 4, "directions": 5}
    hits.sort(key=lambda item: (-item["year"], priority.get(item["kind"], 9)))
    return hits


# ---------------------------------------------------------------- 生词本写入

def audio_for(text: str) -> str:
    """为本机缺少的朗读文本生成美音音频（macOS say）；已有音频直接复用。"""
    import hashlib

    spoken = re.sub(r"\s+", " ", text).strip()
    if not spoken:
        return ""
    key = hashlib.sha256(spoken.encode("utf-8")).hexdigest()[:24]
    target = OUTPUT / "audio" / f"{key}.wav"
    if target.exists():
        return f"audio/{key}.wav"
    if sys.platform != "darwin" or not shutil.which("say"):
        return ""
    with _audio_lock:
        if target.exists():
            return f"audio/{key}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["say", "-v", "Samantha", "-o", str(target), "--data-format=LEI16@22050",
                            "--file-format=WAVE", spoken], capture_output=True, timeout=120, check=True)
        except (OSError, subprocess.SubprocessError):
            return ""
    return f"audio/{key}.wav" if target.exists() else ""


def save_entries(payload: dict) -> dict:
    """把工作台确认过的候选写成生词记录，并生成个人词库卡片。

    生词记录合并进词库生成复习页面；同一批词另外变成 PersonalCore 卡片，
    由 main.py 发布为 personal-cards.js，页面启动时并入浏览器里的个人词库。
    """
    candidates = payload.get("entries") or []
    if not candidates:
        raise ValueError("没有需要保存的词条")
    additions = store.load_additions()
    existing = {entry["lemma"].casefold() for entry in store.all_entries()}
    created, skipped, errors = [], [], []
    cards = []
    for item in candidates:
        try:
            if not item.get("lemma"):
                continue
            if item["lemma"].casefold() in existing:
                skipped.append(item["lemma"])
                continue
            entry = store.make_entry(item, additions["entries"])
            audio = audio_for(entry["example"])
            if audio:
                entry["audio"] = audio
            additions["entries"].append(entry)
            existing.add(entry["lemma"].casefold())
            created.append(entry["id"])
            source = item.get("source_image")
            if source and not any(image["filename"] == source for image in additions["source_images"]):
                path = INPUTS / source
                if path.exists():
                    additions["source_images"].append({
                        "filename": source,
                        "relative_path": f"data/uploads/inbox/{source}",
                        "sha256": recognize.file_digest(path),
                        "bytes": path.stat().st_size,
                    })
        except Exception as error:            # 单条失败不影响其他词
            errors.append(f"{item.get('lemma', '?')}：{error}")
    if created:
        store.save_additions(additions)
    # 个人词库卡片：释义必填（个人词库按词义去重），缺释义的词在下面报错
    if candidates:
        import time as _time
        cards, card_errors = personal_cards.cards_from_entries(candidates, int(_time.time() * 1000))
        for card in cards:
            additions.setdefault("personal_cards", [])
        if cards:
            additions = store.load_additions()
            store.add_personal_cards(cards)
        errors.extend(card_errors)
    return {"created": created, "skipped": skipped, "errors": errors,
            "cards": [card["id"] for card in cards],
            "total": len(store.all_entries())}


def rebuild_pages() -> dict:
    """合并新增生词并重新生成复习页面。用当前解释器运行生成脚本，避免 PATH 里的旧版本。"""
    interpreter = runtime.interpreter()
    version = subprocess.run([interpreter, "-c", "import sys;print(sys.version.split()[0])"],
                             capture_output=True, timeout=60).stdout.decode().strip()
    result = subprocess.run([interpreter, "-B", str(ROOT / "main.py")],
                            cwd=str(ROOT), capture_output=True, timeout=1800)
    if result.returncode != 0:
        detail = (result.stderr.decode("utf-8", "replace").strip()
                  or result.stdout.decode("utf-8", "replace").strip())
        raise RuntimeError(detail[-600:] or "生成失败")
    return {"ok": True, "summary": result.stdout.decode("utf-8", "replace")[-400:],
            "python": version}


def library_overview() -> dict:
    entries = store.all_entries()
    sections: dict[str, dict] = {}
    for entry in entries:
        key = entry.get("section_title") or entry.get("section_id") or "未分组"
        bucket = sections.setdefault(key, {"title": key, "count": 0, "words": []})
        bucket["count"] += 1
        if len(bucket["words"]) < 40:
            bucket["words"].append(entry.get("lemma") or entry.get("form"))
    main = store.load_main()
    additions = store.load_additions()
    # 旧记录没有 category 字段，按真题试卷归类，界面上的筛选才不会漏掉它们
    categories: dict[str, int] = {}
    for entry in entries:
        key = entry.get("category") or "exam"
        categories[key] = categories.get(key, 0) + 1
    return {
        "total": len(entries),
        "main": len(main.get("entries", [])),
        "additions": len(additions.get("entries", [])),
        "categories": {key: categories.get(key, 0) for key in store.CATEGORY_ORDER},
        "sections": sorted(sections.values(), key=lambda item: (-item["count"], item["title"])),
    }


def resolve_pending(words: list[str], limit: int = 6) -> list[dict]:
    """把“待整理”里的词解析成候选：补上在线来源链接、真题位置与离线释义。"""
    from vocabulary_app import dictionary as _dictionary
    known = store.lemma_index()
    output: list[dict] = []
    for word in words[:60]:
        entry = known.get(word.casefold())
        item: dict = {"text": word, "kind": "listed", "score": 0.0, "colored": False,
                      "evidence": {}, "page": 0, "crop": "",
                      "known": bool(entry), "known_lemma": entry["lemma"] if entry else "",
                      "meaning": entry["short_meaning"] if entry else "", "from_pending": True}
        locations = locate_in_bank(word, entry, None, None, limit)
        if locations:
            item["context"] = locations[0]
            item["example"] = locations[0]["text"]
        if not entry:
            item["dict"] = _dictionary.lookup(word)
        output.append(item)
    return output


def resolve_media(relative: str) -> Path | None:
    """只允许访问项目内已登记的图片与上传目录。"""
    relative = urllib.parse.unquote(relative).lstrip("/")
    for base in (ROOT / "images", ROOT / "data" / "uploads", ROOT / "output"):
        target = (base / relative).resolve()
        if within(base, target) and target.is_file():
            return target
    direct = (ROOT / relative).resolve()
    if within(ROOT / "images", direct) and direct.is_file():
        return direct
    return None


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "KaoyanVocab/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:      # 控制台保持清爽
        if self.path.startswith("/api/"):
            sys.stderr.write("  %s %s\n" % (self.command, self.path))

    # -- 响应助手 ---------------------------------------------------
    def send_bytes(self, body: bytes, content_type: str, status: int = 200,
                   cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, payload: object, status: int = 200) -> None:
        self.send_bytes(json_bytes(payload), "application/json; charset=utf-8", status)

    def fail(self, message: str, status: int = 400) -> None:
        self.send_json({"ok": False, "error": message}, status)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_UPLOAD:
            raise ValueError("请求内容过大")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"请求格式不是合法 JSON：{error}") from error

    # -- 路由 -------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if route.startswith("/api/"):
                return self.api_get(route, query)
            if route.startswith("/media/"):
                target = resolve_media(route[len("/media/"):])
                if not target:
                    return self.fail("找不到该文件", 404)
                mime = STATIC_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                return self.send_bytes(target.read_bytes(), mime, cache="public, max-age=3600")
            if route.startswith("/output/"):
                # 生成的复习页面、整卷、音频与浏览器脚本
                target = (OUTPUT / route[len("/output/"):]).resolve()
                if not within(OUTPUT, target) or not target.is_file():
                    return self.fail("找不到该文件", 404)
                mime = STATIC_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                return self.send_bytes(target.read_bytes(), mime)
            if route in ("/", "/index.html"):
                route = "/app.html"
            target = (WEBAPP / route.lstrip("/")).resolve()
            if not within(WEBAPP, target) or not target.is_file():
                return self.fail("页面不存在", 404)
            mime = STATIC_TYPES.get(target.suffix.lower()) or "application/octet-stream"
            return self.send_bytes(target.read_bytes(), mime)
        except BrokenPipeError:
            return
        except Exception as error:                        # noqa: BLE001
            traceback.print_exc()
            return self.fail(f"服务出错：{error}", 500)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/upload":
                return self.api_upload()
            if parsed.path == "/api/rebuild":
                try:
                    return self.send_json({"ok": True, **rebuild_pages()})
                except RuntimeError as error:
                    # 生成脚本没通过校验时把原因原样带回页面，不要只回 500
                    return self.send_json({"ok": False, "error": str(error)}, 400)
            return self.api_post(parsed.path, self.read_json())
        except BrokenPipeError:
            return
        except ValueError as error:
            return self.fail(str(error))
        except Exception as error:                        # noqa: BLE001
            traceback.print_exc()
            return self.fail(f"服务出错：{error}", 500)

    # -- API --------------------------------------------------------
    def api_get(self, route: str, query: dict) -> None:
        if route == "/api/status":
            return self.send_json({
                "ok": True,
                "dictionary_hint": "" if dictionary.available() else
                    "离线词典未生成：运行 python3 vocabulary_app/build_dict.py",
                "engine": "apple-vision" if recognize.engine_available() else
                          ("tesseract" if shutil.which("tesseract") else "none"),
                "dictionary": dictionary.available(),
                "dictionary_words": dictionary_count(),
                "library": library_overview(),
                "pending": store.load_pending().get("words", [])[:60],
                "extractions": sorted((path.stem for path in UPLOADS.glob("*.json")), reverse=True)[:40],
                "audio": (OUTPUT / "audio").exists(),
            })
        if route == "/api/lookup":
            word = (query.get("q") or [""])[0]
            year = query.get("year", [""])[0]
            section = query.get("section", [""])[0] or None
            return self.send_json({"ok": True, **lookup_word(
                word, int(year) if year.isdigit() else None, section)})
        if route == "/api/dictionary":
            word = (query.get("q") or [""])[0]
            return self.send_json({"ok": True, "word": word, "result": dictionary.lookup(word)})
        if route == "/api/vocabulary":
            main = store.load_main()
            additions = store.load_additions()
            return self.send_json({"ok": True, "entries": [*main.get("entries", []),
                                                            *additions.get("entries", [])]})
        if route == "/api/extraction":
            name = (query.get("id") or [""])[0]
            path = (UPLOADS / f"{safe_name(name)}.json").resolve()
            if not within(UPLOADS, path) or not path.exists():
                return self.fail("找不到识别结果", 404)
            return self.send_json({"ok": True, "result": json.loads(path.read_text(encoding="utf-8"))})
        if route == "/api/task":
            task = get_task(safe_name((query.get("id") or [""])[0]))
            return self.send_json({"ok": bool(task), "task": task})
        return self.fail("未知接口", 404)

    def api_post(self, route: str, payload: dict) -> None:
        if route == "/api/extract":
            return self.send_json({"ok": True, **self.start_extraction(payload)})
        if route == "/api/resolve_pending":
            words = [str(word).strip() for word in (payload.get("words") or []) if str(word).strip()]
            if not words:
                raise ValueError("没有需要解析的词")
            return self.send_json({"ok": True, "candidates": resolve_pending(words)})
        if route == "/api/prepare_text":
            text = (payload.get("text") or "").strip()
            if not text:
                raise ValueError("请先粘贴文字")
            if len(text) > 200_000:
                raise ValueError("粘贴内容过长，请分段处理")
            name = (payload.get("name") or "阅读材料").strip()[:80]
            result = recognize.candidates_from_text(
                text, name,
                int(payload["year"]) if payload.get("year") else None,
                payload.get("section") or None,
                category=(payload.get("category") or "").strip(),
                link=store.normalise_link(payload.get("link") or ""),
                location=(payload.get("location") or "").strip())
            return self.send_json({"ok": True, "result": result})
        if route == "/api/save":
            return self.send_json({"ok": True, **save_entries(payload)})
        if route == "/api/audio":
            text = (payload.get("text") or "").strip()
            if not text or len(text) > 600:
                return self.fail("朗读文本无效")
            return self.send_json({"ok": True, "url": audio_for(text)})
        if route == "/api/pending":
            return self.send_json({"ok": True, **store.add_pending(
                payload.get("word", ""), payload.get("locations"), payload.get("source", ""))})
        return self.fail("未知接口", 404)

    def start_extraction(self, payload: dict) -> dict:
        name = safe_name(payload.get("file") or "")
        path = (INPUTS / name).resolve()
        if not within(INPUTS, path) or not path.exists():
            raise ValueError("请先上传试卷图片或 PDF")
        year = payload.get("year")
        section = payload.get("section") or None
        task_id = recognize.file_digest(path)[:16]
        set_task(task_id, state="running", message="正在识别…", progress=5, file=name)

        def worker() -> None:
            try:
                result = recognize.extract(path, source_name=name,
                                           year=int(year) if year else None, section=section,
                                           progress=lambda message: set_task(task_id, message=message))
                set_task(task_id, state="done", message=f"识别完成：{result['stats']['candidates']} 个候选",
                         progress=100, extraction=result["id"])
            except Exception as error:                    # noqa: BLE001
                traceback.print_exc()
                set_task(task_id, state="error", message=str(error), progress=100)

        threading.Thread(target=worker, daemon=True).start()
        return {"task": get_task(task_id)}

    # -- 上传 -------------------------------------------------------
    def api_upload(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self.fail("没有收到文件内容")
        if length > MAX_UPLOAD:
            return self.fail("单个文件不能超过 40 MB；请压缩照片或分批上传")
        body = self.rfile.read(length)
        filename, payload = parse_multipart(body, self.headers.get("Content-Type", ""))
        if not filename or not payload:
            return self.fail("上传内容无效，请重新选择文件")
        name = safe_name(filename)
        suffix = Path(name).suffix.lower()
        if suffix not in IMAGE_SUFFIXES | DOC_SUFFIXES:
            return self.fail(f"暂不支持 {suffix or '该'} 格式；请上传 JPG/PNG/HEIC/PDF/TXT")
        target = unique_path(INPUTS, name)
        target.write_bytes(payload)
        stored = convert_heic(target)
        if stored != target:
            target.unlink(missing_ok=True)
        return self.send_json({"ok": True, "file": stored.name,
                               "bytes": stored.stat().st_size,
                               "preview": f"/media/inbox/{urllib.parse.quote(stored.name)}"})


def parse_multipart(body: bytes, content_type: str) -> tuple[str, bytes]:
    """极简 multipart/form-data 解析：只取第一个文件的文件名与内容。"""
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type)
    if not match:
        return "", b""
    boundary = (match.group(1) or match.group(2)).strip().encode("utf-8")
    delimiter = b"--" + boundary
    for part in body.split(delimiter):
        if b"filename=" not in part:
            continue
        head, _, content = part.partition(b"\r\n\r\n")
        if not content:
            continue
        name_match = re.search(rb'filename="([^"]*)"', head)
        if not name_match:
            continue
        return name_match.group(1).decode("utf-8", "replace"), content.rstrip(b"\r\n-")
    return "", b""


def dictionary_count() -> int:
    try:
        import sqlite3
        if not dictionary.DB.exists():
            return 0
        connection = sqlite3.connect(f"file:{dictionary.DB}?mode=ro", uri=True)
        count = connection.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        connection.close()
        return int(count)
    except Exception:                                     # noqa: BLE001
        return 0


def free_port(preferred: int) -> int:
    for port in [preferred, *range(preferred + 1, preferred + 20)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("找不到可用端口，请用 --port 指定其他端口")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    INPUTS.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    engine = "macOS Vision" if recognize.engine_available() else (
        "Tesseract" if shutil.which("tesseract") else "无（只能手动标记）")
    print("考研英语生词本 · 本机应用已启动")
    print(f"  地址：{url}")
    print(f"  识别引擎：{engine}　离线词典：{'已内置' if dictionary.available() else '未安装'}")
    print("  按 Control+C 结束服务。")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
