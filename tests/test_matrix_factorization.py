"""Real train/validation fixtures only; never read the held-out test split."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from backend.train_baselines import DATA, read_interactions, checksum
from backend.train_matrix_factorization import (
    MODELS, Config, MatrixFactorization, rating_metrics, ranking_metrics,
)


class MatrixFactorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=read_interactions(DATA/'train.csv')
        cls.validation=read_interactions(DATA/'validation.csv')
        cls.model=MatrixFactorization.load()
        cls.metrics=json.loads((DATA/'matrix_factorization_validation_metrics.json').read_text(encoding='utf-8'))
        cls.small=cls.train.head(150).copy()
        cls.config=Config(factors=3,epochs=2,batch_size=64,seed=2026)

    def test_prediction_equation_clipping_and_unknown_fallback(self):
        rows=self.validation.head(40)
        expected=[]
        for row in rows.itertuples(index=False):
            u,b=self.model.user_lookup[row.user_id],self.model.item_lookup[row.gmap_id]
            expected.append(self.model.mean+float(self.model.user_bias[u])+float(self.model.item_bias[b])
                            +float(np.dot(self.model.user_factors[u].astype(float),self.model.item_factors[b].astype(float))))
        np.testing.assert_allclose(self.model.predict(rows.user_id,rows.gmap_id,clip=False),expected,atol=1e-12)
        np.testing.assert_allclose(self.model.predict(rows.user_id,rows.gmap_id),np.clip(expected,1,5))
        small,_=MatrixFactorization.fit(self.small,sorted(self.small.gmap_id.unique()),self.config)
        unknown_user=next(u for u in self.validation.user_id if u not in small.user_lookup)
        unknown_item=next(b for b in self.validation.gmap_id if b not in small.item_lookup)
        self.assertEqual(small.predict([unknown_user],[unknown_item])[0],small.mean)

    def test_reproducibility(self):
        catalog=sorted(self.small.gmap_id.unique())
        first,history_a=MatrixFactorization.fit(self.small,catalog,self.config)
        second,history_b=MatrixFactorization.fit(self.small,catalog,self.config)
        for name in ['user_factors','item_factors','user_bias','item_bias']:
            np.testing.assert_array_equal(getattr(first,name),getattr(second,name))
        self.assertEqual(history_a,history_b)

    def test_training_only_fitting_and_immutable_evaluation(self):
        # Fit cannot consume a validation argument, and creates IDs/mean solely
        # from genuine training rows. Evaluation must leave parameters untouched.
        fitted,_=MatrixFactorization.fit(self.small,sorted(self.small.gmap_id.unique()),self.config)
        self.assertEqual(fitted.mean,self.small.rating.mean())
        self.assertEqual(set(fitted.users),set(self.small.user_id))
        self.assertEqual(sum(len(v) for v in fitted.histories.values()),len(self.small))
        with self.assertRaises(TypeError):
            MatrixFactorization.fit(self.small,fitted.items,self.config,validation=self.validation)
        snapshot=[getattr(self.model,name).copy() for name in ['user_factors','item_factors','user_bias','item_bias']]
        rating_metrics(self.model,self.validation.head(100))
        for name,expected in zip(['user_factors','item_factors','user_bias','item_bias'],snapshot):
            np.testing.assert_array_equal(getattr(self.model,name),expected)

    def test_ranking_exclusions_and_deterministic_id_ties(self):
        for user in self.validation.user_id.head(10):
            scores=self.model.score_catalog([user])[0]
            expected=sorted((item for item in self.model.items if item not in self.model.histories[user]),
                            key=lambda item:(-scores[self.model.item_lookup[item]],item))[:10]
            self.assertEqual(self.model.recommend(user),expected)
            self.assertFalse(set(expected)&self.model.histories[user])
        # Equal model scores on genuine catalog IDs test deterministic sorting;
        # this is a controlled scoring stub, not fabricated ratings or interactions.
        user=self.validation.user_id.iloc[0]
        with patch.object(self.model,'score_catalog',return_value=np.zeros((1,len(self.model.items)))):
            actual=self.model.recommend(user)
        self.assertEqual(actual,[b for b in sorted(self.model.items) if b not in self.model.histories[user]][:10])

    def test_rating_metrics_independently(self):
        predicted=self.model.predict(self.validation.user_id,self.validation.gmap_id)
        error=predicted-self.validation.rating.to_numpy()
        self.assertAlmostEqual(self.metrics['rating_prediction']['mae'],float(sum(abs(error))/len(error)),places=10)
        self.assertAlmostEqual(self.metrics['rating_prediction']['rmse'],float(np.linalg.norm(error)/np.sqrt(len(error))),places=10)

    def test_ranking_metrics_full_catalog_independently(self):
        relevant=self.validation.loc[self.validation.rating.ge(4)]
        hits,gain=0,0.0
        # Independent target-rank calculation over the complete candidate pool,
        # instead of using the production top-10 sorter.
        with threadpool_limits(limits=1):
            for start in range(0,len(relevant),256):
                rows=relevant.iloc[start:start+256]
                scores=self.model.score_catalog(rows.user_id.tolist())
                for index,row in enumerate(rows.itertuples(index=False)):
                    target=self.model.item_lookup[row.gmap_id]
                    eligible=np.ones(len(self.model.items),dtype=bool)
                    eligible[[self.model.item_lookup[b] for b in self.model.histories[row.user_id]]]=False
                    outranks=(scores[index]>scores[index,target]) | ((scores[index]==scores[index,target]) & (np.arange(len(self.model.items))<target))
                    rank=1+np.count_nonzero(eligible & outranks)
                    if rank<=10:
                        hits+=1
                        gain+=1/np.log2(rank+1)
        ranking=self.metrics['ranking']
        self.assertEqual(len(relevant),23806)
        self.assertEqual(ranking['eligible_users'],len(relevant))
        self.assertEqual(ranking['hit_users'],hits)
        self.assertAlmostEqual(ranking['recall_at_10'],hits/len(relevant))
        self.assertAlmostEqual(ranking['ndcg_at_10'],gain/len(relevant))

    def test_loading_roundtrip_and_checksum_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            self.model.save(directory)
            restored=MatrixFactorization.load(directory)
            np.testing.assert_array_equal(restored.predict(self.validation.user_id.head(10),self.validation.gmap_id.head(10)),
                                          self.model.predict(self.validation.user_id.head(10),self.validation.gmap_id.head(10)))
            self.assertEqual(restored.histories,self.model.histories)
            path=Path(directory)/'model.npz'
            with path.open('ab') as stream: stream.write(b'corruption')
            with self.assertRaisesRegex(ValueError,'checksum'):
                MatrixFactorization.load(directory)

    def test_small_search_selection_and_input_provenance(self):
        search=json.loads((DATA/'matrix_factorization_search.json').read_text(encoding='utf-8'))
        self.assertEqual(len(search['trials']),8)
        expected=min(search['trials'],key=lambda row:(row['validation']['rmse'],row['trial']))
        self.assertEqual(search['selected_trial'],expected['trial'])
        self.assertEqual(asdict(self.model.config),expected['config'])
        self.assertFalse(self.metrics['test_data_used'])
        self.assertEqual(set(self.metrics['inputs_sha256']),{'train.csv','validation.csv','attraction_mapping.csv','baseline_validation_metrics.json'})
        for name,digest in self.metrics['inputs_sha256'].items():
            self.assertEqual(checksum(DATA/name),digest)
        baseline=json.loads((DATA/'baseline_validation_metrics.json').read_text(encoding='utf-8'))
        self.assertEqual(self.metrics['ranking']['eligible_users'],baseline['popularity_ranking']['users_with_relevant_holdout'])
        self.assertEqual(self.metrics['ranking']['catalog_size'],baseline['popularity_ranking']['complete_catalog_size'])


if __name__=='__main__':
    unittest.main()
