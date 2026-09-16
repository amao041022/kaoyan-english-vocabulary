"""学习资料必须保留原句与独立词义，搭配的原文标记有据可查。"""
import json
import unittest
from pathlib import Path
from study_build import build_study

ROOT = Path(__file__).resolve().parents[1]


class StudyMaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT/'data/vocabulary.json').read_text(encoding='utf-8'))
        cls.config = json.loads((ROOT/'data/study_config.json').read_text(encoding='utf-8'))
        cls.study = build_study(cls.data, cls.config, lambda s: 'audio.wav')

    def test_every_record_has_one_stable_learning_unit(self):
        ids = {e['id'] for e in self.data['entries']}
        self.assertEqual(ids, set(self.study['entryUnits']))
        self.assertEqual(sum(len(u['members']) for u in self.study['units']), len(ids))
        self.assertEqual(ids, set(self.config['entries']))

    def test_same_sense_merges_but_convert_senses_stay_separate(self):
        m = self.study['entryUnits']
        self.assertEqual(m['2017-t2-13'], m['2017-t4-06'])
        self.assertEqual(len({m[x] for x in ['2017-t3-02','wb-u2-t3-07','2021-ii-t2-15']}),3)

    def test_original_sentences_and_translations_are_preserved(self):
        contexts={(c['section_id'],c['example'],c['translation']) for u in self.study['units'] for c in u['contexts']}
        for e in self.data['entries']:
            for c in [e,*e.get('additional_evidence',[])]:
                self.assertIn((c['section_id'],c['example'],c['translation']),contexts)

    def test_original_collocations_really_occur_in_saved_evidence(self):
        for e in self.data['entries']:
            items=self.config['entries'][e['id']]['collocations']
            self.assertLessEqual(len(items),3)
            for c in items:
                if c['source']=='原文搭配':
                    self.assertTrue(any(c['text'].casefold() in x['example'].casefold()
                                        for x in [e,*e.get('additional_evidence',[])]),(e['id'],c['text']))

    def test_invalid_alias_fails_instead_of_losing_entries(self):
        config={**self.config,'aliases':{'2015-t1-01':'2015-t1-02'}}
        with self.assertRaises(ValueError):
            build_study(self.data,config,lambda s:s)

    def test_unreviewed_new_word_uses_flip_card(self):
        result=build_study({'entries':[self.data['entries'][0]]}, {},lambda s:s)
        self.assertEqual(result['units'][0]['pos'],'unreviewed')
