"""真题导入与查询的回归验证：覆盖缺卷、丢选项、误匹配和来源错位。"""
import hashlib
import json
from pathlib import Path
import re
import unittest

from exam_bank import known_forms, search, sentence_spans, token_pattern

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / 'data' / 'exam_bank'


class ExamBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.papers = {year: json.loads((BANK / f'{year}.json').read_text(encoding='utf-8')) for year in range(2006, 2026)}

    def test_all_twenty_papers_and_nine_sections(self):
        manifest = json.loads((BANK / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['years'], list(self.papers))
        self.assertEqual(manifest['record_count'], sum(len(p['records']) for p in self.papers.values()))
        for paper in self.papers.values():
            self.assertEqual(len(paper['sections']), 9)
            self.assertTrue(all(paper['sections'].values()))
            ids = [r['id'] for r in paper['records']]
            self.assertEqual(len(ids), len(set(ids)))

    def test_reading_questions_and_cloze_options_complete(self):
        for paper in self.papers.values():
            records = paper['records']
            self.assertEqual(sum(r['kind'] == 'option' and r['section'] == 'cloze' for r in records), 80)
            for i in range(1, 5):
                reading = [r for r in records if r['section'] == f'text{i}']
                self.assertEqual(sum(r['kind'] == 'question' for r in reading), 5)
                self.assertEqual(sum(r['kind'] == 'option' for r in reading), 20)
            text = ' '.join(r['text'] for r in records if r['section'] == 'cloze' and r['kind'] == 'passage')
            self.assertEqual(set(re.findall(r'__(\d+)__', text)), {str(i) for i in range(1, 21)})

    def test_new_type_choices_are_not_lost(self):
        for year, paper in self.papers.items():
            choices = [r for r in paper['records'] if r['section'] == 'new_type' and r['kind'] in ('paragraph_option', 'option')]
            self.assertEqual(len(choices), 8 if year in (2023, 2025) else 7)

    def test_source_hashes_and_composition_images(self):
        for year, paper in self.papers.items():
            source = json.loads((BANK / f'{year}.source.json').read_text(encoding='utf-8'))
            for kind in ('html', 'pdf'):
                item = source[kind]
                self.assertEqual(hashlib.sha256((ROOT / item['path']).read_bytes()).hexdigest(), item['sha256'])
            self.assertEqual(len(paper['figures']), 1)
            for figure in paper['figures']:
                self.assertEqual(hashlib.sha256((ROOT / figure['path']).read_bytes()).hexdigest(), figure['sha256'])
                self.assertIn('../../' + figure['path'], (ROOT / f'output/exams/{year}.html').read_text(encoding='utf-8'))

    def test_existing_photo_example_and_known_inflection(self):
        hits = search(self.papers[2017], 'undermine', known_forms('undermine'), 'text1')
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['example'], 'But demanding too much of air travelers or providing too little security in return undermines public support for the process.')
        self.assertEqual(hits[0]['matched_forms'], ['undermines'])
        self.assertEqual(search(self.papers[2017], 'eligible')[0]['example'], 'Passengers who pass a background check are eligible to use expedited screening lanes.')

    def test_search_returns_all_passages_and_preserves_substrings(self):
        hits = search(self.papers[2017], 'undermine', known_forms('undermine'))
        self.assertEqual({h['section'] for h in hits}, {'text1', 'text4'})
        for hit in hits:
            self.assertEqual(hit['example'], hit['paragraph'][hit['start']:hit['end']])

    def test_unmatched_word_and_derivations_are_not_invented(self):
        self.assertEqual(search(self.papers[2006], 'not-a-real-exam-word'), [])
        matcher = token_pattern(['inherit'])
        self.assertFalse(matcher.search('inherent inheritance inherited'))
        self.assertFalse(token_pattern(['state']).search('statement'))
        self.assertTrue(token_pattern(['in return']).search('in   return'))

    def test_abbreviations_and_sentence_offsets(self):
        text = 'Dr. Smith lives in the U.S. and works at 3.5 dollars per hour. Is it true? Yes!'
        sentences = [text[a:b] for a, b in sentence_spans(text)]
        self.assertEqual(sentences, ['Dr. Smith lives in the U.S. and works at 3.5 dollars per hour.', 'Is it true?', 'Yes!'])

    def test_question_options_are_explicitly_classified(self):
        paper = self.papers[2017]
        hits = search(paper, 'belated')
        self.assertTrue(hits)
        self.assertEqual(hits[0]['kind'], 'option')
        self.assertIn('25', hits[0]['location'])

    def test_no_editorial_answers_or_hidden_placeholders(self):
        for paper in self.papers.values():
            for record in paper['records']:
                self.assertNotIn('占位符', record['text'])
                self.assertNotIn('答案速查', record['text'])
                self.assertNotIn('data-astro', record['text'])


if __name__ == '__main__':
    unittest.main()
