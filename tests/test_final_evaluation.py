"""Synthetic protocol fixtures ONLY. Never open real splits or load model files.

Kept outside data-free CI because the existing frozen loaders import CPU torch.
Numbers and IDs below are explicit unit-test fixtures, not destination ratings.
"""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backend import evaluate_final_test as driver
from backend.train_baselines import HawaiiBaselines
from backend.train_bpr import BPR, Config as BPRConfig
from backend.train_matrix_factorization import MatrixFactorization, Config as MFConfig
from backend.group_consensus import form_groups, recommend_group
from backend.evaluate_group_consensus import observed_metrics


def fixtures():
    users = [f'fixture-user-{i}' for i in range(5)]
    items = [f'fixture-item-{i:02}' for i in range(30)]
    rows, validation, test = [], [], []
    for index, user in enumerate(users):
        for offset in range(3):
            rows.append((user, items[index*3+offset], 5, offset+1))
        validation.append((user, items[(index*3+3) % 15], 4, 4))
        test.append((user, items[(index*3+4) % 15], 5, 5))
    columns = ['user_id', 'gmap_id', 'rating', 'timestamp_ms']
    train, val, test = [pd.DataFrame(r, columns=columns) for r in [rows, validation, test]]
    history = {u: set(g.gmap_id) for u, g in train.groupby('user_id')}
    bpr = BPR(users, items, np.zeros((5, 2)), np.zeros((30, 2)), np.zeros(30),
              history, np.ones(30, dtype=int), BPRConfig(factors=2), hybrid_weight=.75)
    mf = MatrixFactorization(users, items, 3., np.zeros((5, 2)), np.zeros((30, 2)),
                             np.zeros(5), np.zeros(30), history, MFConfig(factors=2))
    pop = HawaiiBaselines(3., {i: 3. for i in items}, {i: 1 for i in items}, items, history)
    return train, val, test, pop, mf, bpr


