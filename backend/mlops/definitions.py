"""Pipeline paths; held-out outputs belong only to their preparation producer."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
H='data/processed/hawaii/'
COMMON=['backend/mlops/pipeline.py','backend/mlops/definitions.py',
        'backend/requirements-mlops.txt','backend/mlops/runtime_versions.json']
TRACKED_STAGES={'baselines','mf','bpr','groups'}
PRODUCER_ONLY={H+'test.csv',H+'interactions.csv'}
STAGES={
 'prepare':{'deps':['backend/prepare_hawaii.py','backend/inspect_hawaii.py','data/raw/meta-Hawaii.json.gz','data/raw/review-Hawaii_10.json.gz','data/processed/hawaii_inspection.json','.dvcignore','backend/mlops/external_inputs.json'],
            'outs':[H+x for x in ['train.csv','validation.csv','test.csv','interactions.csv','user_mapping.csv','attraction_mapping.csv','attractions.jsonl','audit.json']]},
 'baselines':{'deps':['backend/train_baselines.py',H+'train.csv',H+'validation.csv',H+'attraction_mapping.csv'],
              'outs':[H+'baseline_validation_metrics.json']+['models/hawaii_baselines/'+x for x in ['baselines.joblib','item_statistics.csv','manifest.json']]},
 'mf':{'deps':['backend/train_matrix_factorization.py','backend/train_baselines.py',H+'train.csv',H+'validation.csv',H+'attraction_mapping.csv',H+'baseline_validation_metrics.json'],
       'outs':[H+x for x in ['matrix_factorization_validation_metrics.json','matrix_factorization_search.json']]+['models/hawaii_matrix_factorization/'+x for x in ['model.npz','metadata.json','config.json']]},
 'bpr':{'deps':['backend/train_bpr.py','backend/train_baselines.py',H+'train.csv',H+'validation.csv',H+'attraction_mapping.csv',H+'baseline_validation_metrics.json',H+'matrix_factorization_validation_metrics.json'],
        'outs':[H+x for x in ['bpr_validation_metrics.json','bpr_search.json']]+['models/hawaii_bpr/'+x for x in ['model.npz','metadata.json','config.json']]},
 'groups':{'deps':['backend/group_consensus.py','backend/evaluate_group_consensus.py','backend/train_bpr.py','backend/train_baselines.py',H+'train.csv',H+'validation.csv']+['models/hawaii_bpr/'+x for x in ['model.npz','metadata.json','config.json']],
           'outs':[H+x for x in ['group_validation_metrics.json','group_validation_details.json']]+['models/hawaii_group_consensus/config.json']},
 'catalog':{'deps':['backend/catalog.py','backend/build_catalog.py','backend/train_baselines.py',H+'attractions.jsonl','models/hawaii_bpr/metadata.json','data/processed/destinations_cleaned.csv','data/raw/corpus-webis-tripad-14.tar.gz','backend/mlops/external_inputs.json'],
            'outs':['data/processed/international/'+x for x in ['catalog.jsonl','coverage.json','coverage_by_country.csv','schema.json']]},
}
SNAPSHOTS=['models/tfidf_baseline.joblib','data/processed/destinations_cleaned.csv','data/processed/hawaii_inspection.json']


def pipeline_document():
    return {'stages':{name:{'cmd':f'${{runtime.python}} -m backend.mlops.pipeline {name}',
            'deps':sorted(set(spec['deps']+COMMON
                +(['backend/requirements-ml.txt'] if name!='prepare' else [])
                +(['backend/mlops/tracking.py'] if name in TRACKED_STAGES else []))),
            'params':['runtime.python'],
            'outs':[{path:dict({'persist':True},**({'cache':False} if path in PRODUCER_ONLY else {}))} for path in spec['outs']]}
            for name,spec in STAGES.items()}}


def validate_layout(document):
    stages=document['stages']; owners={}
    for name,stage in stages.items():
        for entry in stage['outs']:
            path=next(iter(entry))
            if path in owners:raise ValueError('Overlapping stage outputs')
            if Path(path).name in ['test.csv','interactions.csv']:
                if name!='prepare' or path not in PRODUCER_ONLY or entry[path].get('cache') is not False:
                    raise ValueError('Held-out outputs must be uncached, preparation-only artifacts')
            if not entry[path].get('persist'):raise ValueError('Existing artifacts must persist on failed execution')
            owners[path]=name
        for path in stage['deps']:
            if Path(path).name in ['test.csv','interactions.csv']:raise ValueError('Held-out dependencies forbidden')
    graph={name:{owners[d] for d in stage['deps'] if d in owners} for name,stage in stages.items()}
    visited=set();pending=dict(graph)
    while pending:
        ready=[name for name,deps in pending.items() if deps<=visited]
        if not ready:raise ValueError('Pipeline contains a cycle')
        for name in ready:visited.add(name);pending.pop(name)
    return {name:sorted(deps) for name,deps in graph.items()}
