"""Simulated-group validation audit; all recommendations precede held-out reads."""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from threadpoolctl import threadpool_limits

from backend.group_consensus import ConsensusConfig, form_groups, protocol, recommend_group, satisfaction
from backend.train_baselines import DATA, ROOT, checksum, read_interactions
from backend.train_bpr import BPR, MODELS as BPR_MODELS

MODELS=ROOT/'models/hawaii_group_consensus'
METHODS=['average','least_misery','adaptive_consensus']


def observed_metrics(bundle, validation_lookup):
    """Observed positive coverage, never imputing missing member ratings."""
    candidates=set(bundle['candidate_ids'])
    positive=[(u,validation_lookup[u][0]) for u in bundle['members']
              if u in validation_lookup and validation_lookup[u][1]>=4]
    relevant_all={item for _,item in positive}
    relevant=relevant_all & candidates
    eligible_members=[u for u,item in positive if item in candidates]
    outcome={'positive_member_holdouts':len(positive),'eligible_positive_member_holdouts':len(eligible_members),
             'blocked_positive_member_holdouts':sum(item not in candidates for _,item in positive),
             'unique_observed_positive_items':len(relevant_all),'eligible_relevant_items':len(relevant),
             'members_missing_validation':sum(u not in validation_lookup for u in bundle['members']),
             'methods':{}}
    for method,ranking in bundle['methods'].items():
        items=ranking['items']
        hits=len(set(items)&relevant)
        dcg=sum(1/np.log2(rank+2) for rank,item in enumerate(items) if item in relevant)
        idcg=sum(1/np.log2(rank+2) for rank in range(min(len(items),len(relevant))))
        # Conditional observed member hit utility: only positive, candidate-eligible
        # held-out items. Other members' satisfaction is unknown, not zero.
        member_hits=[int(validation_lookup[u][0] in items) for u in eligible_members]
        outcome['methods'][method]={
            'group_recall_at_10':hits/len(relevant) if relevant else None,
            'group_ndcg_at_10':float(dcg/idcg) if idcg else None,
            'recall_including_blocked_positive_items':hits/len(relevant_all) if relevant_all else None,
            'observed_positive_member_hit_proxy':satisfaction(member_hits) if member_hits else None,
            'predicted_satisfaction':ranking['predicted_satisfaction']}
    return outcome


def summarize(details):
    summary={}
    for size in [2,3,4,5]:
        rows=[row for row in details if row['size']==size]
        observations=[row['observed'] for row in rows]
        quality=[row for row in observations if row['eligible_relevant_items']>0]
        result={'groups_total':len(rows),'groups_evaluable':len(quality),
                'groups_without_eligible_observed_relevance':len(rows)-len(quality),
                'candidate_count_min':min(row['candidate_count'] for row in rows),
                'candidate_count_mean':float(np.mean([row['candidate_count'] for row in rows])),
                'positive_member_holdouts':sum(row['positive_member_holdouts'] for row in observations),
                'blocked_positive_member_holdouts':sum(row['blocked_positive_member_holdouts'] for row in observations),
                'eligible_relevant_items_mean':float(np.mean([row['eligible_relevant_items'] for row in observations])),
                'groups_with_attraction_positive_for_multiple_members':sum(row['eligible_positive_member_holdouts']>row['eligible_relevant_items'] for row in observations),
                'members_missing_validation':sum(row['members_missing_validation'] for row in observations),'methods':{}}
        for method in METHODS:
            predicted={key:float(np.mean([row['methods'][method]['predicted_satisfaction'][key] for row in observations]))
                       for key in ['average_member','minimum_member','disparity_range']}
            observed={key:float(np.mean([row['methods'][method]['observed_positive_member_hit_proxy'][key] for row in quality])) if quality else None
                      for key in ['average_member','minimum_member','disparity_range']}
            all_positive=[row for row in observations if row['unique_observed_positive_items']>0]
            result['methods'][method]={
                'group_recall_at_10':float(np.mean([row['methods'][method]['group_recall_at_10'] for row in quality])) if quality else None,
                'group_ndcg_at_10':float(np.mean([row['methods'][method]['group_ndcg_at_10'] for row in quality])) if quality else None,
                'recall_including_blocked_positive_items':float(np.mean([row['methods'][method]['recall_including_blocked_positive_items'] for row in all_positive])) if all_positive else None,
                'predicted_satisfaction':predicted,'observed_positive_member_hit_proxy':observed}
        summary[str(size)]=result
    return summary


def build_recommendations(model, training_users, count=500, seed=2026, config=ConsensusConfig()):
    """Separable no-held-out-data phase, suitable for leakage checks."""
    bundles=[]
    with threadpool_limits(limits=1):
        for size in [2,3,4,5]:
            groups=form_groups(training_users,size,count=count,seed=seed)
            for index,members in enumerate(groups):
                bundle=recommend_group(model,members,config)
                bundle.update({'size':size,'group_index':index})
                bundles.append(bundle)
            print(f'Built recommendations for {count} groups of size {size} using training information only.',flush=True)
    return bundles


