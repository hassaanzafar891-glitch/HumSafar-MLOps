"""Train-only rating/popularity baselines; validation only, never test data."""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/processed/hawaii'
MODELS = ROOT / 'models/hawaii_baselines'


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_interactions(path):
    frame = pd.read_csv(path, dtype={'user_id': str, 'gmap_id': str},
                        usecols=['user_id', 'gmap_id', 'rating'], keep_default_na=False)
    validate(frame)
    return frame


def validate(frame):
    if frame.empty or not {'user_id','gmap_id','rating'}.issubset(frame.columns):
        raise ValueError('Nonempty user_id/gmap_id/rating data required')
    for column in ['user_id','gmap_id']:
        if not frame[column].map(lambda value: isinstance(value,str) and bool(value.strip())).all():
            raise ValueError('Original IDs must be nonblank strings')
    ratings = pd.to_numeric(frame['rating'], errors='coerce').to_numpy(dtype=float)
    if not (np.isfinite(ratings).all() and ((ratings>=1)&(ratings<=5)).all()):
        raise ValueError('Ratings must be finite and in [1,5]')
    if frame.duplicated(['user_id','gmap_id']).any():
        raise ValueError('Duplicate user-attraction pairs')


class HawaiiBaselines:
    def __init__(self, global_mean, item_means, item_counts, catalog, histories):
        self.global_mean = float(global_mean)
        self.item_means = item_means
        self.item_counts = item_counts
        self.catalog = sorted(catalog)
        self.histories = histories
        self.popularity_order = sorted(self.catalog,key=lambda item:(-item_counts.get(item,0),item))

    @classmethod
    def fit(cls, train, catalog):
        validate(train)
        catalog = list(catalog)
        if not catalog or len(catalog)!=len(set(catalog)) or any(not isinstance(i,str) or not i.strip() for i in catalog):
            raise ValueError('Catalog IDs must be unique nonblank strings')
        if not set(train['gmap_id']).issubset(catalog):
            raise ValueError('Training attraction absent from catalog')
        numeric = train.assign(rating=pd.to_numeric(train['rating']))
        stats = numeric.groupby('gmap_id')['rating'].agg(['mean','size'])
        histories = {user:set(group['gmap_id']) for user,group in train.groupby('user_id',sort=True)}
        return cls(numeric['rating'].mean(),stats['mean'].to_dict(),
                   {item:int(n) for item,n in stats['size'].items()},catalog,histories)

    def predict_global(self, items):
        return np.full(len(items),self.global_mean,dtype=float)

    def predict_item(self, items):
        return np.array([self.item_means.get(item,self.global_mean) for item in items],dtype=float)

    def recommend(self, user_id, k=10):
        if isinstance(k,bool) or not isinstance(k,int) or k<=0:
            raise ValueError('k must be a positive integer')
        seen = self.histories.get(user_id,set())
        return [item for item in self.popularity_order if item not in seen][:k]

    def save(self, path):
        # Save plain fitted state; no training/validation frame or metadata aggregates.
        joblib.dump({'format_version':1,'global_mean':self.global_mean,
                     'item_means':self.item_means,'item_counts':self.item_counts,
                     'catalog':self.catalog,'histories':{u:sorted(items) for u,items in self.histories.items()}},path,compress=3)

    @classmethod
    def load(cls, path):
        # Load only trusted artifacts (joblib uses pickle).
        state = joblib.load(path)
        if state.pop('format_version')!=1:
            raise ValueError('Unsupported baseline artifact')
        state['histories']={u:set(items) for u,items in state['histories'].items()}
        return cls(**state)


