"""Inference-only container smoke check; pipe into Compose exec -T backend python -."""
import importlib.metadata
import json
from pathlib import Path
import sys

sys.path.insert(0, '/app/docker')
from humsafar_artifacts import verify_bundle
from backend.catalog import load_catalog
from backend.recommender import DestinationRecommender
from backend.train_bpr import BPR
import torch

bundle = Path('/opt/humsafar-artifacts')
verify_bundle(bundle)
catalog = load_catalog()
tfidf = DestinationRecommender.load()
bpr = BPR.load()
configuration = json.loads((bundle/'models/hawaii_bpr/config.json').read_text())
assert configuration and len(catalog) and len(tfidf.destinations) and len(bpr.items)
assert torch.version.cuda is None
cuda_packages = [d.metadata['Name'] for d in importlib.metadata.distributions()
                 if d.metadata.get('Name', '').lower().startswith(('nvidia-', 'cuda-'))]
assert not cuda_packages
print(json.dumps({'verified_serving_files': 5, 'catalog_records': len(catalog),
                  'tfidf_destinations': len(tfidf.destinations), 'bpr_items': len(bpr.items),
                  'bpr_config_loaded': True, 'torch_version': torch.__version__,
                  'cuda_packages': cuda_packages, 'training_executed': False}, indent=2))
