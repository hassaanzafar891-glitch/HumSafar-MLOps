"""CPU BPR and a training-popularity hybrid, tuned on validation only."""
import argparse
from dataclasses import asdict, dataclass
import itertools
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import torch
from threadpoolctl import threadpool_limits

from backend.train_baselines import DATA, ROOT, checksum, read_interactions, validate

MODELS = ROOT/'models/hawaii_bpr'


@dataclass(frozen=True)
class Config:
    factors: int = 16
    regularization: float = .001
    learning_rate: float = .005
    epochs: int = 15
    batch_size: int = 4096
    seed: int = 2026

    def validate(self):
        for name in ['factors','epochs','batch_size']:
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,int) or value<1:
                raise ValueError(f'{name} must be a positive integer')
        if not np.isfinite(self.regularization) or self.regularization<0:
            raise ValueError('Invalid regularization')
        if not np.isfinite(self.learning_rate) or self.learning_rate<=0:
            raise ValueError('Invalid learning rate')


class ComparisonSampler:
    """Uniform rejection sampling outside the COMPLETE training history."""
    def __init__(self, histories, users, items):
        item_lookup={item:i for i,item in enumerate(items)}
        self.seen=np.zeros((len(users),len(items)),dtype=bool)
        for index,user in enumerate(users):
            self.seen[index,[item_lookup[b] for b in histories[user]]]=True
        if self.seen.all(axis=1).any():
            raise ValueError('A user has no eligible unobserved comparison items')

    def sample(self, user_indices, rng):
        user_indices=np.asarray(user_indices,dtype=np.int64)
        draws=rng.integers(0,self.seen.shape[1],size=len(user_indices))
        rejected=self.seen[user_indices,draws]
        while rejected.any():
            draws[rejected]=rng.integers(0,self.seen.shape[1],size=int(rejected.sum()))
            rejected=self.seen[user_indices,draws]
        return draws


