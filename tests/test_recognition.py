"""识别与查词的最小验证。

用本地整卷 PDF 渲染一页真题，在渲染图上按识别出的文字框位置真实地画圈、画线，
再走完整识别流程，检查：
  1. 被圈、被划的词能被找出来；
  2. 没有标记的正文词不会被当成生词；
  3. 找出的词能回到本地真题库补上原句与位置。

依赖 Pillow 与内置识别引擎；缺少任一条件时跳过，不算失败。
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PIL import Image, ImageDraw
    HAVE_PIL = True
except ImportError:                                   # pragma: no cover
    HAVE_PIL = False

from vocabulary_app import ink, recognize  # noqa: E402

PDF = ROOT / "images" / "exam_bank" / "2017.pdf"
CACHE = ROOT / "data" / "uploads" / "_test"


def render_page(page: int = 4, dpi: int = 200) -> Path | None:
    if not PDF.exists() or not recognize.engine_available():
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"base-{page}.jpg"
    if target.exists():
        return target
    render_dir = CACHE / "render"
    subprocess.run([str(recognize.ENGINE), "render", str(PDF), "--out", str(render_dir),
                    "--dpi", str(dpi), "--first", str(page), "--last", str(page)],
                   capture_output=True, check=True, timeout=300)
    source = render_dir / f"page-{page:03d}.png"
    if not source.exists():
        return None
    Image.open(source).convert("RGB").save(target, quality=92)
    return target


def draw_marks(base: Path, words: list[str]) -> Path | None:
    """用识别结果定位文字，在真实位置画手写风格标记。"""
    work = CACHE / "probe"
    raw = recognize.ocr(base, work)
    page = raw["pages"][0]
    lines = recognize.line_boxes(page["lines"], page["width"], page["height"])
    image = Image.open(base).convert("RGB")
    draw = ImageDraw.Draw(image)
    found = []
    for line in lines:
        for token in recognize.tokenize(line):
            cleaned = token["text"]
            if cleaned.lower() not in {word.lower() for word in words}:
                continue
            box = ink.Box(token["x0"], token["y0"], token["x1"], token["y1"])
            pad_x, pad_y = box.width * 0.18, box.height * 0.5
            if cleaned.lower() == words[0].lower():
                for offset in range(4):
                    draw.ellipse([box.x0 - pad_x - offset, box.y0 - pad_y - offset,
                                  box.x1 + pad_x + offset, box.y1 + pad_y + offset],
                                 outline=(38, 62, 176))
            else:
                draw.line([box.x0 - pad_x, box.y1 + pad_y * 1.2,
                           box.x1 + pad_x, box.y1 + pad_y * 1.4], fill=(196, 48, 44), width=4)
            found.append(cleaned)
    if len(found) < len(words):
        return None
    marked = CACHE / "marked.jpg"
    image.save(marked, quality=92)
    return marked


@unittest.skipUnless(HAVE_PIL, "需要 Pillow")
class MarkedPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = render_page()
        if cls.base is None:
            raise unittest.SkipTest("缺少整卷 PDF 或识别引擎")
        cls.marked = draw_marks(cls.base, ["domestic", "tolerate"])
        if cls.marked is None:
            raise unittest.SkipTest("测试页上没有找到预期的词，跳过")

    def test_marks_are_found_and_matched(self):
        result = recognize.extract(self.marked, source_name="marked.jpg")
        words = {item["text"].lower(): item for item in result["candidates"]}
        self.assertIn("domestic", words, "圈出的词没有被识别")
        self.assertIn("tolerate", words, "划线的词没有被识别")
        self.assertEqual(words["domestic"]["kind"], "circle")
        self.assertEqual(words["tolerate"]["kind"], "underline")
        for word in ("domestic", "tolerate"):
            context = words[word].get("context")
            self.assertIsNotNone(context, f"{word} 没有匹配到真题位置")
            self.assertEqual(context["year"], 2017)
        # 2017 Text 1 第 1 段：原句必须来自本地题库，不能编造
        self.assertIn("domestic", words["domestic"]["example"].lower())

    def test_plain_page_has_no_candidates(self):
        """没有任何笔迹的页面不应产生候选词。"""
        result = recognize.extract(self.base, source_name="base.jpg")
        self.assertEqual(result["candidates"], [],
                         f"干净页面出现了 {len(result['candidates'])} 个候选词")


class DictionaryTest(unittest.TestCase):
    def test_lookup_reduces_forms(self):
        from vocabulary_app import dictionary
        if not dictionary.available():
            self.skipTest("未生成离线词典")
        self.assertEqual(dictionary.lookup("insisted")["word"], "insist")
        self.assertEqual(dictionary.lookup("monarchs")["word"], "monarch")
        self.assertTrue(dictionary.lookup("eligible")["senses"])


class BankMatchTest(unittest.TestCase):
    def test_context_uses_real_sentence(self):
        found = recognize.guess_context(
            "King Juan Carlos of Spain once insisted kings don't abdicate, they die in their sleep.",
            2015, "text1")
        self.assertIsNotNone(found)
        self.assertEqual(found["section"], "text1")
        sentence = recognize.context_sentence(found, "abdicate")
        self.assertIn("abdicate", sentence)
        self.assertTrue(sentence.endswith((".", "”", '"')) or len(sentence) > 40)

    def test_no_fabrication_when_missing(self):
        self.assertIsNone(recognize.guess_context("This sentence is not from any exam paper.", 2017))


if __name__ == "__main__":
    unittest.main(verbosity=2)
