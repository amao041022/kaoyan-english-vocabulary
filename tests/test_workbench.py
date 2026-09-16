"""工作台写入与页面生成的端到端验证。

覆盖：保存确认过的词条 → main.py 合并生成页面 → 新词出现在生词本与学习资料里。
测试会临时替换 data/vocabulary_additions.json，结束后恢复原文件。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vocabulary_app import runtime, store  # noqa: E402

ADDITIONS = ROOT / "data" / "vocabulary_additions.json"
BACKUP = ROOT / "data" / "vocabulary_additions.json.test-backup"

ENTRY = {
    "id": "testunit-01",
    "section_id": "upload-testunit",
    "section_title": "测试材料｜端到端验证",
    "year": None,
    "source_group": "端到端测试材料",
    "photo": "",
    "lemma": "tolerate",
    "form": "tolerate",
    "ipa": "ˈtɒləreɪt",
    "pos": "vt.",
    "common": "vt. 容忍；容许",
    "meaning": "vt. 容忍（安检流程）",
    "short_meaning": "vt. 容忍（安检流程）",
    "location": "第 2 段",
    "example": "Americans are willing to tolerate time-consuming security procedures in return for increased safety.",
    "translation": "美国人愿意为了更高的安全性而容忍耗时的安检流程。",
    "note": "端到端测试用，测试结束会删除。",
    "forms": ["tolerate", "tolerated", "tolerating"],
    "additional_evidence": [],
}


class WorkbenchFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ADDITIONS.exists():
            shutil.copyfile(ADDITIONS, BACKUP)
        store.save_additions(store.empty_additions())

    @classmethod
    def tearDownClass(cls):
        if BACKUP.exists():
            shutil.copyfile(BACKUP, ADDITIONS)
            BACKUP.unlink()
        else:
            ADDITIONS.unlink(missing_ok=True)
        # 恢复生成物，避免留下测试词
        subprocess.run([runtime.interpreter(), "-B", str(ROOT / "main.py")],
                       cwd=str(ROOT), capture_output=True, timeout=600)

    def test_make_entry_rejects_missing_evidence(self):
        with self.assertRaises(ValueError):
            store.make_entry({"lemma": "tolerate", "example": ""}, [])
        with self.assertRaises(ValueError):
            store.make_entry({"lemma": "tolerate", "example": "Nothing matches here."}, [])

    def test_save_then_generate(self):
        from vocabulary_app import server

        result = server.save_entries({"entries": [ENTRY]})
        self.assertEqual(result["created"], ["testunit-01"], result)
        self.assertEqual(result["errors"], [])

        # 重复保存不会覆盖，只记为跳过
        again = server.save_entries({"entries": [ENTRY]})
        self.assertEqual(again["created"], [])
        self.assertIn("tolerate", again["skipped"])

        summary = server.rebuild_pages()
        self.assertTrue(summary["ok"])

        data = json.loads((ROOT / "data" / "vocabulary.json").read_text(encoding="utf-8"))
        merged = json.loads((ROOT / "data" / "vocabulary_additions.json").read_text(encoding="utf-8"))
        self.assertNotIn("testunit-01", {entry["id"] for entry in data["entries"]},
                         "测试词不应写进主词库")
        self.assertIn("testunit-01", {entry["id"] for entry in merged["entries"]})

        study = (ROOT / "output" / "study-data.js").read_text(encoding="utf-8")
        self.assertIn("tolerate", study, "新词没有进入学习资料")
        index = (ROOT / "output" / "index.html").read_text(encoding="utf-8")
        self.assertIn("tolerate", index, "新词没有出现在总复习页")
        self.assertIn("端到端测试材料", index, "来源分组没有写入页面")


READING_ENTRY = {
    "id": "readtest-01",
    "lemma": "stark",
    "form": "stark",
    "forms": ["stark"],
    "ipa": "stɑːk",
    "pos": "adj.",
    "common": "adj. 鲜明的；严酷的",
    "meaning": "adj. 严酷的（形容劳动力市场）",
    "short_meaning": "adj. 严酷的（形容劳动力市场）",
    "example": "The report paints a stark picture of a labour market that has become increasingly polarised.",
    "translation": "这份报告描绘了一幅严酷的图景：劳动力市场日益两极分化。",
    "category": "news",
    "source_name": "纽约时报",
    "link": "https://www.nytimes.com/2024/03/11/business/labour-market.html?utm_source=newsletter",
    "location": "第 3 段",
    "capture": "text",
    "captured_at": "2026-09-16",
}


class ReadingScenarioTest(unittest.TestCase):
    """外刊／书籍场景：来源、链接与原文都要跟着词条一起进库并出现在页面上。"""

    @classmethod
    def setUpClass(cls):
        if ADDITIONS.exists():
            shutil.copyfile(ADDITIONS, BACKUP)
        store.save_additions(store.empty_additions())

    @classmethod
    def tearDownClass(cls):
        if BACKUP.exists():
            shutil.copyfile(BACKUP, ADDITIONS)
            BACKUP.unlink()
        else:
            ADDITIONS.unlink(missing_ok=True)
        subprocess.run([runtime.interpreter(), "-B", str(ROOT / "main.py")],
                       cwd=str(ROOT), capture_output=True, timeout=600)

    def test_source_fields_and_link_normalisation(self):
        entry = store.make_entry(READING_ENTRY, [])
        self.assertEqual(entry["category"], "news")
        self.assertEqual(entry["source_name"], "纽约时报")
        self.assertEqual(entry["source_group"], "外刊文章｜纽约时报")
        self.assertTrue(entry["section_id"].startswith("read-news-"), entry["section_id"])
        self.assertNotIn("utm_source", entry["link"], "跟踪参数没有被去掉")
        self.assertTrue(entry["link"].startswith("https://www.nytimes.com/2024/03/11/"))

    def test_book_entry_without_link(self):
        payload = dict(READING_ENTRY, id="readtest-02", lemma="fraud", form="fraud", forms=["fraud"],
                       category="book", source_name="Sapiens", link="", location="第 5 章",
                       example="Sapiens argues that the Agricultural Revolution was history's biggest fraud.")
        entry = store.make_entry(payload, [])
        self.assertEqual(entry["category"], "book")
        self.assertEqual(entry["source_group"], "书籍｜Sapiens")
        self.assertEqual(entry["link"], "")

    def test_reading_entry_reaches_pages(self):
        from vocabulary_app import server
        result = server.save_entries({"entries": [READING_ENTRY]})
        self.assertEqual(result["created"], ["readtest-01"], result)
        server.rebuild_pages()
        index = (ROOT / "output" / "index.html").read_text(encoding="utf-8")
        self.assertIn("外刊文章｜纽约时报", index, "来源分组没有出现在页面")
        self.assertIn("nytimes.com", index, "原文链接没有出现在页面")
        self.assertIn("stark", index)


if __name__ == "__main__":
    unittest.main(verbosity=2)
