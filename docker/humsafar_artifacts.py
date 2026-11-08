"""Small explicit serving bundle: never include reviews, splits or experiments."""
import hashlib
import json
from pathlib import Path

ARTIFACTS = {
    'data/processed/international/catalog.jsonl': 'catalog/catalog.jsonl',
    'models/tfidf_baseline.joblib': 'models/tfidf_baseline.joblib',
    'models/hawaii_bpr/model.npz': 'models/hawaii_bpr/model.npz',
    'models/hawaii_bpr/metadata.json': 'models/hawaii_bpr/metadata.json',
    'models/hawaii_bpr/config.json': 'models/hawaii_bpr/config.json',
}

def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def verify_bundle(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format_version') != 1 or set(manifest.get('files', {})) != set(ARTIFACTS.values()):
        raise ValueError('Serving manifest does not match the five-file allowlist')
    for relative, metadata in manifest['files'].items():
        path = (directory/relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError('Missing or unsafe serving artifact: '+relative)
        if path.stat().st_size != metadata['bytes'] or checksum(path) != metadata['sha256']:
            raise ValueError('Serving artifact checksum mismatch: '+relative)
    return manifest
