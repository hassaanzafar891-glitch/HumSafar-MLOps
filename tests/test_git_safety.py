"""Ignore-policy fixtures; never initialize Git or read real ML payloads."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import audit_git_safety as audit


class GitSafetyTests(unittest.TestCase):
    def setUp(self):
        location = audit.ROOT / '.local/tmp'
        location.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=location, prefix='git_audit_')
        self.root = Path(self.temp.name)
        (self.root / '.gitignore').write_text((audit.ROOT / '.gitignore').read_text(), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def files(self, paths):
        for relative in paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('', encoding='utf-8')

    def test_payloads_excluded_metadata_and_examples_preserved(self):
        safe = ['.env.example', 'frontend/.env.example', '.dvc/config', 'dvc.yaml', 'dvc.lock',
                '.github/workflows/ci.yml', 'backend/api/app.py', 'tests/test_sample.py',
                'frontend/package-lock.json', 'data/raw/sample.csv.dvc',
                'models/model.npz.dvc', 'models/registry/model_manifest.json',
                'models/example/README.md', 'frontend/public/images/destinations/photo.webp']
        private = ['.env', 'frontend/.env.production', 'frontend/custom.env', '.dvc/config.local',
                   '.dvc/cache/object', '.dvc/tmp/lock', '.local/mlflow/metadata.json',
                   '.venv/pyvenv.cfg', 'frontend/node_modules/package/index.js',
                   'backend/var/humsafar.db', 'another.sqlite3-wal', 'other.sqlite-journal',
                   'mlruns/run/meta.yaml', 'mlartifacts/run/model.bin', 'dvc-remote/data',
                   'data/raw/sample.csv', 'data/processed/sample.json', 'models/model.npz',
                   'models/hf_cache/revision/README.md', 'models/minilm/encoder/README.md',
                   'frontend/dist/index.html', 'frontend/test-results/screenshot.png',
                   'logs/backend.log', 'server.pem', '.aws/credentials', 'backup.joblib']
        self.files(safe + private)
        candidates, _, links = audit.inventory(self.root)
        included = {p.relative_to(self.root).as_posix() for p in candidates}
        self.assertTrue(set(safe) <= included)
        self.assertFalse(set(private) & included)
        self.assertFalse(links)
        self.assertFalse((self.root / '.git').exists())

    def test_nested_ignore_rules_are_applied(self):
        self.files(['frontend/.gitignore', 'frontend/private.txt', 'frontend/keep.txt'])
        (self.root / 'frontend/.gitignore').write_text('*.txt\n!keep.txt\n')
        candidates, _, _ = audit.inventory(self.root)
        names = {p.relative_to(self.root).as_posix() for p in candidates}
        self.assertIn('frontend/keep.txt', names)
        self.assertNotIn('frontend/private.txt', names)

    def test_secret_findings_are_redacted_and_match_local_secret_duplicates(self):
        sample = 'audit-only-fixture-value-123456'
        self.files(['.env', 'example.py'])
        (self.root / '.env').write_text('JWT_SECRET_KEY=' + sample)
        (self.root / 'example.py').write_text('value = "' + sample + '"\nkey = "' + 'AKIA' + 'A' * 16 + '"\n')
        with patch.object(audit, 'ROOT', self.root):
            count, findings = audit.scan([self.root / 'example.py'])
        self.assertEqual(count, 1)
        self.assertEqual({f['rule'] for f in findings}, {'matches_local_environment_secret', 'aws_access_key_id'})
        self.assertNotIn(sample, str(findings))

    def test_inventory_does_not_read_excluded_payloads(self):
        self.files(['data/raw/sample.csv', 'models/model.npz', 'app.sqlite', 'source.py'])
        original = Path.read_text
        def guarded(path, *args, **kwargs):
            if path.name != '.gitignore':
                raise AssertionError('Inventory must not read payload contents')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', guarded):
            candidates, _, _ = audit.inventory(self.root)
        self.assertIn(self.root / 'source.py', candidates)
