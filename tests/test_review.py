"""检查复现统计易出错的边界，不依赖浏览器或第三方库。"""
import unittest

from main import build_index, excerpt, pattern, speech_text, source_group, render_entries, AUDIO_TEXTS


def entry(lemma: str, forms: list[str], sentence: str, section: str = "t1") -> dict:
    return {"lemma": lemma, "forms": forms, "example": sentence, "section_id": section,
            "year": 2016, "location": "正文", "additional_evidence": []}


class RecurrenceTests(unittest.TestCase):
    def test_similar_spelling_and_derivation_do_not_merge(self):
        self.assertIsNone(pattern(["inherit", "inherited"]).search("an inherent problem"))
        self.assertIsNone(pattern(["prohibit", "prohibited"]).search("a prohibition"))
        self.assertIsNotNone(pattern(["inherit", "inherited"]).search("inherited wealth"))

    def test_shared_sentence_is_counted_once(self):
        sentence = "The government did not anticipate the steep increase."
        data = {"entries": [entry("anticipate", ["anticipate"], sentence),
                             entry("steep", ["steep"], sentence)]}
        index, contexts = build_index(data)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(len(index["steep"]["hits"]), 1)

    def test_same_lemma_keeps_distinct_passages_and_senses(self):
        data = {"entries": [entry("state", ["state"], "indicating the state of", "t1"),
                             entry("state", ["state"], "heads of state", "t2")]}
        index, _ = build_index(data)
        self.assertEqual(index["state"]["passages"], 2)
        self.assertEqual(len(index["state"]["entries"]), 2)

    def test_excerpt_remains_original_and_keeps_target(self):
        sentence = "The introduction is long and descriptive. " * 5 + "This reinforces the need for fairness."
        matcher = pattern(["reinforce", "reinforces"])
        short = excerpt(sentence, matcher)
        self.assertIn("reinforces", short)
        fragment = short.removeprefix("… ").removesuffix(" …")
        self.assertIn(fragment, sentence)


class AudioAndSourceTests(unittest.TestCase):
    def test_unknown_year_is_not_an_exam_year(self):
        a = entry("convert", ["convert"], "convert the machine", "workbook")
        a.update(year=None, source_group="练习册 Unit 2")
        b = entry("convert", ["convert"], "convert the land", "2021-ii-t2")
        b.update(year=2021, source_group="2021 英语（二）")
        index, _ = build_index({"entries": [a, b]})
        self.assertEqual(index["convert"]["passages"], 2)
        self.assertEqual(source_group(a), "练习册 Unit 2")
        self.assertEqual(source_group(b), "2021 英语（二）")

    def test_retake_does_not_inflate_recurrence(self):
        a = entry("mill", ["mill", "mills"], "The mills closed.")
        a["photo"] = "first.jpg"
        a["additional_evidence"] = [dict(a, photo="retake.jpg")]
        index, contexts = build_index({"entries": [a]})
        self.assertEqual(len(contexts), 1)
        self.assertEqual(len(index["mill"]["hits"]), 1)

    def test_audio_blanks_and_money(self):
        self.assertEqual(speech_text("They were __8__ or punished."), "They were blank or punished.")
        self.assertEqual(speech_text("The $285m plan costs $1bn."), "The 285 million dollars plan costs 1 billion dollars.")
        self.assertEqual(speech_text("They ________."), "They blank .")

    def test_compact_audio_uses_entire_original(self):
        sentence = "These words precede the target. " * 8 + "A mill was closed."
        a = entry("mill", ["mill"], sentence)
        a.update(id="test-mill", photo="test.jpg", section_title="Test", form="mill",
                 ipa="/mɪl/", short_meaning="工厂", common="工厂", meaning="工厂", translation="测试翻译")
        index, _ = build_index({"entries": [a]})
        AUDIO_TEXTS.clear()
        html = render_entries({"entries": [a]}, index, False)
        self.assertIn(sentence, AUDIO_TEXTS.values())
        self.assertIn("mill", AUDIO_TEXTS.values())
        self.assertEqual(len(AUDIO_TEXTS), 2)
        self.assertEqual(html.count('data-audio='), 3)


if __name__ == "__main__":
    unittest.main()
