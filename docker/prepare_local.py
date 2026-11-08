"""Prepare private local runtime copies; never overwrite originals or a secret."""
import json
import os
from pathlib import Path
import secrets
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from humsafar_artifacts import ARTIFACTS, checksum, verify_bundle

ROOT = Path(__file__).resolve().parents[1]

def prepare(root=ROOT):
    root = Path(root).resolve()
    private = root/'.local'
    bundle = private/'docker-runtime'
    files = {}
    for source_name, target_name in ARTIFACTS.items():
        source = root/source_name
        if not source.is_file():
            raise FileNotFoundError('Provision the trusted existing artifact first: '+source_name)
        digest = checksum(source)
        target = bundle/target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if checksum(target) != digest:
                raise ValueError('Refusing to replace an existing serving artifact: '+target_name)
        else:
            with source.open('rb') as reader, target.open('xb') as writer:
                shutil.copyfileobj(reader, writer)
        if checksum(source) != digest or checksum(target) != digest:
            raise RuntimeError('Artifact changed while provisioning: '+source_name)
        files[target_name] = {'bytes': target.stat().st_size, 'sha256': digest}
    manifest = bundle/'manifest.json'
    text = json.dumps({'format_version': 1, 'files': files}, indent=2)+'\n'
    if manifest.exists():
        if manifest.read_text(encoding='utf-8') != text:
            raise ValueError('Refusing to replace a different serving manifest')
    else:
        with manifest.open('x', encoding='utf-8') as writer:
            writer.write(text)
    verify_bundle(bundle)
    state = private/'docker-state'
    state.mkdir(parents=True, exist_ok=True)
    env = private/'docker.env'
    if not env.exists():
        uid = os.getuid() if hasattr(os, 'getuid') and os.getuid() != 0 else 10001
        gid = os.getgid() if hasattr(os, 'getgid') and os.getgid() != 0 else 10001
        descriptor = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as writer:
            writer.write('JWT_SECRET_KEY='+secrets.token_urlsafe(48)+'\n')
            writer.write(f'ACCESS_TOKEN_MINUTES=30\nHUMSAFAR_HTTP_PORT=8080\nHUMSAFAR_UID={uid}\nHUMSAFAR_GID={gid}\n')
    return {'verified_artifacts': len(files), 'bundle': str(bundle), 'sqlite_directory': str(state),
            'private_env_file': str(env), 'original_artifacts_modified': False,
            'existing_secret_rotated': False, 'database_copied_or_reset': False}

if __name__ == '__main__':
    print(json.dumps(prepare(), indent=2))
