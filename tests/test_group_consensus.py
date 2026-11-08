"""Genuine train/validation groups and mathematical aggregation checks only."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from threadpoolctl import threadpool_limits

from backend.group_consensus import (
    ConsensusConfig, aggregate, consensus_step, form_groups, recommend_group, satisfaction,
)
from backend.evaluate_group_consensus import METHODS, build_recommendations, observed_metrics
from backend.train_baselines import DATA, ROOT, checksum, read_interactions
from backend.train_bpr import BPR


class GroupConsensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=read_interactions(DATA/'train.csv')
        cls.validation=read_interactions(DATA/'validation.csv')
        cls.users=sorted(cls.train.user_id.unique())
        cls.model=BPR.load()
        cls.report=json.loads((DATA/'group_validation_metrics.json').read_text(encoding='utf-8'))
        cls.details=json.loads((DATA/'group_validation_details.json').read_text(encoding='utf-8'))
        cls.lookup={u:(b,float(r)) for u,b,r in cls.validation[['user_id','gmap_id','rating']].itertuples(index=False,name=None)}

    def test_group_formation_reproducibility_and_training_membership(self):
        for size in [2,3,4,5]:
            first=form_groups(self.users,size)
            self.assertEqual(first,form_groups(self.users,size))
            self.assertNotEqual(first,form_groups(self.users,size,seed=2027))
            self.assertEqual(len(first),500)
            self.assertEqual(len({tuple(g) for g in first}),500)
            for members in first:
                self.assertEqual(len(set(members)),size)
                self.assertTrue(set(members)<=set(self.users))
            saved=[row['members'] for row in self.details if row['size']==size]
            self.assertEqual(first,saved)

    def test_complete_candidate_exclusion_and_individual_hybrid(self):
        for size in [2,3,4,5]:
            members=form_groups(self.users,size,count=1)[0]
            bundle=recommend_group(self.model,members)
            seen=set().union(*(self.model.histories[u] for u in members))
            expected=[b for b in self.model.items if b not in seen]
            self.assertEqual(bundle['candidate_ids'],expected)
            bpr,pop,_=self.model.normalized_components(members)
            for result in bundle['methods'].values():
                self.assertFalse(set(result['items'])&seen)
                self.assertEqual(len(set(result['items'])),10)
                indices=[self.model.item_lookup[b] for b in result['items']]
                values=(.75*bpr+.25*pop)[:,indices].mean(axis=1)
                np.testing.assert_allclose(values,result['predicted_member_utilities'])

    def test_aggregation_equations_and_adaptive_deficits(self):
        members=form_groups(self.users,4,count=1)[0]
        bpr,pop,allowed=self.model.normalized_components(members)
        scores=(.75*bpr+.25*pop)[:,allowed.all(axis=0)]
        np.testing.assert_array_equal(aggregate(scores,'average'),np.argsort(-scores.mean(0),kind='stable')[:10])
        np.testing.assert_array_equal(aggregate(scores,'least_misery'),np.argsort(-scores.min(0),kind='stable')[:10])
        cumulative=np.zeros(len(members))
        selected=[]
        for t in range(1,11):
            prior=cumulative/(t-1) if t>1 else np.zeros(len(members))
            w=(1-prior+.05)/(1-prior+.05).sum()
            projected=(cumulative[:,None]+scores)/t
            expected=.5*np.sum(w[:,None]*scores,axis=0)+.3*np.min(projected,axis=0)+.2*(1-(np.max(projected,axis=0)-np.min(projected,axis=0)))
            np.testing.assert_allclose(consensus_step(scores,cumulative,t),expected)
            self.assertGreaterEqual(w[np.argmin(prior)],w[np.argmax(prior)])
            expected[selected]=-np.inf
            chosen=int(np.argmax(expected))
            selected.append(chosen)
            cumulative+=scores[:,chosen]
        np.testing.assert_array_equal(aggregate(scores,'adaptive_consensus'),selected)

    def test_fairness_calculations_and_ties(self):
        for row in self.details[:20]:
            for result in row['recommendations'].values():
                values=np.array(result['predicted_member_utilities'])
                expected=result['predicted_satisfaction']
                self.assertAlmostEqual(expected['average_member'],float(sum(values)/len(values)))
                self.assertAlmostEqual(expected['minimum_member'],float(min(values)))
                self.assertAlmostEqual(expected['disparity_range'],float(max(values)-min(values)))
                self.assertEqual(satisfaction(values),expected)
        # Tied numerical scores test sorting, not fabricated user preferences.
        for method in METHODS:
            np.testing.assert_array_equal(aggregate(np.zeros((3,12)),method),np.arange(10))
        with self.assertRaises(ValueError):
            aggregate(np.zeros((3,12)),'adaptive_consensus',ConsensusConfig(average_weight=.9))

    def test_formation_and_recommendation_never_access_heldout_data(self):
        # Path.open blocks any file access, not just particular filenames.
        # The loaded fitted model and training-user IDs are the only inputs.
        with patch('pandas.read_csv',side_effect=AssertionError('Unexpected data read')), \
             patch.object(Path,'open',side_effect=AssertionError('Unexpected file access')):
            bundles=build_recommendations(self.model,self.users,count=2)
        self.assertEqual(len(bundles),8)
        first=bundles[0]
        before=json.dumps(first,sort_keys=True)
        observed_metrics(first,self.lookup)
        observed_metrics(first,{})
        self.assertEqual(json.dumps(first,sort_keys=True),before)
        self.assertFalse(self.report['protocol']['weights_tuned_on_validation'])
        self.assertFalse(self.report['protocol']['test_data_used'])

    def test_independent_group_relevance_and_quality_metrics(self):
        for size in [2,3,4,5]:
            rows=[row for row in self.details if row['size']==size]
            results={method:[] for method in METHODS}
            blocked=0
            evaluable=0
            for row in rows:
                excluded=set().union(*(self.model.histories[u] for u in row['members']))
                positive=[self.lookup[u][0] for u in row['members'] if self.lookup[u][1]>=4]
                relevant=set(positive)-excluded
                blocked+=sum(b in excluded for b in positive)
                evaluable+=bool(relevant)
                self.assertEqual(row['observed']['eligible_relevant_items'],len(relevant))
                for method in METHODS:
                    items=row['recommendations'][method]['items']
                    self.assertFalse(set(items)&excluded)
                    if not relevant:
                        self.assertIsNone(row['observed']['methods'][method]['group_recall_at_10'])
                        continue
                    recall=len(set(items)&relevant)/len(relevant)
                    dcg=sum(1/np.log2(i+2) for i,b in enumerate(items) if b in relevant)
                    ideal=sum(1/np.log2(i+2) for i in range(min(10,len(relevant))))
                    results[method].append((recall,dcg/ideal))
            reported=self.report['results_by_group_size'][str(size)]
            self.assertEqual(reported['groups_evaluable'],evaluable)
            self.assertEqual(reported['blocked_positive_member_holdouts'],blocked)
            for method in METHODS:
                self.assertEqual(len(results[method]),evaluable)
                self.assertAlmostEqual(reported['methods'][method]['group_recall_at_10'],float(np.mean([v[0] for v in results[method]])))
                self.assertAlmostEqual(reported['methods'][method]['group_ndcg_at_10'],float(np.mean([v[1] for v in results[method]])))

    def test_observed_proxy_is_conditional_and_missing_is_unknown(self):
        blocked_seen=False
        for row in self.details:
            seen=set().union(*(self.model.histories[u] for u in row['members']))
            members=[u for u in row['members'] if self.lookup[u][1]>=4 and self.lookup[u][0] not in seen]
            blocked_seen|=row['observed']['blocked_positive_member_holdouts']>0
            for method in METHODS:
                proxy=row['observed']['methods'][method]['observed_positive_member_hit_proxy']
                if not members:
                    self.assertIsNone(proxy)
                else:
                    hit=[int(self.lookup[u][0] in row['recommendations'][method]['items']) for u in members]
                    self.assertEqual(proxy,satisfaction(hit))
        self.assertTrue(blocked_seen)

    def test_recommendation_reproduction_and_provenance(self):
        with threadpool_limits(limits=1):
            for size in [2,3,4,5]:
                saved=next(row for row in self.details if row['size']==size)
                rebuilt=recommend_group(self.model,saved['members'])
                self.assertEqual(rebuilt['methods'],saved['recommendations'])
        for name,digest in self.report['protocol']['inputs_sha256'].items():
            self.assertEqual(checksum(ROOT/name),digest)


if __name__=='__main__':
    unittest.main()
