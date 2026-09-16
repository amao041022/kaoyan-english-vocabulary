"""个人词库卡片：与页面 PersonalCore 的一致性验证。

工作台收集的词会以“个人词条卡片”进入浏览器的个人词库。只要有一张卡片不合法，
页面上的 PersonalLibrary.sync() 就会抛错，整套个人词库都会失效，
所以这里既校验 Python 侧的规则，也把生成的卡片交给真正的 JS 实现复核。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vocabulary_app import personal_cards as P  # noqa: E402

NODE = shutil.which("node")
JS_CORE = ROOT / "assets" / "personal-core.js"

CARD_CASES = [
    ("abdicate", "v. 君主退位", ""),
    ("stark", "adj. 严酷的（形容劳动力市场）", ""),
    ("stark", "adj. 严酷的", "unit-123"),
    ("Herding", "n. 群聚、从众本能", ""),
]


@unittest.skipUnless(NODE and JS_CORE.exists(), "需要 Node 与 personal-core.js")
class CardIdParityTest(unittest.TestCase):
    """编号算法必须与 JS 完全一致，否则同一个义项会被当成两张卡片。"""

    def js_ids(self, cases: list[tuple[str, str, str]]) -> list[str]:
        script = (
            f"const P=require({json.dumps(str(JS_CORE))});"
            f"const cases={json.dumps(cases)};"
            "for(const [l,m,t] of cases)console.log(P.cardId(l,m,t));"
        )
        result = subprocess.run([NODE, "-e", script], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return result.stdout.decode().split()

    def test_ids_match(self):
        expected = self.js_ids(CARD_CASES)
        got = [P.card_id(lemma, meaning, target) for lemma, meaning, target in CARD_CASES]
        self.assertEqual(got, expected)

    def test_normalisation_matches(self):
        values = ["  Stark  ", "ＡＢＣ", "multiple   spaces", "结尾；"]
        script = "\n".join([
            f"const P=require({json.dumps(str(JS_CORE))});",
            f"const values={json.dumps(values, ensure_ascii=False)};",
            "for(const v of values)console.log(JSON.stringify(P.normalize(v)));",
        ])
        result = subprocess.run([NODE, "-e", script], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        lines = result.stdout.decode().splitlines()
        self.assertEqual(len(lines), len(values))
        for line, value in zip(lines, values):
            self.assertEqual(json.loads(line), P.normalize(value), f"NFKC 归一化不一致：{value!r}")


class CardShapeTest(unittest.TestCase):
    def entry(self, **overrides) -> dict:
        payload = {
            "lemma": "stark", "form": "stark", "forms": ["stark", "starker"],
            "ipa": "stɑːk", "meaning": "adj. 严酷的",
            "common": "adj. 鲜明的；严酷的",
            "example": "The report paints a stark picture.",
            "translation": "报告描绘了一幅严酷的图景。",
            "category": "news", "source_name": "纽约时报",
            "link": "https://www.nytimes.com/2024/03/11/business/x.html",
            "location": "第 3 段", "section_id": "read-news-nyt",
            "section_title": "外刊文章｜纽约时报", "source_group": "外刊文章｜纽约时报",
        }
        payload.update(overrides)
        return payload

    def test_shape_and_self_check(self):
        cards, errors = P.cards_from_entries([self.entry()], int(time.time() * 1000))
        self.assertEqual(errors, [])
        card = cards[0]
        self.assertTrue(card["id"].startswith("pc-"))
        self.assertEqual(P.validate_card(card)["id"], card["id"])
        self.assertEqual(card["contexts"][0]["kind"], "saved")
        self.assertIn("nytimes.com", card["contexts"][0]["location"])
        self.assertEqual(card["targetId"], "", "工作台卡片不应关联原有学习单元")

    def test_exam_entry_uses_passage_kind(self):
        cards, errors = P.cards_from_entries([self.entry(
            category="exam", year=2017, exam_record_id="2017:text1:passage:p-section2-part-a-1-1:87",
            section_id="2017-t1", location="第 1 段")], int(time.time() * 1000))
        self.assertEqual(errors, [])
        context = cards[0]["contexts"][0]
        self.assertEqual(context["kind"], "passage")
        self.assertEqual(context["sourceUrl"], "exams/2017.html#87")

    def test_missing_meaning_is_rejected(self):
        cards, errors = P.cards_from_entries([self.entry(meaning="", common="", short_meaning="")],
                                             int(time.time() * 1000))
        self.assertEqual(cards, [])
        self.assertTrue(errors and "meaning" in errors[0], errors)

    def test_overlong_field_is_rejected(self):
        cards, errors = P.cards_from_entries([self.entry(meaning="x" * 1001)], int(time.time() * 1000))
        self.assertEqual(cards, [])
        self.assertTrue(errors, "超长释义必须被拒绝")

    def test_duplicate_meaning_is_deduped(self):
        entry = self.entry()
        cards, errors = P.cards_from_entries([entry, dict(entry)], int(time.time() * 1000))
        self.assertEqual(len(cards), 1)
        self.assertTrue(any("重复" in message for message in errors), errors)

    @unittest.skipUnless(NODE and JS_CORE.exists(), "需要 Node 与 personal-core.js")
    def test_generated_cards_pass_js_validator(self):
        cards, _ = P.cards_from_entries(
            [self.entry(), self.entry(lemma="precarious", form="precarious", forms=["precarious"],
                                      meaning="adj. 不稳定的")],
            int(time.time() * 1000))
        script = (
            f"const P=require({json.dumps(str(JS_CORE))});"
            f"const cards={json.dumps(cards, ensure_ascii=False)};"
            "const ok=P.validateCards(cards);console.log('OK',ok.length);"
        )
        result = subprocess.run([NODE, "-e", script], capture_output=True, timeout=60)
        output = result.stdout.decode() + result.stderr.decode()
        self.assertEqual(result.returncode, 0, output)
        self.assertIn(f"OK {len(cards)}", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
