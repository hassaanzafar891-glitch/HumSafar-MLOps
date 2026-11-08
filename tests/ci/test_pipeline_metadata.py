"""Data-free declaration and checksum-helper tests; never run pipeline stages."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from backend.mlops import configure
from backend.mlops.definitions import ROOT, PRODUCER_ONLY, pipeline_document, validate_layout
from backend.mlops.external_inputs import verify


class PipelineMetadataTests(unittest.TestCase):
    def test_producer_outputs_are_declared_uncached_and_never_consumed(self):
        document = pipeline_document()
        validate_layout(document)
        outputs = {next(iter(o)): next(iter(o.values())) for o in document['stages']['prepare']['outs']}
        for name in PRODUCER_ONLY:
            self.assertEqual(outputs[name], {'persist': True, 'cache': False})
        for stage in document['stages'].values():
            self.assertFalse(PRODUCER_ONLY.intersection(stage['deps']))

    def test_heldout_consumer_and_cached_holdout_are_rejected(self):
        document = pipeline_document()
        document['stages']['bpr']['deps'].append('data/processed/hawaii/test.csv')
        with self.assertRaisesRegex(ValueError, 'Held-out dependencies'):
            validate_layout(document)
        document = pipeline_document()
        for out in document['stages']['prepare']['outs']:
            if 'data/processed/hawaii/test.csv' in out:
                out['data/processed/hawaii/test.csv']['cache'] = True
        with self.assertRaisesRegex(ValueError, 'uncached'):
            validate_layout(document)

    def test_portable_interpreter_and_relevant_environment_dependencies(self):
        document = pipeline_document()
        self.assertEqual(yaml.safe_load((ROOT/'params.yaml').read_text())['runtime']['python'], 'python')
        for name, stage in document['stages'].items():
            self.assertEqual(stage['cmd'], '${runtime.python} -m backend.mlops.pipeline '+name)
            self.assertEqual(stage['params'], ['runtime.python'])
            self.assertIn('backend/requirements-mlops.txt', stage['deps'])
            self.assertIn('backend/mlops/runtime_versions.json', stage['deps'])
            self.assertEqual('backend/requirements-ml.txt' in stage['deps'], name != 'prepare')
            self.assertEqual('backend/mlops/tracking.py' in stage['deps'], name in {'baselines','mf','bpr','groups'})

    def test_configure_preserves_existing_interpreter_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = 'runtime:\n  python: custom-python\n'
            (root/'params.yaml').write_text(content)
            with patch.object(configure, 'ROOT', root):
                configure.main()
            self.assertEqual((root/'params.yaml').read_text(), content)
            self.assertEqual(yaml.safe_load((root/'dvc.yaml').read_text())['stages'], pipeline_document()['stages'])

    def test_external_input_hashes_missing_files_and_tampering(self):
        # Explicit byte fixtures, not fabricated dataset records.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root/'archive.fixture'
            sample.write_bytes(b'checksum fixture')
            spec = root/'manifest.json'
            spec.write_text(json.dumps({'files':[{'path':sample.name,'bytes':sample.stat().st_size,
                'sha256':hashlib.sha256(sample.read_bytes()).hexdigest()}]}))
            self.assertEqual(verify(root,spec)['verified_files'], [sample.name])
            sample.write_bytes(b'checksum changed')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                verify(root,spec)
            sample.unlink()
            with self.assertRaises(FileNotFoundError):
                verify(root,spec)

    def test_external_input_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory)/'manifest.json'
            spec.write_text(json.dumps({'files':[{'path':'../outside.fixture','bytes':0,'sha256':'unused'}]}))
            with self.assertRaisesRegex(ValueError, 'within the workspace'):
                verify(directory,spec)