class BPR:
    def __init__(self, users, items, user_factors, item_factors, item_bias,
                 histories, item_counts, config, hybrid_weight=1.0):
        self.users,self.items=list(users),list(items)
        self.user_lookup={u:i for i,u in enumerate(users)}
        self.item_lookup={b:i for i,b in enumerate(items)}
        self.user_factors,self.item_factors,self.item_bias=user_factors,item_factors,item_bias
        self.histories={u:set(v) for u,v in histories.items()}
        self.item_counts=np.asarray(item_counts,dtype=np.int64)
        self.config,self.hybrid_weight=config,float(hybrid_weight)

    @classmethod
    def fit(cls, train, catalog, config=Config()):
        """No validation argument or validation-driven updates are permitted."""
        validate(train)
        config.validate()
        items=sorted(catalog)
        if not items or len(items)!=len(set(items)) or any(not isinstance(b,str) or not b.strip() for b in items):
            raise ValueError('Catalog requires unique nonblank string IDs')
        if not set(train.gmap_id).issubset(items):
            raise ValueError('Training attraction absent from catalog')
        users=sorted(train.user_id.unique())
        ui,bi={u:i for i,u in enumerate(users)},{b:i for i,b in enumerate(items)}
        histories={u:set(g.gmap_id) for u,g in train.groupby('user_id',sort=True)}
        positives=train.loc[pd.to_numeric(train.rating)>=4]
        if positives.empty:
            raise ValueError('No training ratings >=4')
        u_np=positives.user_id.map(ui).to_numpy(dtype=np.int64)
        i_np=positives.gmap_id.map(bi).to_numpy(dtype=np.int64)
        sampler=ComparisonSampler(histories,users,items)
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        generator=torch.Generator(device='cpu').manual_seed(config.seed)
        p=torch.nn.Parameter(torch.randn(len(users),config.factors,generator=generator)*.05)
        q=torch.nn.Parameter(torch.randn(len(items),config.factors,generator=generator)*.05)
        bias=torch.nn.Parameter(torch.zeros(len(items)))
        active_users=set(u_np.tolist())
        with torch.no_grad():
            p[np.array([i not in active_users for i in range(len(users))])]=0
        optimizer=torch.optim.Adam([p,q,bias],lr=config.learning_rate)
        rng=np.random.default_rng(config.seed)
        objectives=[]
        for epoch in range(config.epochs):
            order=rng.permutation(len(positives))
            comparisons=sampler.sample(u_np,rng)
            epoch_loss=0.0
            for start in range(0,len(order),config.batch_size):
                indices=order[start:start+config.batch_size]
                pu,qi,qj=p[u_np[indices]],q[i_np[indices]],q[comparisons[indices]]
                ib,jb=bias[i_np[indices]],bias[comparisons[indices]]
                difference=(pu*(qi-qj)).sum(dim=1)+ib-jb
                penalty=(pu.square().sum(1)+qi.square().sum(1)+qj.square().sum(1)+ib.square()+jb.square()).mean()
                loss=torch.nn.functional.softplus(-difference).mean()+config.regularization*penalty
                if not torch.isfinite(loss):
                    raise ValueError('Nonfinite BPR objective')
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
                epoch_loss+=loss.item()*len(indices)
            objectives.append({'epoch':epoch+1,'mean_batch_objective':epoch_loss/len(positives)})
        counts=train.groupby('gmap_id').size().to_dict()
        model=cls(users,items,p.detach().numpy().copy(),q.detach().numpy().copy(),bias.detach().numpy().copy(),
                  histories,[counts.get(b,0) for b in items],config)
        return model,{'positive_training_rows':len(positives),'training_users_without_positive':len(users)-len(active_users),
                       'comparison_draws_per_epoch':len(positives),'epoch_objectives':objectives}

    def score_catalog(self, users):
        indices=[self.user_lookup[u] for u in users]
        return self.user_factors[indices].astype(np.float64)@self.item_factors.astype(np.float64).T+self.item_bias[None,:]

    def normalized_components(self, users):
        raw=self.score_catalog(users)
        allowed=np.ones(raw.shape,dtype=bool)
        for index,user in enumerate(users):
            allowed[index,[self.item_lookup[b] for b in self.histories[user]]]=False
        def scale(values):
            low=np.where(allowed,values,np.inf).min(axis=1,keepdims=True)
            high=np.where(allowed,values,-np.inf).max(axis=1,keepdims=True)
            return np.divide(values-low,high-low,out=np.zeros_like(values),where=high>low)
        popularity=np.broadcast_to(np.log1p(self.item_counts).astype(float),raw.shape)
        return scale(raw),scale(popularity),allowed

    def recommend(self, user, k=10, alpha=None):
        if user not in self.user_lookup:
            raise ValueError('Ranking requires a known training user')
        if isinstance(k,bool) or not isinstance(k,int) or k<=0:
            raise ValueError('k must be a positive integer')
        alpha=self.hybrid_weight if alpha is None else alpha
        if not np.isfinite(alpha) or not 0<=alpha<=1:
            raise ValueError('alpha must be in [0,1]')
        bpr,pop,allowed=self.normalized_components([user])
        scores=alpha*bpr[0]+(1-alpha)*pop[0]
        scores[~allowed[0]]=-np.inf
        order=np.argsort(-scores,kind='stable')
        return [self.items[i] for i in order if np.isfinite(scores[i])][:k]

    def save(self, directory):
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(directory/'model.npz',user_factors=self.user_factors,item_factors=self.item_factors,
                            item_bias=self.item_bias,item_counts=self.item_counts)
        metadata={'format_version':1,'users':self.users,'items':self.items,'histories':{u:sorted(v) for u,v in self.histories.items()},
                  'config':asdict(self.config),'hybrid_weight':self.hybrid_weight,'weights_sha256':checksum(directory/'model.npz')}
        (directory/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')

    @classmethod
    def load(cls,directory=MODELS):
        directory=Path(directory)
        metadata=json.loads((directory/'metadata.json').read_text(encoding='utf-8'))
        if metadata['format_version']!=1 or checksum(directory/'model.npz')!=metadata['weights_sha256']:
            raise ValueError('Model format or checksum mismatch')
        with np.load(directory/'model.npz',allow_pickle=False) as weights:
            arrays={key:weights[key].copy() for key in weights.files}
        config=Config(**metadata['config'])
        expected={'user_factors':(len(metadata['users']),config.factors),'item_factors':(len(metadata['items']),config.factors),
                  'item_bias':(len(metadata['items']),),'item_counts':(len(metadata['items']),)}
        if any(arrays[key].shape!=shape or not np.isfinite(arrays[key]).all() for key,shape in expected.items()):
            raise ValueError('Invalid saved arrays')
        return cls(metadata['users'],metadata['items'],histories=metadata['histories'],config=config,
                   hybrid_weight=metadata['hybrid_weight'],**arrays)


def evaluate(model, validation, alphas=(1.0,), batch_size=256):
    validate(validation)
    if validation.user_id.duplicated().any():
        raise ValueError('Requires one validation interaction per user')
    if any(u not in model.histories or b not in model.item_lookup or b in model.histories[u]
           for u,b in validation[['user_id','gmap_id']].itertuples(index=False,name=None)):
        raise ValueError('Validation coverage or training overlap issue')
    if any(not np.isfinite(alpha) or not 0<=alpha<=1 for alpha in alphas):
        raise ValueError('Mixing weights must be in [0,1]')
    relevant=validation.loc[pd.to_numeric(validation.rating)>=4]
    totals={float(alpha):{'hits':0,'gain':0.0} for alpha in alphas}
    for start in range(0,len(relevant),batch_size):
        rows=relevant.iloc[start:start+batch_size]
        bpr,pop,allowed=model.normalized_components(rows.user_id.tolist())
        target=rows.gmap_id.map(model.item_lookup).to_numpy()
        for alpha,values in totals.items():
            scores=alpha*bpr+(1-alpha)*pop
            scores[~allowed]=-np.inf
            top=np.argsort(-scores,axis=1,kind='stable')[:,:10]
            matches=top==target[:,None]
            values['hits']+=int(matches.sum())
            values['gain']+=float((matches/np.log2(np.arange(10)+2)).sum())
    n=len(relevant)
    return [{'alpha':alpha,'recall_at_10':v['hits']/n if n else None,'ndcg_at_10':v['gain']/n if n else None,
             'hit_users':v['hits'],'eligible_users':n,'excluded_no_relevant_holdout':len(validation)-n,
             'catalog_size':len(model.items)} for alpha,v in totals.items()]


def run(data_dir=DATA,model_dir=MODELS):
    data_dir,model_dir=Path(data_dir),Path(model_dir)
    names=['train.csv','validation.csv','attraction_mapping.csv','baseline_validation_metrics.json','matrix_factorization_validation_metrics.json']
    paths={name:data_dir/name for name in names}
    provenance={name:checksum(path) for name,path in paths.items()}
    train,validation=read_interactions(paths['train.csv']),read_interactions(paths['validation.csv'])
    catalog=pd.read_csv(paths['attraction_mapping.csv'],dtype={'gmap_id':str},usecols=['gmap_id']).gmap_id.tolist()
    baseline=json.loads(paths['baseline_validation_metrics.json'].read_text(encoding='utf-8'))
    mf=json.loads(paths['matrix_factorization_validation_metrics.json'].read_text(encoding='utf-8'))
    for name in ['train.csv','validation.csv','attraction_mapping.csv']:
        if provenance[name]!=baseline['training']['inputs_sha256'][name] or provenance[name]!=mf['inputs_sha256'][name]:
            raise ValueError('Inputs differ from prior baseline/MF experiments')
    grid=[Config(factors=f,regularization=r,learning_rate=lr)
          for f,r,lr in itertools.product([16,32],[.001,.01],[.005,.02])]
    trials,best,best_key=[],None,None
    started=time.perf_counter()
    with threadpool_limits(limits=1):
        for index,config in enumerate(grid):
            tick=time.perf_counter()
            model,training=BPR.fit(train,catalog,config)
            training_seconds=time.perf_counter()-tick
            metrics=evaluate(model,validation)[0]
            trials.append({'trial':index+1,'config':asdict(config),'training_seconds':training_seconds,
                           'training':training,'validation':metrics})
            key=(-metrics['ndcg_at_10'],-metrics['recall_at_10'],index)
            if best_key is None or key<best_key:
                best,best_key=model,key
            print(f"Trial {index+1}/8: {asdict(config)} Recall@10={metrics['recall_at_10']:.6f} NDCG@10={metrics['ndcg_at_10']:.6f} ({training_seconds:.1f}s)",flush=True)
        bpr_metrics=trials[best_key[2]]['validation']
        hybrid_trials=evaluate(best,validation,alphas=(0,.25,.5,.75,1))
    # NDCG primary, Recall secondary, lower alpha on exact metric ties.
    hybrid=min(hybrid_trials,key=lambda row:(-row['ndcg_at_10'],-row['recall_at_10'],row['alpha']))
    best.hybrid_weight=hybrid['alpha']
    popularity=baseline['popularity_ranking']
    if (bpr_metrics['eligible_users']!=popularity['users_with_relevant_holdout']
            or bpr_metrics['eligible_users']!=mf['ranking']['eligible_users']
            or len(catalog)!=popularity['complete_catalog_size']):
        raise ValueError('Evaluation population/catalog differs from prior experiments')
    pure_pop=next(row for row in hybrid_trials if row['alpha']==0)
    if not all(np.isclose(pure_pop[key],popularity[key],rtol=0,atol=1e-12) for key in ['recall_at_10','ndcg_at_10']):
        raise ValueError('Hybrid alpha=0 does not reproduce Step 21 popularity')
    if provenance!={name:checksum(path) for name,path in paths.items()}:
        raise RuntimeError('An input changed during training')
    best.save(model_dir)
    limitations=[
        'Training positives are actual train ratings>=4. Comparison items are sampled uniformly only outside COMPLETE train history, including low-rated interactions. They are unobserved items, not verified negative labels.',
        'A held-out item may be sampled as an unknown comparison because only training history is available to the sampler; no validation interaction/label is consulted during fitting.',
        'Both BPR configuration selection and hybrid weight tuning reuse validation, so reported validation metrics are selection-conditioned. Test remains untouched.',
        'Per-user min-max normalization uses eligible catalog items only. Constant components become zero. Hybrid alpha=1 is BPR; alpha=0 is pure popularity, not evidence of personalization.',
        'Full-graph 5-core filtering favors active users/popular attractions and uses future graph membership. Per-user chronology includes timestamp ties and cross-user temporal overlap.',
        'One relevant validation item per eligible user: Recall is hit rate and NDCG discounts its rank. Unobserved attractions remain unknown; full-catalog scoring does not verify dislikes.',
        'Small search, one seed and a Hawaii catalog do not establish international generalization, statistical significance, or group fairness outcomes.',
    ]
    config_report={'selected_config':asdict(best.config),'hybrid_alpha':best.hybrid_weight,
                   'search_grid':{'factors':[16,32],'regularization':[.001,.01],'learning_rate':[.005,.02]},
                   'selection':'Maximum validation NDCG@10; ties by Recall@10 then grid order. Tune alpha only for selected BPR; exact hybrid metric ties prefer lower alpha.',
                   'hybrid_grid':[0,.25,.5,.75,1],
                   'hybrid_formula':'alpha * minmax(BPR raw score) + (1-alpha) * minmax(log1p(train interaction count)); minmax over each user eligible unseen catalog.',
                   'objective':'mean(softplus(-(p_u dot (q_i-q_j)+b_i-b_j))) + lambda*mean(||p_u||^2+||q_i||^2+||q_j||^2+b_i^2+b_j^2).',
                   'sampling':'One uniform unobserved comparison per positive per epoch, with replacement; rejection excludes every training interaction, not just positives.',
                   'optimizer':'Adam default betas/epsilon; no additional weight decay. CPU, deterministic algorithms, one torch/BLAS thread.',
                   'initialization':'Factors Normal(0,.05), item biases zero. Users without training positives have zero factors and use learned item biases.',
                   'software':{'torch':torch.__version__,'numpy':np.__version__,'pandas':pd.__version__},
                   'inputs_sha256':provenance,'test_data_used':False,'limitations':limitations}
    (model_dir/'config.json').write_text(json.dumps(config_report,indent=2)+'\n',encoding='utf-8')
    comparison={name:{key:row[key] for key in ['recall_at_10','ndcg_at_10']} for name,row in
                [('popularity',popularity),('matrix_factorization',mf['ranking']),('bpr',bpr_metrics),('bpr_popularity_hybrid',hybrid)]}
    for name in ['bpr','bpr_popularity_hybrid']:
        comparison[name]['minus_popularity']={key:comparison[name][key]-comparison['popularity'][key] for key in ['recall_at_10','ndcg_at_10']}
    result={'evaluation_split':'validation','selected_config':asdict(best.config),'hybrid_alpha':best.hybrid_weight,
            'bpr':bpr_metrics,'hybrid':hybrid,'comparison':comparison,
            'training_rows':len(train),'positive_training_rows':trials[best_key[2]]['training']['positive_training_rows'],
            'training_users_without_positive':trials[best_key[2]]['training']['training_users_without_positive'],
            'search_training_seconds':sum(t['training_seconds'] for t in trials),
            'selected_model_training_seconds':trials[best_key[2]]['training_seconds'],
            'search_and_evaluation_seconds':time.perf_counter()-started,
            'inputs_sha256':provenance,'test_data_used':False,'limitations':limitations}
    (data_dir/'bpr_validation_metrics.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (data_dir/'bpr_search.json').write_text(json.dumps({'trials':trials,'selected_trial':best_key[2]+1,'hybrid_trials':hybrid_trials,'selected_alpha':best.hybrid_weight},indent=2)+'\n',encoding='utf-8')
    return result


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(run(),indent=2))


if __name__=='__main__':
    main()
