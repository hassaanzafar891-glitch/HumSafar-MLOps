"""Local MLflow provenance: imported reports are NEVER newly trained runs."""
import argparse
import json
import math
import os
from pathlib import Path

from backend.mlops.definitions import ROOT,H,STAGES
from backend.train_baselines import checksum


def connect(root=None):
    # Explicit local tracking; do not forward artifacts to an ambient cloud URI.
    location=Path(root) if root else ROOT/'.local/mlflow'
    location.mkdir(parents=True,exist_ok=True)
    os.environ['MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING']='false'
    os.environ['MLFLOW_DISABLE_TELEMETRY']='true'
    os.environ['MLFLOW_DISABLE_AGENT_HINT']='1'
    import mlflow
    mlflow.set_tracking_uri('sqlite:///'+(location/'tracking.db').resolve().as_posix())
    return mlflow,location.resolve()


def flatten(value,prefix=''):
    result={}
    if isinstance(value,dict):
        for key,child in value.items():result.update(flatten(child,f'{prefix}.{key}' if prefix else key))
    elif isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):result[prefix]=float(value)
    return result


def reports(only=None):
    read=lambda name:json.loads((ROOT/H/name).read_text(encoding='utf-8'))
    result=[]
    if only in [None,'baselines']:
        row=read('baseline_validation_metrics.json')
        result.append(('baselines','baseline_validation_metrics.json',{'seed':'not_applicable'}, {'rating':row['rating_prediction'],'ranking':row['popularity_ranking']},'baselines'))
    if only in [None,'mf']:
        row=read('matrix_factorization_validation_metrics.json')
        result.append(('mf','matrix_factorization_validation_metrics.json',row['selected_config'],{'rating':row['rating_prediction'],'ranking':row['ranking'],'historical_reported_training_seconds':row['selected_model_training_seconds']},'mf'))
    if only in [None,'bpr']:
        row=read('bpr_validation_metrics.json')
        result.extend([('bpr','bpr_validation_metrics.json',row['selected_config'],{'ranking':row['bpr'],'historical_reported_training_seconds':row['selected_model_training_seconds']},'bpr'),
            ('hybrid','bpr_validation_metrics.json',dict(row['selected_config'],alpha=row['hybrid_alpha']),{'ranking':row['hybrid']},'bpr')])
    if only in [None,'groups']:
        row=read('group_validation_metrics.json')
        formation=row['protocol']['evaluation']['group_formation']
        params=dict(row['protocol']['config'],group_seed=formation['seed'],groups_per_size=formation['groups_per_size'])
        result.append(('groups','group_validation_metrics.json',params,{'group_sizes':row['results_by_group_size']},'groups'))
    return result


def log_training_history(mlflow,name,stage):
    if stage in ['mf','bpr']:
        search_name='matrix_factorization_search.json' if stage=='mf' else 'bpr_search.json'
        search_path=ROOT/H/search_name
        search=json.loads(search_path.read_text(encoding='utf-8'))
        selected=next(row for row in search['trials'] if row['trial']==search['selected_trial'])
        curve=selected.get('training_objectives') if stage=='mf' else selected['training']['epoch_objectives']
        for entry in curve:
            mlflow.log_metric('training.mean_batch_objective',entry['mean_batch_objective'],step=entry['epoch'])
        mlflow.log_artifact(str(search_path),artifact_path='source_search_report')
        if name=='hybrid':mlflow.set_tag('training_shared_with_bpr','true')
    elif stage=='baselines':
        row=json.loads((ROOT/H/'baseline_validation_metrics.json').read_text(encoding='utf-8'))
        mlflow.log_metric('training.global_mean_rating',row['training']['global_mean_rating'])
    mlflow.set_tag('training_history_imported_or_logged','true')


def track_existing(origin='imported_historical',only=None):
    if origin not in ['imported_historical','executed_pipeline_stage']:raise ValueError('Explicit run origin required')
    mlflow,root=connect()
    experiment=mlflow.get_experiment_by_name('HumSafar local experiments')
    if experiment is None:
        eid=mlflow.create_experiment('HumSafar local experiments',artifact_location=(root/'artifacts').as_uri())
    else:eid=experiment.experiment_id
    client=mlflow.tracking.MlflowClient()
    receipts=[]
    for name,report,params,metrics,stage in reports(only):
        if only and stage!=only:continue
        report_path=ROOT/H/report
        digest=checksum(report_path)
        # Idempotence applies to historical imports only; genuine new executions
        # can have the same score while retaining a distinct provenance record.
        previous=client.search_runs([eid],filter_string=f"tags.origin = '{origin}' AND tags.component = '{name}' AND tags.report_sha256 = '{digest}'") if origin=='imported_historical' else []
        if previous:
            with mlflow.start_run(run_id=previous[0].info.run_id):
                mlflow.log_params(params)
                if previous[0].data.tags.get('training_history_imported_or_logged')!='true':
                    log_training_history(mlflow,name,stage)
            receipts.append({'component':name,'run_id':previous[0].info.run_id,'reused_import':True});continue
        with mlflow.start_run(experiment_id=eid,run_name=f'{name}-{origin}') as run:
            mlflow.set_tags({'origin':origin,'component':name,'report_sha256':digest,
                             'evaluation_split':'validation','test_data_used':'false',
                             'historical_import_is_not_training':str(origin=='imported_historical').lower()})
            mlflow.log_params(params)
            mlflow.log_metrics(flatten(metrics))
            log_training_history(mlflow,name,stage)
            references={path:{'sha256':checksum(ROOT/path),'storage':'private local DVC cache/remote; not copied into MLflow'}
                        for path in STAGES[stage]['outs'] if path.startswith('models/')}
            mlflow.log_dict(references,'model_artifact_references.json')
            mlflow.log_dict({'source_report':str(report_path.relative_to(ROOT)),'sha256':digest,'origin':origin},'report_provenance.json')
            # Public config sidecars are small and contain hashes/objectives, not
            # original user IDs; large weights/histories stay in private DVC.
            config=next((ROOT/path for path in STAGES[stage]['outs'] if path.endswith('/config.json')),None)
            if config:mlflow.log_artifact(str(config),artifact_path='configuration')
            receipts.append({'component':name,'run_id':run.info.run_id,'reused_import':False})
    receipt=root/f'{origin}_receipt.json'
    receipt.write_text(json.dumps(receipts,indent=2)+'\n',encoding='utf-8')
    return receipts


def smoke(root=None):
    mlflow,location=connect(root)
    experiment=mlflow.get_experiment_by_name('HumSafar tracking smoke only')
    eid=experiment.experiment_id if experiment else mlflow.create_experiment('HumSafar tracking smoke only',artifact_location=(location/'smoke-artifacts').as_uri())
    with mlflow.start_run(experiment_id=eid,run_name='tracking-connectivity-smoke') as run:
        mlflow.set_tags({'purpose':'tracking_smoke_test','not_model_training':'true'})
        mlflow.log_param('check','local_tracking_roundtrip')
        mlflow.log_metric('smoke_value',1.0)
        run_id=run.info.run_id
    stored=mlflow.tracking.MlflowClient().get_run(run_id)
    if stored.data.metrics.get('smoke_value')!=1.0:raise RuntimeError('MLflow roundtrip failed')
    return {'run_id':run_id,'purpose':'tracking_smoke_test','verified':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['smoke','import-history'])
    args=parser.parse_args()
    print(json.dumps(smoke() if args.command=='smoke' else track_existing(),indent=2))