class FinalEvaluationProtocolTests(unittest.TestCase):
    def test_valid_split_and_deterministic_timestamp_ties(self):
        train, val, test, *_ = fixtures()
        self.assertEqual(driver.check_splits(train, val, test)['rows'], {'train': 15, 'validation': 5, 'test': 5})
        # A tied holdout timestamp is valid only if original ID ordering agrees.
        val.loc[0, 'timestamp_ms'] = 5
        with self.assertRaisesRegex(ValueError, 'latest'):
            driver.check_splits(train, val, test)
        val.loc[0, 'gmap_id'], test.loc[0, 'gmap_id'] = test.loc[0, 'gmap_id'], val.loc[0, 'gmap_id']
        driver.check_splits(train, val, test)

    def test_overlap_cold_start_invalid_ratings_and_short_history_fail(self):
        for failure in ['overlap', 'cold_start', 'rating', 'history']:
            train, val, test, *_ = fixtures()
            if failure == 'overlap': test.loc[0, 'gmap_id'] = train.loc[0, 'gmap_id']
            if failure == 'cold_start': test.loc[0, 'gmap_id'] = 'never-in-training-fixture'
            if failure == 'rating': test.loc[0, 'rating'] = 6
            if failure == 'history': train = train.drop(index=0)
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                driver.check_splits(train, val, test)

    def test_duplicate_holdouts_and_reversed_time_fail(self):
        train, val, test, *_ = fixtures()
        with self.assertRaises(ValueError):
            driver.check_splits(train, val, pd.concat([test, test.iloc[:1]], ignore_index=True))
        test.loc[0, 'timestamp_ms'] = 0
        with self.assertRaises(ValueError):
            driver.check_splits(train, val, test)

    def test_training_history_exclusion_and_tie_break_for_all_models(self):
        train, _, _, pop, mf, bpr = fixtures()
        for model in [pop, mf, bpr]:
            driver.check_model_state(model, train, bpr.items)
            for user in bpr.users:
                expected = sorted(set(bpr.items)-bpr.histories[user])[:10]
                self.assertEqual(model.recommend(user, 10), expected)
                self.assertEqual(model.recommend(user, 10), expected)
                self.assertFalse(set(expected) & bpr.histories[user])

    def test_threshold_four_denominators_and_rank_discount(self):
        _, _, test, _, _, bpr = fixtures()
        test = test.iloc[:3].copy()
        test['rating'] = [4, 3, 5]
        test['gmap_id'] = [bpr.items[1], bpr.items[0], bpr.items[29]]
        ranking = {u: bpr.items[:10] for u in test.user_id}
        metrics = driver.single_positive_metrics(ranking, test)
        self.assertEqual(metrics['eligible_users'], 2)
        self.assertEqual(metrics['excluded_no_relevant_holdout'], 1)
        self.assertEqual(metrics['hit_users'], 1)
        self.assertEqual(metrics['recall_at_10'], .5)
        self.assertAlmostEqual(metrics['ndcg_at_10'], .5/np.log2(3))
        test['rating'] = 3
        self.assertIsNone(driver.single_positive_metrics(ranking, test)['recall_at_10'])

    def test_all_four_scorers_do_not_fit_tune_or_read_files(self):
        _, _, test, pop, mf, bpr = fixtures()
        with ExitStack() as stack:
            for target in ['backend.train_baselines.HawaiiBaselines.fit', 'backend.train_baselines.run',
                           'backend.train_bpr.BPR.fit', 'backend.train_bpr.run',
                           'backend.train_matrix_factorization.MatrixFactorization.fit',
                           'backend.train_matrix_factorization.run', 'backend.evaluate_group_consensus.run',
                           'pandas.read_csv']:
                stack.enter_context(patch(target, side_effect=AssertionError('Forbidden real IO or fitting')))
            result = driver.evaluate_frozen(pop, mf, bpr, test)
        self.assertEqual(set(result), {'popularity', 'matrix_factorization', 'bpr', 'bpr_popularity_hybrid'})
        self.assertEqual({m['eligible_users'] for m in result.values()}, {5})
        self.assertEqual(result['bpr']['recall_at_10'], result['bpr_popularity_hybrid']['recall_at_10'])

    def test_fixed_groups_candidates_and_identical_methods(self):
        _, _, _, _, _, model = fixtures()
        self.assertEqual(form_groups(model.users, 3, count=5), form_groups(model.users, 3, count=5))
        bundles = driver.make_group_bundles(model, model.users, count=1)
        self.assertEqual([b['size'] for b in bundles], [2, 3, 4, 5])
        for bundle in bundles:
            forbidden = set().union(*(model.histories[u] for u in bundle['members']))
            self.assertEqual(set(bundle['candidate_ids']), set(model.items)-forbidden)
            self.assertEqual(set(bundle['methods']), {'average', 'least_misery', 'adaptive_consensus'})
            for method, ranking in bundle['methods'].items():
                self.assertFalse(forbidden & set(ranking['items']))
                self.assertEqual(ranking['items'], recommend_group(model, bundle['members'])['methods'][method]['items'])

    def test_group_relevance_blocked_holdout_and_observed_subset(self):
        _, _, _, _, _, model = fixtures()
        bundle = recommend_group(model, model.users[:2])
        lookup = {model.users[0]: (model.items[6], 4.), model.users[1]: (model.items[0], 5.)}
        observed = observed_metrics(bundle, lookup)
        self.assertEqual(observed['blocked_positive_member_holdouts'], 1)
        self.assertEqual(observed['eligible_positive_member_holdouts'], 1)
        for metrics in observed['methods'].values():
            self.assertEqual(metrics['group_recall_at_10'], 1.)
            self.assertEqual(metrics['recall_including_blocked_positive_items'], .5)
            self.assertEqual(metrics['observed_positive_member_hit_proxy']['average_member'], 1.)
            self.assertIn('predicted_satisfaction', metrics)
        lookup = {u: (model.items[6], 3.) for u in model.users[:2]}
        for metrics in observed_metrics(bundle, lookup)['methods'].values():
            self.assertIsNone(metrics['group_recall_at_10'])
            self.assertIsNone(metrics['observed_positive_member_hit_proxy'])

    def test_existing_ledger_blocks_before_real_data_access(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder)/'explicit-fixture-ledger.json'
            ledger.write_text('{}', encoding='utf-8')
            with patch.object(driver, 'synthetic_gate', return_value=9), patch.object(driver, 'LEDGER', ledger), \
                 patch.object(driver, 'load_json', side_effect=AssertionError('Real IO prohibited')):
                with self.assertRaisesRegex(ValueError, 'already attempted'):
                    driver.execute_once()
