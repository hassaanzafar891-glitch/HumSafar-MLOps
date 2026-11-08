"""Explicit-rating biased MF: training-only fitting and validation-only tuning."""
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

MODELS = ROOT / 'models/hawaii_matrix_factorization'


@dataclass(frozen=True)
class Config:
    factors: int = 8
    regularization: float = .01
    learning_rate: float = .005
    epochs: int = 20
    batch_size: int = 4096
    seed: int = 2026

    def validate(self):
        for name in ['factors','epochs','batch_size']:
            value = getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,int) or value<1:
                raise ValueError(f'{name} must be a positive integer')
        if not np.isfinite(self.regularization) or self.regularization<0:
            raise ValueError('regularization must be nonnegative and finite')
        if not np.isfinite(self.learning_rate) or self.learning_rate<=0:
            raise ValueError('learning_rate must be positive and finite')


class MatrixFactorization:
    def __init__(self, users, items, mean, user_factors, item_factors,
                 user_bias, item_bias, histories, config):
        self.users, self.items = list(users), list(items)
        self.user_lookup = {u:i for i,u in enumerate(users)}
        self.item_lookup = {b:i for i,b in enumerate(items)}
        self.mean = float(mean)
        self.user_factors, self.item_factors = user_factors, item_factors
        self.user_bias, self.item_bias = user_bias, item_bias
        self.histories = {u:set(items) for u,items in histories.items()}
        self.config = config

    @classmethod
    def fit(cls, train, catalog, config=Config()):
        """Fit solely from train; validation is deliberately not accepted here."""
        validate(train)
        config.validate()
        items = sorted(catalog)
        if not items or len(items)!=len(set(items)) or any(not isinstance(b,str) or not b for b in items):
            raise ValueError('Catalog must contain unique nonblank string IDs')
        users = sorted(train.user_id.unique())
        ui, bi = {u:i for i,u in enumerate(users)}, {b:i for i,b in enumerate(items)}
        if not set(train.gmap_id).issubset(bi):
            raise ValueError('Training items absent from catalog')
        u = torch.tensor(train.user_id.map(ui).to_numpy(),dtype=torch.long)
        b = torch.tensor(train.gmap_id.map(bi).to_numpy(),dtype=torch.long)
        r = torch.tensor(pd.to_numeric(train.rating).to_numpy(),dtype=torch.float32)
        mean = float(pd.to_numeric(train.rating).mean())
        # CPU, one thread, explicit generator and shuffles: no GPU or external model.
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        generator = torch.Generator(device='cpu').manual_seed(config.seed)
        p = torch.nn.Parameter(torch.randn(len(users),config.factors,generator=generator)*.05)
        q = torch.nn.Parameter(torch.randn(len(items),config.factors,generator=generator)*.05)
        ub = torch.nn.Parameter(torch.zeros(len(users)))
        ib = torch.nn.Parameter(torch.zeros(len(items)))
        with torch.no_grad():
            observed_items = set(train.gmap_id)
            inactive = np.array([item not in observed_items for item in items])
            q[inactive] = 0
        optimizer = torch.optim.Adam([p,q,ub,ib],lr=config.learning_rate)
        random = np.random.default_rng(config.seed)
        losses = []
        for epoch in range(config.epochs):
            order = random.permutation(len(train))
            loss_total = 0.0
            for start in range(0,len(order),config.batch_size):
                index = order[start:start+config.batch_size]
                pu, qi, bu, ci = p[u[index]], q[b[index]], ub[u[index]], ib[b[index]]
                predicted = mean+bu+ci+(pu*qi).sum(dim=1)
                penalty = (pu.square().sum(dim=1)+qi.square().sum(dim=1)+bu.square()+ci.square()).mean()
                loss = (predicted-r[index]).square().mean()+config.regularization*penalty
                if not torch.isfinite(loss):
                    raise ValueError('Nonfinite training objective')
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
                loss_total += loss.item()*len(index)
            losses.append({'epoch':epoch+1,'mean_batch_objective':loss_total/len(train)})
        histories = {user:set(group.gmap_id) for user,group in train.groupby('user_id',sort=True)}
        model = cls(users,items,mean,p.detach().numpy().copy(),q.detach().numpy().copy(),
                    ub.detach().numpy().copy(),ib.detach().numpy().copy(),histories,config)
        return model,losses

    def predict(self, users, items, clip=True):
        users, items = list(users),list(items)
        if len(users)!=len(items):
            raise ValueError('Users and items must have matching lengths')
        result = np.full(len(users),self.mean,dtype=np.float64)
        # Unknown entities use known-side bias, or global mean if both unknown.
        u = np.array([self.user_lookup.get(user,-1) for user in users])
        b = np.array([self.item_lookup.get(item,-1) for item in items])
        ku, kb = u>=0,b>=0
        result[ku] += self.user_bias[u[ku]]
        result[kb] += self.item_bias[b[kb]]
        known = ku&kb
        result[known] += np.einsum('ij,ij->i',self.user_factors[u[known]].astype(np.float64),self.item_factors[b[known]].astype(np.float64))
        return np.clip(result,1,5) if clip else result

    def score_catalog(self, users):
        indices = [self.user_lookup[u] for u in users]
        # Dot products in float64 keep batched scores/pair predictions consistent.
        return (self.user_factors[indices].astype(np.float64) @ self.item_factors.astype(np.float64).T
                +self.mean+self.user_bias[indices,None]+self.item_bias[None,:])

    def recommend(self, user, k=10):
        if user not in self.user_lookup:
            raise ValueError('Ranking requires a known training user')
        if isinstance(k,bool) or not isinstance(k,int) or k<=0:
            raise ValueError('k must be a positive integer')
        scores = self.score_catalog([user])[0]
        for item in self.histories[user]:
            scores[self.item_lookup[item]] = -np.inf
        indices = np.argsort(-scores,kind='stable')
        return [self.items[i] for i in indices if np.isfinite(scores[i])][:k]

    def save(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(directory/'model.npz',user_factors=self.user_factors,item_factors=self.item_factors,
                            user_bias=self.user_bias,item_bias=self.item_bias)
        metadata = {'format_version':1,'users':self.users,'items':self.items,'global_mean':self.mean,
                    'histories':{u:sorted(v) for u,v in self.histories.items()},'config':asdict(self.config),
                    'weights_sha256':checksum(directory/'model.npz')}
        (directory/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')

    @classmethod
    def load(cls, directory=MODELS):
        directory = Path(directory)
        meta = json.loads((directory/'metadata.json').read_text(encoding='utf-8'))
        if meta['format_version']!=1 or checksum(directory/'model.npz')!=meta['weights_sha256']:
            raise ValueError('Model format or weights checksum mismatch')
        with np.load(directory/'model.npz',allow_pickle=False) as weights:
            arrays = {key:weights[key].copy() for key in weights.files}
        config = Config(**meta['config'])
        expected = {'user_factors':(len(meta['users']),config.factors),'item_factors':(len(meta['items']),config.factors),
                    'user_bias':(len(meta['users']),),'item_bias':(len(meta['items']),)}
        if any(arrays[key].shape!=shape or not np.isfinite(arrays[key]).all() for key,shape in expected.items()):
            raise ValueError('Invalid factor shapes or values')
        return cls(meta['users'],meta['items'],meta['global_mean'],histories=meta['histories'],config=config,**arrays)


def rating_metrics(model, validation):
    actual = pd.to_numeric(validation.rating).to_numpy(dtype=float)
    predictions = model.predict(validation.user_id,validation.gmap_id)
    residual = predictions-actual
    return {'mae':float(np.mean(np.abs(residual))),'rmse':float(np.sqrt(np.mean(residual**2)))}


def ranking_metrics(model, validation, batch_size=256):
    relevant = validation.loc[pd.to_numeric(validation.rating)>=4]
    if validation.user_id.duplicated().any():
        raise ValueError('Requires exactly one validation row per user')
    if any(u not in model.histories or b not in model.item_lookup or b in model.histories[u]
           for u,b in validation[['user_id','gmap_id']].itertuples(index=False,name=None)):
        raise ValueError('Validation coverage or train-overlap issue')
    hits, gains = 0,0.0
    for start in range(0,len(relevant),batch_size):
        rows = relevant.iloc[start:start+batch_size]
        scores = model.score_catalog(rows.user_id.tolist())
        for offset,row in enumerate(rows.itertuples(index=False)):
            seen = [model.item_lookup[item] for item in model.histories[row.user_id]]
            scores[offset,seen] = -np.inf
        top = np.argsort(-scores,axis=1,kind='stable')[:,:10]
        target = rows.gmap_id.map(model.item_lookup).to_numpy()
        matches = top==target[:,None]
        hits += int(matches.sum())
        gains += float((matches/np.log2(np.arange(10)+2)).sum())
    n = len(relevant)
    return {'recall_at_10':hits/n if n else None,'ndcg_at_10':gains/n if n else None,
            'eligible_users':n,'hit_users':hits,'excluded_no_relevant_holdout':len(validation)-n,
            'catalog_size':len(model.items),'relevance_threshold':4,
            'candidate_rule':'All catalog attractions except this user training history, no negative sampling.',
            'tie_break':'Raw predicted score descending then original gmap_id ascending; no score clipping for ranking.'}


def run(data_dir=DATA, model_dir=MODELS):
    data_dir,model_dir = Path(data_dir),Path(model_dir)
    allowed = ['train.csv','validation.csv','attraction_mapping.csv','baseline_validation_metrics.json']
    paths = {name:data_dir/name for name in allowed}
    provenance = {name:checksum(path) for name,path in paths.items()}
    train,validation = read_interactions(paths['train.csv']),read_interactions(paths['validation.csv'])
    catalog = pd.read_csv(paths['attraction_mapping.csv'],dtype={'gmap_id':str},usecols=['gmap_id']).gmap_id.tolist()
    baseline = json.loads(paths['baseline_validation_metrics.json'].read_text(encoding='utf-8'))
    for name in ['train.csv','validation.csv','attraction_mapping.csv']:
        if provenance[name]!=baseline['training']['inputs_sha256'][name]:
            raise ValueError('Inputs differ from Step 21 baseline provenance')
    grid = [Config(factors=d,regularization=reg,learning_rate=lr)
            for d,reg,lr in itertools.product([8,16],[.01,.1],[.005,.02])]
    trials,best,best_key = [],None,None
    all_started = time.perf_counter()
    with threadpool_limits(limits=1):
        for index,config in enumerate(grid):
            started = time.perf_counter()
            model,history = MatrixFactorization.fit(train,catalog,config)
            elapsed = time.perf_counter()-started
            metrics = rating_metrics(model,validation)
            trials.append({'trial':index+1,'config':asdict(config),'training_seconds':elapsed,
                           'validation':metrics,'training_objectives':history})
            key = (metrics['rmse'],index)
            if best_key is None or key<best_key:
                best,best_key = model,key
            print(f"Trial {index+1}/8: {asdict(config)} MAE={metrics['mae']:.6f} RMSE={metrics['rmse']:.6f} ({elapsed:.1f}s)",flush=True)
        training_search_seconds = sum(t['training_seconds'] for t in trials)
        best_rating = rating_metrics(best,validation)
        best_ranking = ranking_metrics(best,validation)
    previous = baseline['popularity_ranking']
    if best_ranking['eligible_users']!=previous['users_with_relevant_holdout'] or len(catalog)!=previous['complete_catalog_size']:
        raise ValueError('Ranking population/catalog differs from Step 21')
    if provenance!={name:checksum(path) for name,path in paths.items()}:
        raise RuntimeError('Input data changed during execution')
    model_dir.mkdir(parents=True,exist_ok=True)
    best.save(model_dir)
    selected = trials[best_key[1]]
    limitations = [
        'Selection uses minimum final-epoch validation RMSE across eight prespecified configurations, not ranking metrics. Same validation set is used for selection and reporting, so scores are selection-conditioned; no untouched test estimate exists yet.',
        'Only train.csv fits factors, biases, global mean and histories. Validation never enters gradient updates. No refit on train+validation occurs.',
        'The complete retrospective 5-core catalog is used; full-graph selection favors active users/popular attractions and uses future graph membership.',
        'One validation interaction per user; ranking macro-averages only ratings>=4, matching Step 21. Other items are unknown, not confirmed dislikes. No sampled negatives.',
        'Original per-user splits contain timestamp ties and cross-user temporal overlap; they are not a strict globally chronological prospective evaluation.',
        'Rating predictions are clipped to [1,5]; ranking uses unbounded raw scores to avoid introducing clipping ties. Neither score is a probability.',
        'Small CPU search and one seed do not establish the best attainable MF performance. No international generalization or group fairness performance is established.',
    ]
    config_report = {'selected_config':asdict(best.config),'selection_rule':'Lowest validation RMSE after exactly 20 epochs; exact RMSE ties resolved by grid order.',
                     'search_grid':{'factors':[8,16],'regularization':[.01,.1],'learning_rate':[.005,.02]},
                     'optimizer':'Adam, default beta1=.9 beta2=.999 eps=1e-8; no optimizer weight decay.',
                     'objective':'Mean batch squared error + lambda * mean(||p_u||^2 + ||q_i||^2 + b_u^2 + b_i^2). Regularization is observation-frequency-weighted; global mean is fixed from training.',
                     'initialization':'Factors independent Normal(0,.05), biases zero, fixed training global mean.',
                     'cpu_threads':1,'torch_deterministic_algorithms':True,
                     'software':{'torch':torch.__version__,'numpy':np.__version__,'pandas':pd.__version__},
                     'inputs_sha256':provenance,'test_data_used':False,'limitations':limitations}
    (model_dir/'config.json').write_text(json.dumps(config_report,indent=2)+'\n',encoding='utf-8')
    comparison = {
        'mae':{'matrix_factorization':best_rating['mae'],'item_mean':baseline['rating_prediction']['item_mean']['mae']},
        'rmse':{'matrix_factorization':best_rating['rmse'],'item_mean':baseline['rating_prediction']['item_mean']['rmse']},
        'recall_at_10':{'matrix_factorization':best_ranking['recall_at_10'],'popularity':previous['recall_at_10']},
        'ndcg_at_10':{'matrix_factorization':best_ranking['ndcg_at_10'],'popularity':previous['ndcg_at_10']},
    }
    for name,values in comparison.items():
        reference = values['item_mean' if name in ['mae','rmse'] else 'popularity']
        values['mf_minus_baseline'] = values['matrix_factorization']-reference
        values['mf_better_on_validation'] = values['mf_minus_baseline']<0 if name in ['mae','rmse'] else values['mf_minus_baseline']>0
    result = {'evaluation_split':'validation','rating_prediction':best_rating,'ranking':best_ranking,
              'selected_config':asdict(best.config),'training_rows':len(train),'validation_rows':len(validation),
              'search_training_seconds':training_search_seconds,'selected_model_training_seconds':selected['training_seconds'],
              'search_and_evaluation_seconds':time.perf_counter()-all_started,'comparison':comparison,
              'inputs_sha256':provenance,'test_data_used':False,'limitations':limitations}
    (data_dir/'matrix_factorization_validation_metrics.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (data_dir/'matrix_factorization_search.json').write_text(json.dumps({'selection_rule':config_report['selection_rule'],'trials':trials,'selected_trial':selected['trial']},indent=2)+'\n',encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(run(),indent=2))


if __name__=='__main__':
    main()
