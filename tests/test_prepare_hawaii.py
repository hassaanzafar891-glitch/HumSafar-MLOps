"""Verify prepared genuine Hawaii data; no generated ratings or labels."""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import unittest

import pandas as pd

from backend.inspect_hawaii import ATTRACTION_CATEGORIES
from backend.prepare_hawaii import ROOT, OUTPUT, deduplicate_and_core, select_metadata, sha256


DTYPES={'user_id':str,'gmap_id':str}


class PrepareHawaiiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit=json.loads((OUTPUT/'audit.json').read_text(encoding='utf-8'))
        cls.all=pd.read_csv(OUTPUT/'interactions.csv',dtype=DTYPES)
        cls.parts={p:pd.read_csv(OUTPUT/f'{p}.csv',dtype=DTYPES) for p in ['train','validation','test']}

    def test_exact_inspection_filter_and_core_counts(self):
        inspection=json.loads((ROOT/'data/processed/hawaii_inspection.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(ATTRACTION_CATEGORIES),inspection['category_filter']['allowlist'])
        self.assertEqual(self.audit['category_filter'],inspection['category_filter'])
        for key in ['interactions','users','attractions']:
            self.assertEqual(self.audit['five_core'][key],inspection['iterative_cores_after_tourist_filter']['5'][key])
        self.assertGreaterEqual(self.all.groupby('user_id').size().min(),5)
        self.assertGreaterEqual(self.all.groupby('gmap_id').size().min(),5)

    def test_split_partition_and_no_duplicates(self):
        combined=pd.concat(self.parts.values(),ignore_index=True)
        self.assertFalse(combined.duplicated(['user_id','gmap_id']).any())
        self.assertEqual(len(combined),len(self.all))
        columns=self.all.columns.tolist()
        pd.testing.assert_frame_equal(combined.sort_values(['user_id','gmap_id']).reset_index(drop=True)[columns],
                                      self.all.sort_values(['user_id','gmap_id']).reset_index(drop=True))

    def test_chronology_and_deterministic_ties(self):
        ordered=self.all.sort_values(['user_id','timestamp_ms','gmap_id'],ascending=[True,False,True],kind='stable')
        ranks=ordered.groupby('user_id').cumcount()
        for part,rank in [('test',0),('validation',1)]:
            expected=ordered.loc[ranks.eq(rank),['user_id','gmap_id','timestamp_ms']].sort_values('user_id').reset_index(drop=True)
            actual=self.parts[part][expected.columns].sort_values('user_id').reset_index(drop=True)
            pd.testing.assert_frame_equal(actual,expected)
        self.assertEqual(self.audit['audit']['checks']['users_with_timestamp_order_violations'],0)

    def test_training_coverage_and_ratings(self):
        train=self.parts['train']
        for part in ['validation','test']:
            self.assertTrue(set(self.parts[part]['user_id'])<=set(train['user_id']))
            self.assertTrue(set(self.parts[part]['gmap_id'])<=set(train['gmap_id']))
        self.assertGreaterEqual(train.groupby('user_id').size().min(),3)
        self.assertTrue(self.all['rating'].between(1,5).all())
        self.assertFalse(self.all.isna().any().any())
        self.assertTrue(pd.api.types.is_integer_dtype(self.all['timestamp_ms']))
        self.assertTrue(self.all['timestamp_ms'].ge(0).all())

    def test_stable_reversible_numerical_mappings(self):
        for filename,id_col,index_col in [('user_mapping.csv','user_id','user_index'),
                                           ('attraction_mapping.csv','gmap_id','attraction_index')]:
            mapping=pd.read_csv(OUTPUT/filename,dtype={id_col:str})
            self.assertEqual(mapping[id_col].tolist(),sorted(self.all[id_col].unique()))
            self.assertEqual(mapping[index_col].tolist(),list(range(len(mapping))))
            looked_up=self.all[id_col].map(dict(zip(mapping[id_col],mapping[index_col])))
            self.assertEqual(looked_up.tolist(),self.all[index_col].tolist())

    def test_metadata_preserved_and_filter_reused(self):
        selected,_=select_metadata(ROOT/'data/raw/meta-Hawaii.json.gz')
        with (OUTPUT/'attractions.jsonl').open(encoding='utf-8') as stream:
            saved=[json.loads(line) for line in stream]
        self.assertEqual(len(saved),self.all['gmap_id'].nunique())
        for item in saved:
            source=item['source_metadata']
            self.assertEqual(source,selected[source['gmap_id']]['source_metadata'])
            self.assertTrue(item['matched_attraction_categories'])
            self.assertTrue(any(c.casefold() in {v.casefold() for v in ATTRACTION_CATEGORIES}
                                for c in item['matched_attraction_categories']))

    def test_source_and_output_checksums(self):
        for filename,info in self.audit['sources'].items():
            self.assertEqual(sha256(ROOT/'data/raw'/filename),info['sha256'])
        for filename,info in self.audit['generated_files'].items():
            self.assertEqual(sha256(OUTPUT/filename),info['sha256'])
        self.assertTrue(self.audit['audit']['structural_checks_passed'])
        self.assertTrue(all(n==0 for n in self.audit['audit']['checks'].values()))

    def test_duplicate_timestamp_tie_keeps_later_source_record(self):
        # Duplicate an unchanged genuine row to exercise ingestion tie-breaking.
        row=self.all.iloc[0]
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE reviews(seq INTEGER PRIMARY KEY,u TEXT,b TEXT,r REAL,t INTEGER)')
            for seq in [10,20]:
                db.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',
                           (seq,row.user_id,row.gmap_id,float(row.rating),int(row.timestamp_ms)))
            deduplicate_and_core(db,minimum=1)
            self.assertEqual(db.execute('SELECT seq FROM edges').fetchone()[0],20)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM core').fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
