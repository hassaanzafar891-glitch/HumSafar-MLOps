"""One-shot frozen Hawaii test evaluation. No fitting, tuning or serving writes.

First run: python -m unittest discover -s tests -p test_final_evaluation.py -v
Then: python -m backend.evaluate_final_test --execute-once
An exclusive ledger prevents an accidental second real scoring attempt.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time
import unittest

import numpy as np
import pandas as pd
import torch
from threadpoolctl import threadpool_limits

from backend.train_baselines import HawaiiBaselines, checksum, validate
from backend.train_matrix_factorization import MatrixFactorization, ranking_metrics
from backend.train_bpr import BPR, evaluate as bpr_metrics
from backend.group_consensus import ConsensusConfig, form_groups, recommend_group
from backend.evaluate_group_consensus import observed_metrics, summarize

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'data/processed/hawaii'
REPORT = DATA/'final_test_evaluation.json'
LEDGER = ROOT/'.local/step30_2_test_evaluation.json'
CONFIG = ConsensusConfig()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def document_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_split(path):
    return pd.read_csv(path, dtype={'user_id': str, 'gmap_id': str}, keep_default_na=False,
                       usecols=['user_id', 'gmap_id', 'rating', 'timestamp_ms'])


def check_splits(train, validation, test):
    """Structural checks only: no scores, relevance metrics or model selection."""
    for name, frame in [('train', train), ('validation', validation), ('test', test)]:
        validate(frame)
        require(frame.rating.isin([1, 2, 3, 4, 5]).all(), name+': invalid rating')
        require(pd.api.types.is_integer_dtype(frame.timestamp_ms) and frame.timestamp_ms.ge(0).all(),
                name+': invalid timestamp')
    users = set(train.user_id)
    for name, frame in [('validation', validation), ('test', test)]:
        require(not frame.user_id.duplicated().any(), name+': multiple heldouts per user')
        require(set(frame.user_id) == users, name+': user coverage mismatch')
        require(set(frame.gmap_id) <= set(train.gmap_id), name+': cold-start attraction')
    require(train.groupby('user_id').size().min() >= 3, 'User lacks minimum training history')
    for a, b in [(train, validation), (train, test), (validation, test)]:
        require(a.merge(b, on=['user_id', 'gmap_id']).empty, 'Cross-split interaction overlap')
    combined = pd.concat([train.assign(part='train'), validation.assign(part='validation'),
                          test.assign(part='test')], ignore_index=True)
    ordered = combined.sort_values(['user_id', 'timestamp_ms', 'gmap_id'], ascending=[True, False, True])
    rank = ordered.groupby('user_id').cumcount()
    require(ordered.loc[rank == 0, 'part'].eq('test').all(), 'Test is not latest under deterministic tie rule')
    require(ordered.loc[rank == 1, 'part'].eq('validation').all(), 'Validation is not second-latest')
    return {'rows': {'train': len(train), 'validation': len(validation), 'test': len(test)},
            'users': len(users), 'catalog_size': train.gmap_id.nunique(),
            'overlap_cold_start_rating_timestamp_checks': 'passed',
            'minimum_train_history': int(train.groupby('user_id').size().min())}


def single_positive_metrics(rankings, holdout):
    """Macro averages over positive heldouts only. Unknown items are not dislikes."""
    relevant = holdout.loc[holdout.rating >= 4]
    hits, gains = 0, 0.
    for row in relevant.itertuples(index=False):
        items = rankings[row.user_id]
        require(len(items) == 10 and len(set(items)) == 10, 'Ranking must contain ten distinct items')
        if row.gmap_id in items:
            hits += 1
            gains += 1/np.log2(items.index(row.gmap_id)+2)
    n = len(relevant)
    return {'recall_at_10': hits/n if n else None, 'ndcg_at_10': float(gains/n) if n else None,
            'eligible_users': n, 'excluded_no_relevant_holdout': len(holdout)-n, 'hit_users': hits}


def check_model_state(model, train, items):
    histories = {u: set(g.gmap_id) for u, g in train.groupby('user_id', sort=True)}
    require(model.histories == histories, 'Saved model histories differ from train only')
    catalog = getattr(model, 'items', getattr(model, 'catalog', None))
    require(catalog == items, 'Saved catalog/order differs from frozen catalog')
    if hasattr(model, 'users'):
        require(model.users == sorted(histories), 'Model user mapping/order mismatch')
    require(min(len(items)-len(h) for h in histories.values()) >= 10, 'Fewer than ten eligible candidates')


def make_group_bundles(model, users, config=CONFIG, count=500, seed=2026):
    """No holdout input; same training-only groups/candidates as audited Step 24."""
    bundles = []
    for size in [2, 3, 4, 5]:
        for index, members in enumerate(form_groups(users, size, count=count, seed=seed)):
            bundle = recommend_group(model, members, config)
            expected = set(model.items)-set().union(*(model.histories[u] for u in members))
            require(bundle['candidate_ids'] == sorted(expected), 'Group candidate exclusion/order mismatch')
            for ranking in bundle['methods'].values():
                require(len(ranking['items']) == 10 and len(set(ranking['items'])) == 10,
                        'Invalid group list length or duplicate')
                require(set(ranking['items']) <= expected, 'Ineligible group recommendation')
            bundle.update(size=size, group_index=index)
            bundles.append(bundle)
    return bundles


def evaluate_frozen(popularity, mf, bpr, test):
    """Only pure frozen scoring functions. The two BPR weights are prespecified."""
    pop_lists = {u: popularity.recommend(u, 10) for u in test.user_id}
    result = {'popularity': single_positive_metrics(pop_lists, test),
              'matrix_factorization': ranking_metrics(mf, test)}
    pure, hybrid = bpr_metrics(bpr, test, alphas=(1., .75))
    result.update(bpr=pure, bpr_popularity_hybrid=hybrid)
    n = int(test.rating.ge(4).sum())
    require(n > 0, 'No eligible positive test users')
    for name, metrics in result.items():
        require(metrics['eligible_users'] == n, name+': denominator mismatch')
        require(metrics['excluded_no_relevant_holdout'] == len(test)-n, name+': exclusion mismatch')
        require(0 <= metrics['ndcg_at_10'] <= metrics['recall_at_10'] <= 1, name+': metric bounds')
        require(np.isclose(metrics['recall_at_10'], metrics['hit_users']/n), name+': hit count mismatch')
    return result


def synthetic_gate():
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'), pattern='test_final_evaluation.py')
    require(suite.countTestCases() >= 7, 'Missing synthetic protocol checks')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    require(result.wasSuccessful(), 'Synthetic protocol checks failed; no real scoring permitted')
    return result.testsRun


def execute_once():
    # This runs BEFORE opening real data/artifacts. The ledger is never reset here.
    tests = synthetic_gate()
    require(not LEDGER.exists() and not REPORT.exists(), 'Final scoring already attempted or report exists; stop')
    started = time.perf_counter()
    protected = [p for p in DATA.iterdir() if p.is_file()]
    for folder in ['hawaii_baselines', 'hawaii_matrix_factorization', 'hawaii_bpr', 'hawaii_group_consensus']:
        protected.extend(p for p in (ROOT/'models'/folder).iterdir() if p.is_file())
    protected.extend([ROOT/'models/registry/model_manifest.json', Path(__file__),
                      ROOT/'tests/test_final_evaluation.py', ROOT/'backend/group_consensus.py',
                      ROOT/'backend/evaluate_group_consensus.py', ROOT/'backend/train_baselines.py',
                      ROOT/'backend/train_bpr.py', ROOT/'backend/train_matrix_factorization.py'])
    before = {str(p.relative_to(ROOT)).replace('\\', '/'): checksum(p) for p in protected}
    audit = load_json(DATA/'audit.json')
    for name in ['train.csv', 'validation.csv', 'test.csv', 'attraction_mapping.csv', 'user_mapping.csv']:
        require(checksum(DATA/name) == audit['generated_files'][name]['sha256'], 'Split/mapping checksum: '+name)
    manifest = load_json(ROOT/'models/registry/model_manifest.json')
    require(manifest['hybrid_alpha'] == .75 and not manifest['test_evaluated'], 'Frozen reference changed')
    for name, digest in manifest['artifacts'].items():
        require(checksum(ROOT/name) == digest, 'Frozen artifact mismatch: '+name)
    group_config = load_json(ROOT/'models/hawaii_group_consensus/config.json')
    require(group_config['config'] == asdict(CONFIG), 'AGC configuration changed')
    require(not group_config['weights_tuned_on_validation'] and not group_config['test_data_used'], 'AGC provenance changed')
    formation = group_config['evaluation']['group_formation']
    require(formation['sizes'] == [2, 3, 4, 5] and formation['groups_per_size'] == 500
            and formation['seed'] == 2026, 'Group formation protocol changed')
    baseline_manifest = load_json(ROOT/'models/hawaii_baselines/manifest.json')
    require(checksum(ROOT/'models/hawaii_baselines/baselines.joblib') == baseline_manifest['artifact_sha256'],
            'Baseline artifact mismatch')
    train, validation = read_split(DATA/'train.csv'), read_split(DATA/'validation.csv')
    items = pd.read_csv(DATA/'attraction_mapping.csv', dtype={'gmap_id': str}, keep_default_na=False).gmap_id.tolist()
    require(items == sorted(train.gmap_id.unique()) and len(items) == 1512, 'Catalog mismatch')
    pop = HawaiiBaselines.load(ROOT/'models/hawaii_baselines/baselines.joblib')
    mf = MatrixFactorization.load(ROOT/'models/hawaii_matrix_factorization')
    bpr = BPR.load(ROOT/'models/hawaii_bpr')
    for model in [pop, mf, bpr]:
        check_model_state(model, train, items)
    require(asdict(bpr.config) == manifest['selected_config'] and bpr.hybrid_weight == .75, 'BPR parameters changed')
    counts = train.groupby('gmap_id').size().to_dict()
    require(pop.item_counts == counts and np.array_equal(bpr.item_counts, [counts[i] for i in items]),
            'Popularity is not training-only')
    with threadpool_limits(limits=1):
        bundles = make_group_bundles(bpr, sorted(train.user_id.unique()))
    previous_groups = load_json(DATA/'group_validation_details.json')
    require([(b['size'], b['group_index'], b['members']) for b in bundles]
            == [(b['size'], b['group_index'], b['members']) for b in previous_groups], 'Audited fixed groups differ')
    group_hash = document_hash([{'size': b['size'], 'index': b['group_index'], 'members': b['members']} for b in bundles])
    # Only now parse test rows for structural checks. No scoring before ALL checks pass.
    test = read_split(DATA/'test.csv')
    split_checks = check_splits(train, validation, test)
    require(split_checks['rows'] == audit['split_counts'] and len(test) == 25908, 'Split counts changed')
    require(test.rating.ge(4).any(), 'No relevant test holdouts')
    require(all(checksum(ROOT/p) == h for p, h in before.items()), 'Input changed during preflight')
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    attempt = {'status': 'started_do_not_rerun', 'started_utc': datetime.now(timezone.utc).isoformat(),
               'report': str(REPORT.relative_to(ROOT)), 'input_hashes': before, 'groups_sha256': group_hash}
    with LEDGER.open('x', encoding='utf-8') as stream:
        json.dump(attempt, stream, indent=2)
    # Never retry this section automatically, including after a partial failure.
    with threadpool_limits(limits=1):
        individual = evaluate_frozen(pop, mf, bpr, test)
        lookup = {u: (item, float(rating)) for u, item, rating in test[['user_id', 'gmap_id', 'rating']].itertuples(index=False, name=None)}
        details = [{'size': b['size'], 'candidate_count': len(b['candidate_ids']),
                    'observed': observed_metrics(b, lookup)} for b in bundles]
        groups = summarize(details)
    require(all(checksum(ROOT/p) == h for p, h in before.items()), 'Input/model changed during scoring; do not rerun')
    report = {'evaluation_split': 'test', 'executed_once': True, 'created_utc': datetime.now(timezone.utc).isoformat(),
              'synthetic_checks_passed': tests, 'split_checks': split_checks, 'individual_ranking': individual,
              'group_results_by_size': groups, 'groups_sha256': group_hash,
              'frozen_bpr_config': asdict(bpr.config), 'hybrid_alpha': .75, 'group_config': asdict(CONFIG),
              'group_formation': formation, 'inputs_and_source_sha256': before,
              'protocol': {'k': 10, 'relevance_threshold': 4, 'catalog_size': 1512,
                           'individual_candidates': 'Full catalog minus complete training history; validation visits remain candidates.',
                           'group_candidates': 'Full catalog minus union of all members training histories.',
                           'tie_break': 'Original attraction ID ascending for exact ties.',
                           'normalization': 'Per-user minmax on training-unseen catalog; group restriction afterward without rescaling.',
                           'individual_denominator': 'Users whose single test rating >=4; other users excluded, not dislikes.',
                           'group_relevance': 'Union of candidate-eligible member test attractions rated >=4; unknown ratings are not dislikes.',
                           'group_denominator': 'Macro average over groups with nonempty eligible relevance; predicted utilities over all groups.',
                           'observed_proxy': 'Mean/min/range of binary hits among members with eligible positive holdouts only.',
                           'predicted_utility': 'Mean normalized model score over list per member; mean/min/range across all members.',
                           'no_selection': 'No fit, tuning, validation evaluation, alpha selection, or automatic model promotion.'},
              'limitations': ['Full-graph 5-core and latest-review deduplication expose future cohort membership and create selection bias.',
                              'Per-user split is not a global temporal cutoff; timestamp ties do not prove strict chronology.',
                              'One heldout item per user and unknown missing ratings limit observed relevance.',
                              'Validation visits remain candidates under the approved train-only exclusion protocol.',
                              'Simulated groups overlap; groups are not independent observations or actual friend groups.',
                              'Predicted fairness uses optimized model scores, not independently observed human satisfaction.',
                              'Union relevance is not unanimous preference; conditional observed proxies omit unobserved members.',
                              'Test results must not trigger new tuning; a future changed model requires a new evaluation plan.',
                              'Hawaii historical-ID benchmark does not establish international or new-application-user personalization.'],
              'software': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__,
                           'torch': torch.__version__},
              'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'runtime_seconds': time.perf_counter()-started, 'protected_inputs_unchanged': True}
    with REPORT.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    attempt.update(status='completed_do_not_rerun', report_sha256=checksum(REPORT))
    LEDGER.write_text(json.dumps(attempt, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'report': str(REPORT.relative_to(ROOT)), 'individual_ranking': individual,
                      'group_results_by_size': groups, 'runtime_seconds': report['runtime_seconds']}, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-once', action='store_true')
    args = parser.parse_args()
    if not args.execute_once:
        parser.error('Use --execute-once only after approval; the ledger blocks reruns.')
    execute_once()