def run(data_dir=DATA,model_dir=MODELS,count=500,seed=2026):
    data_dir,model_dir=Path(data_dir),Path(model_dir)
    started=time.perf_counter()
    protected=[data_dir/'train.csv',BPR_MODELS/'model.npz',BPR_MODELS/'metadata.json',BPR_MODELS/'config.json']
    provenance={str(path.relative_to(ROOT)):checksum(path) for path in protected}
    train=read_interactions(data_dir/'train.csv')
    model=BPR.load()
    if not np.isclose(model.hybrid_weight,.75):
        raise ValueError('Step 24 requires the selected .75 BPR + .25 popularity hybrid')
    users=sorted(train.user_id.unique())
    if users!=model.users:
        raise ValueError('BPR users differ from training users')
    counts=train.groupby('gmap_id').size().to_dict()
    if not np.array_equal(model.item_counts,np.array([counts.get(item,0) for item in model.items])):
        raise ValueError('Saved popularity does not match training-only counts')
    for user,rows in train.groupby('user_id',sort=False):
        if model.histories[user]!=set(rows.gmap_id):
            raise ValueError('Saved history differs from training-only history')
    config=ConsensusConfig()
    bundles=build_recommendations(model,users,count,seed,config)
    # Only now read validation: it cannot affect formation, normalization, weights
    # or any recommendation. No consensus tuning is performed in this experiment.
    validation_path=data_dir/'validation.csv'
    validation_hash=checksum(validation_path)
    validation=read_interactions(validation_path)
    if validation.user_id.duplicated().any():
        raise ValueError('Requires one validation interaction per user')
    lookup={u:(b,float(r)) for u,b,r in validation[['user_id','gmap_id','rating']].itertuples(index=False,name=None)}
    details=[]
    for bundle in bundles:
        observed=observed_metrics(bundle,lookup)
        details.append({'size':bundle['size'],'group_index':bundle['group_index'],
                        'members':bundle['members'],'candidate_count':len(bundle['candidate_ids']),
                        'recommendations':bundle['methods'],'observed':observed})
    if any(checksum(path)!=provenance[str(path.relative_to(ROOT))] for path in protected) or checksum(validation_path)!=validation_hash:
        raise RuntimeError('An input/model artifact changed during evaluation')
    provenance[str(validation_path.relative_to(ROOT))]=validation_hash
    evaluation_protocol={
        'group_formation':{'sizes':[2,3,4,5],'groups_per_size':count,'seed':seed,
            'rule':'Sort all training user IDs; NumPy default_rng(SeedSequence([seed,size])); uniformly sample distinct members without replacement within a group; reject duplicate member sets within each size. Users may appear in multiple groups. No validation filtering.'},
        'relevance':'Binary union: R_g consists of candidate-eligible attractions with a validation rating >=4 by at least one group member. Missing member-item ratings are unknown; union relevance is not unanimous group preference.',
        'quality':'Macro average over groups with nonempty R_g: Recall@10=|L_g intersect R_g|/|R_g|; NDCG@10=sum 1/log2(rank+1) for relevant listed items divided by ideal DCG for min(10,|R_g|).',
        'blocked_holdouts':'An attraction visited by any member in training is ineligible even if another member rated it positively in validation. Count those blocked holdouts and report secondary recall with all observed positive items in the denominator.',
        'observed_satisfaction_proxy':'For each member with a candidate-eligible positive validation holdout only, utility is 1 if that holdout is listed, else 0. Summarize mean/min/range over this observed subset only. A zero is failure to retrieve that single known positive, not proof of dissatisfaction with other recommendations.',
        'predicted_satisfaction':'Model-based list mean scores per member, summarized for ALL members/groups. This is predicted utility and cannot be interpreted as observed satisfaction or calibrated interpersonal welfare.',
    }
    limitations=[
        'Groups are simulated random sets, not observed friends/trips; user overlap across groups makes group observations dependent. No confidence intervals or statistical significance are claimed.',
        'Each member has only one validation rating. Group relevance is typically a few union-positive items; absence of a positive observation is not negative feedback. Full group agreement or real satisfaction is not observable.',
        'Predicted fairness is computed from the same normalized model scores optimized by consensus, not independent fairness ground truth. Equal numeric normalization does not prove comparable human utilities.',
        'Shared-history exclusions can block observed positive holdouts. The primary candidate-eligible denominator and secondary all-positive denominator are both reported.',
        'Consensus weights are fixed before validation, but the underlying hybrid/BPR were previously tuned on this validation set; these are exploratory validation results.',
        'Existing full-graph 5-core selection favors active users/popular attractions and uses future graph membership. Timestamp ties and cross-user temporal overlap prevent strict global chronology.',
        'This is a transparent sequential deficit-adaptive heuristic, not a proven fairness guarantee or established novel algorithm. No test evaluation, retraining, or international generalization claim is made.',
    ]
    model_dir.mkdir(parents=True,exist_ok=True)
    configuration=dict(protocol(config),evaluation=evaluation_protocol,inputs_sha256=provenance,test_data_used=False)
    (model_dir/'config.json').write_text(json.dumps(configuration,indent=2)+'\n',encoding='utf-8')
    result={'evaluation_split':'validation','results_by_group_size':summarize(details),
            'protocol':configuration,'runtime_seconds':time.perf_counter()-started,'limitations':limitations}
    (data_dir/'group_validation_metrics.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (data_dir/'group_validation_details.json').write_text(json.dumps(details,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    result=run()
    print(json.dumps({'results_by_group_size':result['results_by_group_size'],'runtime_seconds':result['runtime_seconds']},indent=2))


if __name__=='__main__':
    main()
