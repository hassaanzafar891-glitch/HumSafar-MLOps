"""BPR checks use genuine training/validation data; test.csv is never opened."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from backend.train_baselines import DATA, checksum, read_interactions
from backend.train_bpr import BPR, Config, ComparisonSampler, evaluate


class BPRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=read_interactions(DATA/'train.csv')
        cls.validation=read_interactions(DATA/'validation.csv')
        cls.model=BPR.load()
        cls.metrics=json.loads((DATA/'bpr_validation_metrics.json').read_text(encoding='utf-8'))
        cls.small=cls.train.head(256).copy()
        cls.config=Config(factors=4,epochs=2,batch_size=64)

    def test_training_only_fit_and_positive_threshold(self):
        # Fitting is self-contained: no data reads and no validation argument.
        with patch('pandas.read_csv',side_effect=AssertionError('Unexpected fit data access')):
            model,report=BPR.fit(self.small,self.model.items,self.config)
        self.assertEqual(report['positive_training_rows'],int(self.small.rating.ge(4).sum()))
        self.assertEqual(set(model.users),set(self.small.user_id))
        self.assertEqual(int(model.item_counts.sum()),len(self.small))
        for user,rows in self.small.groupby('user_id'):
            self.assertEqual(model.histories[user],set(rows.gmap_id))
        with self.assertRaises(TypeError):
            BPR.fit(self.small,self.model.items,self.config,validation=self.validation)

    def test_comparisons_exclude_all_training_interactions(self):
        sampler=ComparisonSampler(self.model.histories,self.model.users,self.model.items)
        users=np.repeat(np.arange(len(self.model.users)),3)
        first=sampler.sample(users,np.random.default_rng(2026))
        second=sampler.sample(users,np.random.default_rng(2026))
        np.testing.assert_array_equal(first,second)
        self.assertTrue(((first>=0)&(first<len(self.model.items))).all())
        self.assertFalse(sampler.seen[users,first].any())
        # Low-rated training interactions are explicitly seen/excluded too.
        low=self.train.loc[self.train.rating.lt(4)]
        self.assertGreater(len(low),0)
        for row in low.head(500).itertuples(index=False):
            self.assertTrue(sampler.seen[self.model.user_lookup[row.user_id],self.model.item_lookup[row.gmap_id]])

    def test_reproducibility(self):
        first,history_a=BPR.fit(self.small,self.model.items,self.config)
        second,history_b=BPR.fit(self.small,self.model.items,self.config)
        for name in ['user_factors','item_factors','item_bias','item_counts']:
            np.testing.assert_array_equal(getattr(first,name),getattr(second,name))
        self.assertEqual(history_a,history_b)

    def test_ranking_exclusions_hybrid_formula_and_ties(self):
        for user in self.validation.user_id.head(10):
            raw=self.model.score_catalog([user])[0]
            eligible=[b for b in self.model.items if b not in self.model.histories[user]]
            expected=sorted(eligible,key=lambda b:(-raw[self.model.item_lookup[b]],b))[:10]
            self.assertEqual(self.model.recommend(user,alpha=1),expected)
            for alpha in [0,.25,.5,.75,1]:
                self.assertFalse(set(self.model.recommend(user,alpha=alpha))&self.model.histories[user])
            indices=[self.model.item_lookup[b] for b in eligible]
            pop=np.log1p(self.model.item_counts[indices])
            bpr=(raw[indices]-raw[indices].min())/np.ptp(raw[indices])
            pop=(pop-pop.min())/np.ptp(pop)
            scores=.25*bpr+.75*pop
            expected=[b for _,b in sorted(zip(-scores,eligible))[:10]]
            self.assertEqual(self.model.recommend(user,alpha=.25),expected)
        user=self.validation.user_id.iloc[0]
        with patch.object(self.model,'score_catalog',return_value=np.zeros((1,len(self.model.items)))):
            actual=self.model.recommend(user,alpha=1)
        self.assertEqual(actual,[b for b in sorted(self.model.items) if b not in self.model.histories[user]][:10])

    def test_metrics_independently_over_complete_catalog(self):
        relevant=self.validation.loc[self.validation.rating.ge(4)]
        alpha=self.model.hybrid_weight
        totals={weight:[0,0.0] for weight in [1.0,alpha]}
        with threadpool_limits(limits=1):
            for start in range(0,len(relevant),256):
                rows=relevant.iloc[start:start+256]
                raw=self.model.score_catalog(rows.user_id.tolist())
                for offset,row in enumerate(rows.itertuples(index=False)):
                    eligible=np.array([self.model.items[i] not in self.model.histories[row.user_id] for i in range(len(self.model.items))])
                    target=self.model.item_lookup[row.gmap_id]
                    r=raw[offset]
                    norm_bpr=(r-r[eligible].min())/np.ptp(r[eligible]) if np.ptp(r[eligible]) else np.zeros_like(r)
                    pop=np.log1p(self.model.item_counts)
                    norm_pop=(pop-pop[eligible].min())/np.ptp(pop[eligible]) if np.ptp(pop[eligible]) else np.zeros_like(pop)
                    for weight in totals:
                        scores=weight*norm_bpr+(1-weight)*norm_pop
                        outranks=(scores>scores[target])|((scores==scores[target])&(np.arange(len(scores))<target))
                        rank=1+np.count_nonzero(eligible&outranks)
                        if rank<=10:
                            totals[weight][0]+=1
                            totals[weight][1]+=1/np.log2(rank+1)
        self.assertEqual(len(relevant),23806)
        for name,weight in [('bpr',1.0),('hybrid',alpha)]:
            reported=self.metrics[name]
            hits,gain=totals[weight]
            self.assertEqual(reported['hit_users'],hits)
            self.assertEqual(reported['eligible_users'],len(relevant))
            self.assertAlmostEqual(reported['recall_at_10'],hits/len(relevant))
            self.assertAlmostEqual(reported['ndcg_at_10'],gain/len(relevant))

    def test_popularity_endpoint_matches_existing_baseline(self):
        baseline=json.loads((DATA/'baseline_validation_metrics.json').read_text(encoding='utf-8'))
        with threadpool_limits(limits=1):
            result=evaluate(self.model,self.validation,alphas=(0,))[0]
        for metric in ['recall_at_10','ndcg_at_10']:
            self.assertAlmostEqual(result[metric],baseline['popularity_ranking'][metric])

    def test_saved_model_loading_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            self.model.save(directory)
            restored=BPR.load(directory)
            np.testing.assert_array_equal(restored.score_catalog(self.model.users[:5]),self.model.score_catalog(self.model.users[:5]))
            self.assertEqual(restored.hybrid_weight,self.model.hybrid_weight)
            self.assertEqual(restored.histories,self.model.histories)
            self.assertEqual(restored.recommend(self.model.users[0]),self.model.recommend(self.model.users[0]))
            with (Path(directory)/'model.npz').open('ab') as stream:stream.write(b'corrupted')
            with self.assertRaisesRegex(ValueError,'checksum'):
                BPR.load(directory)

    def test_search_selection_and_no_input_changes(self):
        search=json.loads((DATA/'bpr_search.json').read_text(encoding='utf-8'))
        self.assertEqual(len(search['trials']),8)
        best=min(search['trials'],key=lambda row:(-row['validation']['ndcg_at_10'],-row['validation']['recall_at_10'],row['trial']))
        self.assertEqual(search['selected_trial'],best['trial'])
        self.assertEqual(best['config'],asdict(self.model.config))
        hybrid=min(search['hybrid_trials'],key=lambda row:(-row['ndcg_at_10'],-row['recall_at_10'],row['alpha']))
        self.assertEqual(hybrid['alpha'],self.model.hybrid_weight)
        self.assertFalse(self.metrics['test_data_used'])
        self.assertEqual(set(self.metrics['inputs_sha256']),{'train.csv','validation.csv','attraction_mapping.csv','baseline_validation_metrics.json','matrix_factorization_validation_metrics.json'})
        for name,digest in self.metrics['inputs_sha256'].items():
            self.assertEqual(checksum(DATA/name),digest)


if __name__=='__main__':
    unittest.main()