def evaluate(model, validation, k=10):
    validate(validation)
    if validation['user_id'].duplicated().any():
        raise ValueError('This evaluation requires one validation interaction per user')
    if not set(validation['user_id']).issubset(model.histories):
        raise ValueError('Validation has users absent from training')
    if not set(validation['gmap_id']).issubset(model.catalog):
        raise ValueError('Validation has attractions absent from catalog')
    if any(item in model.histories[user] for user,item in validation[['user_id','gmap_id']].itertuples(index=False,name=None)):
        raise ValueError('Validation overlaps user training history')
    truth = pd.to_numeric(validation['rating']).to_numpy(dtype=float)
    predictions = {'global_mean':model.predict_global(validation['gmap_id']),
                   'item_mean':model.predict_item(validation['gmap_id'])}
    rating_metrics = {name:{'mae':float(np.abs(pred-truth).mean()),
                          'rmse':float(np.sqrt(np.mean((pred-truth)**2)))} for name,pred in predictions.items()}
    hits, gains, ranks, eligible_counts = [], [], [], []
    relevant = validation.loc[truth>=4]
    for row in relevant.itertuples(index=False):
        recommendations = model.recommend(row.user_id,k)
        eligible_counts.append(len(model.catalog)-len(model.histories[row.user_id]))
        rank = recommendations.index(row.gmap_id)+1 if row.gmap_id in recommendations else None
        ranks.append(rank)
        hits.append(int(rank is not None))
        gains.append(1/np.log2(rank+1) if rank is not None else 0.0)
    n = len(relevant)
    ranking = {'k':k,'relevance_threshold':4,'validation_users_total':len(validation),
               'users_with_relevant_holdout':n,'users_excluded_no_relevant_holdout':len(validation)-n,
               'recall_at_10':float(np.mean(hits)) if n else None,
               'ndcg_at_10':float(np.mean(gains)) if n else None,
               'hit_users':sum(hits), 'complete_catalog_size':len(model.catalog),
               'eligible_candidates_min':min(eligible_counts,default=None),
               'eligible_candidates_max':max(eligible_counts,default=None),
               'candidate_rule':'Complete prepared attraction catalog minus this user training interactions; no negative sampling.',
               'denominator':'Macro average over users whose single validation rating is >=4. Below-threshold users have no relevant held-out item and are excluded, not assigned dislikes.',
               'gain':'Binary relevance; with exactly one relevant holdout IDCG@10=1, NDCG=1/log2(rank+1) for a hit, otherwise zero.',
               'tie_break':'Descending training interaction count, then original gmap_id ascending lexicographic.'}
    return {'rating_prediction':rating_metrics,'popularity_ranking':ranking,
            'validation_rating_rows':len(validation),
            'item_mean_global_fallback_rows':int((~validation['gmap_id'].isin(model.item_means)).sum())}


def run(data_dir=DATA, model_dir=MODELS):
    data_dir, model_dir = Path(data_dir),Path(model_dir)
    # Explicit allowlist of inputs: no test, interactions, audit, or raw metadata read.
    paths = {name:data_dir/name for name in ['train.csv','validation.csv','attraction_mapping.csv']}
    hashes = {name:checksum(path) for name,path in paths.items()}
    train, validation = read_interactions(paths['train.csv']),read_interactions(paths['validation.csv'])
    catalog = pd.read_csv(paths['attraction_mapping.csv'],dtype={'gmap_id':str},usecols=['gmap_id'],keep_default_na=False)['gmap_id'].tolist()
    model = HawaiiBaselines.fit(train,catalog)
    metrics = evaluate(model,validation)
    model_dir.mkdir(parents=True,exist_ok=True)
    artifact = model_dir/'baselines.joblib'
    model.save(artifact)
    stats = pd.DataFrame({'gmap_id':model.catalog,
                          'training_interaction_count':[model.item_counts.get(i,0) for i in model.catalog],
                          'training_mean_rating':[model.item_means.get(i) for i in model.catalog]})
    stats.to_csv(model_dir/'item_statistics.csv',index=False)
    manifest = {'format_version':1,'training_rows':len(train),'training_users':len(model.histories),
                'catalog_attractions':len(catalog),'global_mean_rating':model.global_mean,
                'inputs_sha256':hashes,'artifact_sha256':checksum(artifact),
                'fitting':'Means, counts and user histories derived solely from train.csv; item-mean fallback is training global mean.',
                'test_data_used':False,'catalog_source':'attraction_mapping.csv: prepared 5-core IDs only, no rating averages or review counts.',
                'artifacts':['baselines.joblib','item_statistics.csv','manifest.json']}
    (model_dir/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    metrics.update({'training':manifest,'evaluation_split':'validation',
                    'limitations':[
                        'Each user has one validation interaction. Recall@10 is hit rate over relevant-holdout users; NDCG@10 measures the discounted rank of that one item. Neither captures all genuinely relevant attractions.',
                        'Unobserved items are unknown, not confirmed dislikes; no sampled negatives are used. Metric misses are not proof of user dislike.',
                        'Popularity is a shared nonpersonalized ordering with per-user training-history exclusion. Scores are counts, not probabilities.',
                        'The prepared full-graph 5-core induces active-user/popular-item selection bias and retrospective catalog eligibility. This stage adds no new filtering.',
                        'Existing user-wise splits have timestamp ties and cross-user temporal overlap; this is not a strict globally chronological evaluation.',
                        'Only validation is evaluated. No test data, full-corpus rating aggregates, metadata review counts, or matrix-factorization models are used.',
                        'Hawaii is the first international HumSafar benchmark; no international generalization or group fairness performance is established.'
                    ]})
    if hashes!={name:checksum(path) for name,path in paths.items()}:
        raise RuntimeError('Input files changed during baseline run')
    metrics_path=data_dir/'baseline_validation_metrics.json'
    metrics_path.write_text(json.dumps(metrics,indent=2)+'\n',encoding='utf-8')
    return metrics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result=run()
    print(json.dumps({k:result[k] for k in ['rating_prediction','popularity_ranking','item_mean_global_fallback_rows']},indent=2))


if __name__=='__main__':
    main()
