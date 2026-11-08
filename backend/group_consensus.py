"""Training-only group formation and deterministic predicted-score aggregation."""
from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class ConsensusConfig:
    average_weight: float = .5
    minimum_weight: float = .3
    fairness_weight: float = .2
    epsilon: float = .05
    hybrid_alpha: float = .75
    top_k: int = 10

    def validate(self):
        weights=np.array([self.average_weight,self.minimum_weight,self.fairness_weight])
        if not np.isfinite(weights).all() or (weights<0).any() or not np.isclose(weights.sum(),1):
            raise ValueError('Consensus weights must be finite, nonnegative and sum to one')
        if not np.isfinite(self.epsilon) or self.epsilon<=0:
            raise ValueError('epsilon must be positive and finite')
        if not 0<=self.hybrid_alpha<=1:
            raise ValueError('Invalid hybrid alpha')
        if isinstance(self.top_k,bool) or not isinstance(self.top_k,int) or self.top_k<1:
            raise ValueError('top_k must be a positive integer')


def form_groups(training_users, size, count=500, seed=2026):
    """Uniform random unique-member groups, without any held-out information."""
    users=sorted(training_users)
    if len(users)!=len(set(users)) or size<2 or size>len(users) or count<1:
        raise ValueError('Invalid unique training users, group size or count')
    import math
    if count>math.comb(len(users),size):
        raise ValueError('Requested more unique groups than possible')
    rng=np.random.default_rng(np.random.SeedSequence([seed,size]))
    groups,seen=[],set()
    while len(groups)<count:
        indices=tuple(sorted(rng.choice(len(users),size=size,replace=False).tolist()))
        if indices not in seen:
            groups.append([users[i] for i in indices])
            seen.add(indices)
    return groups


def satisfaction(values):
    """Summary of member utilities; callers must label predicted vs observed."""
    values=np.asarray(values,dtype=float)
    if values.ndim!=1 or not len(values) or not np.isfinite(values).all():
        raise ValueError('Finite nonempty member utility vector required')
    return {'average_member':float(values.mean()),'minimum_member':float(values.min()),
            'disparity_range':float(np.ptp(values))}


def consensus_step(scores, cumulative, position, config=ConsensusConfig()):
    """Candidate AGC objective at a one-based list position."""
    if position==1:
        prior=np.zeros(scores.shape[0])
    else:
        prior=cumulative/(position-1)
    weights=(1-prior+config.epsilon)
    weights/=weights.sum()
    projected=(cumulative[:,None]+scores)/position
    return (config.average_weight*(weights@scores)
            +config.minimum_weight*projected.min(axis=0)
            +config.fairness_weight*(1-np.ptp(projected,axis=0)))


def aggregate(scores, method, config=ConsensusConfig()):
    """Columns MUST follow original attraction-ID order for deterministic ties."""
    config.validate()
    scores=np.asarray(scores,dtype=float)
    if scores.ndim!=2 or scores.shape[0]<2 or scores.shape[1]<config.top_k:
        raise ValueError('At least two members and top_k eligible attractions required')
    if not np.isfinite(scores).all() or (scores<0).any() or (scores>1+1e-12).any():
        raise ValueError('Member scores must be finite and within [0,1]')
    if method=='average':
        return np.argsort(-scores.mean(axis=0),kind='stable')[:config.top_k]
    if method=='least_misery':
        return np.argsort(-scores.min(axis=0),kind='stable')[:config.top_k]
    if method!='adaptive_consensus':
        raise ValueError('Unknown aggregation method')
    cumulative=np.zeros(scores.shape[0])
    selected=[]
    available=np.ones(scores.shape[1],dtype=bool)
    for position in range(1,config.top_k+1):
        objective=consensus_step(scores,cumulative,position,config)
        objective[~available]=-np.inf
        best=int(np.argmax(objective))
        selected.append(best)
        available[best]=False
        cumulative+=scores[:,best]
    return np.array(selected,dtype=int)


def recommend_group(model, members, config=ConsensusConfig()):
    """No validation input: only fitted train-state and candidate scores used."""
    config.validate()
    if len(members)<2 or len(members)!=len(set(members)) or any(u not in model.histories for u in members):
        raise ValueError('Group needs distinct known training users')
    bpr,pop,allowed=model.normalized_components(members)
    common=allowed.all(axis=0)
    indices=np.flatnonzero(common)
    if len(indices)<config.top_k:
        raise ValueError('Insufficient common unvisited catalog; do not change protocol silently')
    # Preserve the exact Step 23 individual normalization over each user's own
    # unseen catalog, then restrict to common group candidates without rescaling.
    scores=(config.hybrid_alpha*bpr+(1-config.hybrid_alpha)*pop)[:,indices]
    candidates=[model.items[i] for i in indices]
    methods={}
    for method in ['average','least_misery','adaptive_consensus']:
        selected=aggregate(scores,method,config)
        member_predicted=scores[:,selected].mean(axis=1)
        methods[method]={'items':[candidates[i] for i in selected],
                         'predicted_member_utilities':member_predicted.tolist(),
                         'predicted_satisfaction':satisfaction(member_predicted)}
    return {'members':list(members),'candidate_ids':candidates,'methods':methods}


def protocol(config=ConsensusConfig()):
    return {'config':asdict(config),'weights_tuned_on_validation':False,
            'individual_scores':'x_ui=.75*minmax(raw BPR score)+.25*minmax(log1p(training interaction count)); minmax over each member own unseen catalog, exactly Step 23. Restrict to group-common candidates afterward without rescaling.',
            'adaptive_formula':'At position t: prior_u=0 if t=1 else cumulative_u/(t-1); w_u=(1-prior_u+epsilon)/sum_v(1-prior_v+epsilon); q_ui=(cumulative_u+x_ui)/t; A_t(i)=lambda_avg*sum_u(w_u*x_ui)+lambda_min*min_u(q_ui)+lambda_fair*(1-(max_u(q_ui)-min_u(q_ui))). Select maximum remaining A_t(i).',
            'rationale':'Deficit weights adapt after each selected item to emphasize members with lower predicted list satisfaction. Projected minimum and range explicitly reward the worst-served member and balance. The weighted average preserves overall predicted utility. These are model-score proxies, not verified preferences or satisfaction.',
            'average':'Rank descending mean_u(x_ui).',
            'least_misery':'Rank descending min_u(x_ui).',
            'list_predicted_satisfaction':'For member u, S_u=mean of x_ui across the 10 recommended attractions. Report mean_u S_u, min_u S_u and range_u S_u, then macro-average over groups.',
            'tie_break':'All methods use original gmap_id ascending for exact score ties; candidate columns are in that order.'}
