"""Verify operator-supplied raw archives; no download, extraction or evaluation."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_suffix('.json')


def verify(root=ROOT, manifest=MANIFEST):
    root = Path(root).resolve()
    specification = json.loads(Path(manifest).read_text(encoding='utf-8'))
    checked = []
    for entry in specification['files']:
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('External input path must stay within the workspace')
        if not path.is_file():
            raise FileNotFoundError(f"Supply the original archive: {entry['path']}; see RAW_INPUTS.md")
        if path.stat().st_size != entry['bytes']:
            raise ValueError(f"External input size mismatch: {entry['path']}")
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != entry['sha256']:
            raise ValueError(f"External input checksum mismatch: {entry['path']}")
        checked.append(entry['path'])
    return {'verified_files': checked, 'downloaded': False, 'extracted': False, 'evaluated': False}


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(verify(), indent=2))
