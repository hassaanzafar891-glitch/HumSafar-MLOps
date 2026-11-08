"""Train/validation and saved-artifact checks, deliberately excluding test."""
import json
import math

import pandas as pd
import yaml

from backend.mlops.definitions import ROOT,H,validate_layout
from backend.train_baselines import checksum,read_interactions


def metric_check(metrics,n):
    recall,ndcg=metrics['recall_at_10'],metrics['ndcg_at_10']
    if not all(math.isfinite(x) and 0<=x<=1 for x in [recall,ndcg]) or ndcg>recall+1e-12:
        raise ValueError('Invalid single-positive ranking metric bounds')
    if metrics.get('eligible_users',metrics.get('users_with_relevant_holdout'))!=n:
        raise ValueError('Ranking population mismatch')
    if not math.isclose(recall,metrics['hit_users']/n,abs_tol=1e-12):raise ValueError('Recall/hit inconsistency')


def check():
    train,val=read_interactions(ROOT/H/'train.csv'),read_interactions(ROOT/H/'validation.csv')
    if train.merge(val,on=['user_id','gmap_id']).shape[0]:raise ValueError('Train-validation pair overlap')
    if val.user_id.duplicated().any() or train.groupby('user_id').size().min()<3:
        raise ValueError('Invalid per-user split/history shape')
    if not set(val.user_id)<=set(train.user_id) or not set(val.gmap_id)<=set(train.gmap_id):
        raise ValueError('Unexpected validation cold-start entities')
    audit=json.loads((ROOT/H/'audit.json').read_text(encoding='utf-8'))
    for name in ['train.csv','validation.csv']:
        if checksum(ROOT/H/name)!=audit['generated_files'][name]['sha256']:raise ValueError('Prepared split changed')
    baseline=json.loads((ROOT/H/'baseline_validation_metrics.json').read_text(encoding='utf-8'))
    mf=json.loads((ROOT/H/'matrix_factorization_validation_metrics.json').read_text(encoding='utf-8'))
    bpr=json.loads((ROOT/H/'bpr_validation_metrics.json').read_text(encoding='utf-8'))
    n=int(val.rating.ge(4).sum())
    for metrics in [baseline['popularity_ranking'],mf['ranking'],bpr['bpr'],bpr['hybrid']]:metric_check(metrics,n)
    for folder,weight in [('hawaii_bpr','model.npz'),('hawaii_matrix_factorization','model.npz')]:
        metadata=json.loads((ROOT/'models'/folder/'metadata.json').read_text(encoding='utf-8'))
        if checksum(ROOT/'models'/folder/weight)!=metadata['weights_sha256']:raise ValueError('Model weights changed')
        if set(metadata['items'])!=set(train.gmap_id) or set(metadata['users'])!=set(train.user_id):
            raise ValueError('Model/source identity compatibility mismatch')
    baseline_manifest=json.loads((ROOT/'models/hawaii_baselines/manifest.json').read_text(encoding='utf-8'))
    if checksum(ROOT/'models/hawaii_baselines/baselines.joblib')!=baseline_manifest['artifact_sha256']:
        raise ValueError('Baseline artifact mismatch')
    dag=validate_layout(yaml.safe_load((ROOT/'dvc.yaml').read_text(encoding='utf-8')))
    return {'train_rows':len(train),'validation_rows':len(val),'ranking_eligible_users':n,
            'train_validation_integrity':'passed','model_compatibility':'passed','ranking_consistency':'passed',
            'test_split_accessed':False,'three_way_integrity_not_rechecked':True,'dag':dag}


if __name__=='__main__':print(json.dumps(check(),indent=2))
