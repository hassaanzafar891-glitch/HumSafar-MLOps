"""Reference manifest and explicit manual-integration approval records."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

from backend.mlops.definitions import ROOT,H
from backend.train_baselines import checksum

REGISTRY=ROOT/'models/registry'


def create_manifest():
    bpr=json.loads((ROOT/H/'bpr_validation_metrics.json').read_text(encoding='utf-8'))
    mf=json.loads((ROOT/H/'matrix_factorization_validation_metrics.json').read_text(encoding='utf-8'))
    files=['models/hawaii_bpr/model.npz','models/hawaii_bpr/metadata.json','models/hawaii_bpr/config.json']
    manifest={'schema_version':1,'status':'current_approved_reference_not_new_deployment',
        'approval_basis':'User approved completed Step 23/24; no model replacement authorized in Step 28.',
        'objective':'ranking','model':'hawaii_bpr_popularity_hybrid','scope':'google_local_hawaii compatible user/item IDs only',
        'selected_config':bpr['selected_config'],'hybrid_alpha':bpr['hybrid_alpha'],
        'validation':bpr['hybrid'],'test_evaluated':False,
        'artifacts':{path:checksum(ROOT/path) for path in files},
        'dataset_provenance':{k:v for k,v in bpr['inputs_sha256'].items() if k in ['train.csv','validation.csv','attraction_mapping.csv']},
        'rating_prediction_reference':{'model':'biased_matrix_factorization','objective':'explicit_rating',
            'validation':mf['rating_prediction'],'artifact':'models/hawaii_matrix_factorization/model.npz',
            'not_selected_for_ranking':True},
        'promotion_policy':'Candidate metrics never auto-change serving. Review quality, scope, provenance and regressions; signed-off JSON approval must bind exact candidate-file SHA256. Approval records only permit a later explicit manual integration; this service still loads existing paths.'}
    REGISTRY.mkdir(parents=True,exist_ok=True)
    path=REGISTRY/'model_manifest.json'
    path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest


def approve(candidate_path,approval_path,output):
    candidate_path,approval_path=Path(candidate_path),Path(approval_path)
    candidate=json.loads(candidate_path.read_text(encoding='utf-8'))
    approval=json.loads(approval_path.read_text(encoding='utf-8'))
    if (approval.get('approved') is not True or not approval.get('reviewer') or not approval.get('reason')
        or approval.get('candidate_sha256')!=checksum(candidate_path)):
        raise ValueError('Explicit reviewer/reason and exact candidate SHA256 approval required')
    if candidate.get('objective')!='ranking' or candidate.get('test_evaluated') is not False:
        raise ValueError('This gate accepts validation-only ranking candidates; rating objectives cannot silently replace ranking')
    if not isinstance(candidate.get('artifacts'),dict) or not candidate['artifacts']:
        raise ValueError('A candidate requires actual artifact paths and hashes')
    for path,digest in candidate['artifacts'].items():
        resolved=(ROOT/path).resolve()
        if not resolved.is_relative_to(ROOT/'models') or checksum(resolved)!=digest:
            raise ValueError('Candidate artifact path/hash mismatch')
    record={'status':'approved_for_future_manual_integration_only','serving_model_changed':False,
            'candidate_sha256':checksum(candidate_path),'reviewer':approval['reviewer'],'reason':approval['reason'],
            'approved_at':datetime.now(timezone.utc).isoformat()}
    Path(output).write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['manifest','approve'])
    parser.add_argument('--candidate',type=Path)
    parser.add_argument('--approval',type=Path)
    args=parser.parse_args()
    if args.command=='manifest':print(json.dumps(create_manifest(),indent=2))
    else:
        if not args.candidate or not args.approval:parser.error('Explicit --candidate and --approval are required')
        print(json.dumps(approve(args.candidate,args.approval,REGISTRY/'approved_candidate.json'),indent=2))
