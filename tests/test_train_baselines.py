"""Tests read training/validation/catalog only; test.csv is never opened."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backend.train_baselines import DATA, MODELS, HawaiiBaselines, evaluate, read_interactions, run


class BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=read_interactions(DATA/'train.csv')
        cls.validation=read_interactions(DATA/'validation.csv')
        cls.catalog=pd.read_csv(DATA/'attraction_mapping.csv',dtype={'gmap_id':str})['gmap_id'].tolist()
        cls.model=HawaiiBaselines.fit(cls.train,cls.catalog)
        cls.metrics=json.loads((DATA/'baseline_validation_metrics.json').read_text(encoding='utf-8'))

    def test_means_and_counts_are_training_only(self):
        self.assertAlmostEqual(self.model.global_mean,self.train.rating.sum()/len(self.train))
        self.assertEqual(sum(self.model.item_counts.values()),len(self.train))
        for item,rows in self.train.groupby('gmap_id'):
            self.assertEqual(self.model.item_counts[item],len(rows))
            self.assertAlmostEqual(self.model.item_means[item],rows.rating.sum()/len(rows))

    def test_item_fallback_uses_training_global_mean(self):
        subset=self.train.head(100)
        model=HawaiiBaselines.fit(subset,self.catalog)
        unseen=next(item for item in self.catalog if item not in model.item_means)
        self.assertEqual(model.predict_item([unseen])[0],subset.rating.mean())
        self.assertTrue(np.all(model.predict_global([unseen,unseen])==subset.rating.mean()))

    def test_rating_metrics_against_independent_calculation(self):
        actual=self.validation.rating.to_numpy()
        mean=self.train.rating.mean()
        item_mean=self.train.groupby('gmap_id').rating.mean()
        for name,pred in [('global_mean',np.repeat(mean,len(actual))),
                          ('item_mean',self.validation.gmap_id.map(item_mean).fillna(mean).to_numpy())]:
            residual=actual-pred
            expected=self.metrics['rating_prediction'][name]
            self.assertAlmostEqual(expected['mae'],sum(abs(residual))/len(actual))
            self.assertAlmostEqual(expected['rmse'],float(np.linalg.norm(residual)/np.sqrt(len(actual))))

    def test_popularity_ties_and_seen_item_exclusion(self):
        counts=self.train.groupby('gmap_id').size().to_dict()
        expected=sorted(self.catalog,key=lambda item:(-counts.get(item,0),item))
        self.assertEqual(self.model.popularity_order,expected)
        # Actual equal-count items exercise the specified ID tie-break.
        self.assertLess(len(set(counts.values())),len(counts))
        for user in self.validation.user_id.head(30):
            seen=set(self.train.loc[self.train.user_id.eq(user),'gmap_id'])
            results=self.model.recommend(user)
            self.assertEqual(results,[item for item in expected if item not in seen][:10])
            self.assertFalse(set(results)&seen)
            self.assertEqual(len(results),10)

    def test_full_catalog_ranking_metrics_independently(self):
        # Compute target rank by its global position minus earlier seen items,
        # independently of recommend() and its top-k list construction.
        counts=self.train.groupby('gmap_id').size()
        order=sorted(self.catalog,key=lambda item:(-int(counts.get(item,0)),item))
        positions={item:rank for rank,item in enumerate(order,1)}
        histories=self.train.groupby('user_id').gmap_id.agg(list).to_dict()
        positive=self.validation.loc[self.validation.rating.ge(4)]
        hits=0
        gains=[]
        for row in positive.itertuples(index=False):
            rank=positions[row.gmap_id]-sum(positions[item]<positions[row.gmap_id] for item in histories[row.user_id])
            hit=rank<=10
            hits+=hit
            gains.append(1/np.log2(rank+1) if hit else 0)
        result=self.metrics['popularity_ranking']
        self.assertEqual(result['users_with_relevant_holdout'],len(positive))
        self.assertEqual(result['users_excluded_no_relevant_holdout'],len(self.validation)-len(positive))
        self.assertEqual(result['hit_users'],hits)
        self.assertAlmostEqual(result['recall_at_10'],hits/len(positive))
        self.assertAlmostEqual(result['ndcg_at_10'],sum(gains)/len(positive))

    def test_saved_artifact_reuses_exact_fitted_state(self):
        restored=HawaiiBaselines.load(MODELS/'baselines.joblib')
        np.testing.assert_array_equal(restored.predict_item(self.validation.gmap_id),self.model.predict_item(self.validation.gmap_id))
        self.assertEqual(restored.item_counts,self.model.item_counts)
        self.assertEqual(restored.histories,self.model.histories)
        self.assertEqual(restored.catalog,self.model.catalog)
        self.assertEqual(restored.recommend(self.validation.user_id.iloc[0]),self.model.recommend(self.validation.user_id.iloc[0]))

    def test_invalid_ranking_history_or_input_is_rejected(self):
        for k in [0,-1,True,1.5]:
            with self.subTest(k=k), self.assertRaises(ValueError):
                self.model.recommend(self.validation.user_id.iloc[0],k)
        with self.assertRaisesRegex(ValueError,'one validation'):
            evaluate(self.model,self.train.head(10))
        with self.assertRaisesRegex(ValueError,'overlaps'):
            evaluate(self.model,self.train.groupby('user_id').head(1).head(1))

    def test_run_reads_only_train_validation_and_catalog(self):
        original=pd.read_csv
        allowed={(DATA/name).resolve() for name in ['train.csv','validation.csv','attraction_mapping.csv']}
        def guarded(path,*args,**kwargs):
            if Path(path).resolve() not in allowed:
                raise AssertionError(f'Unexpected dataset access: {path}')
            return original(path,*args,**kwargs)
        with tempfile.TemporaryDirectory() as directory:
            # Preserve the metrics output by redirecting only the output write.
            original_write=Path.write_text
            def write(path,data,*args,**kwargs):
                if path==DATA/'baseline_validation_metrics.json':
                    path=Path(directory)/'metrics.json'
                return original_write(path,data,*args,**kwargs)
            with patch('backend.train_baselines.pd.read_csv',side_effect=guarded), patch.object(Path,'write_text',write):
                result=run(model_dir=Path(directory)/'models')
            self.assertEqual(result['rating_prediction'],self.metrics['rating_prediction'])
            self.assertEqual(result['popularity_ranking'],self.metrics['popularity_ranking'])
            self.assertFalse(result['training']['test_data_used'])


if __name__=='__main__':
    unittest.main()
