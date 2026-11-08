"""Data-free container configuration and private provisioning regression tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DockerConfigTests(unittest.TestCase):
    def test_network_and_storage_boundaries(self):
        compose = yaml.safe_load((ROOT/'docker-compose.yml').read_text())
        backend = compose['services']['backend']
        frontend = compose['services']['frontend']
        self.assertNotIn('ports', backend)
        self.assertEqual(backend['networks'], ['api'])
        self.assertTrue(compose['networks']['api']['internal'])
        self.assertTrue(frontend['ports'][0].startswith('127.0.0.1:'))
        self.assertEqual(backend['environment']['DATABASE_URL'], 'sqlite:////state/humsafar.db')
        self.assertIn(':?', backend['environment']['JWT_SECRET_KEY'])
        volumes = {v['target']: v for v in backend['volumes']}
        self.assertTrue(volumes['/opt/humsafar-artifacts']['read_only'])
        self.assertFalse(volumes['/state']['bind']['create_host_path'])
        for service in compose['services'].values():
            self.assertEqual(len(service['tmpfs']), 1)
            self.assertTrue(service['tmpfs'][0].startswith('/tmp:'))
            self.assertIn(',noexec,nosuid,', service['tmpfs'][0])
            self.assertTrue(service['read_only'])
            self.assertEqual(service['cap_drop'], ['ALL'])
            self.assertEqual(service['restart'], 'unless-stopped')

    def test_images_and_proxy_contract(self):
        backend = (ROOT/'docker/backend/Dockerfile').read_text()
        frontend = (ROOT/'frontend/Dockerfile').read_text()
        nginx = (ROOT/'frontend/nginx.conf').read_text()
        self.assertIn('python:3.12-', backend)
        self.assertIn('USER 10001:10001', backend)
        self.assertIn('HEALTHCHECK', backend)
        self.assertNotIn('COPY . ', backend)
        self.assertIn('--network=none --mount=type=bind,from=wheels', backend)
        self.assertIn('--no-index --find-links=/wheels', backend)
        self.assertIn('python -m pip check', backend)
        self.assertIn('--from=build', frontend)
        self.assertIn('USER 101:101', frontend)
        self.assertIn('proxy_pass http://humsafar_api/;', nginx)
        self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;', nginx)
        self.assertNotIn('$proxy_add_x_forwarded_for', nginx)
        self.assertIn('return 307 /api/auth/login;', nginx)
        self.assertIn('try_files $uri $uri/ /index.html;', nginx)

    def test_build_context_allowlists(self):
        for relative in ['.dockerignore', 'frontend/.dockerignore']:
            rules = (ROOT/relative).read_text().splitlines()
            self.assertIn('**', rules)
            for rule in rules:
                if rule.startswith('!'):
                    self.assertFalse(any(term in rule for term in
                        ['.local', '.env', 'node_modules', '.venv', 'data/', 'models/', 'mlflow']))

    def test_provisioning_is_idempotent_and_preserves_sources(self):
        helper = load('docker_prepare_test', 'docker/prepare_local.py')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, relative in enumerate(helper.ARTIFACTS):
                source = root/relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f'Explicit unit-test artifact fixture {index}'.encode())
            before = {p: helper.checksum(root/p) for p in helper.ARTIFACTS}
            first = helper.prepare(root)
            env = (root/'.local/docker.env').read_bytes()
            self.assertEqual(helper.prepare(root), first)
            self.assertEqual((root/'.local/docker.env').read_bytes(), env)
            self.assertEqual(before, {p: helper.checksum(root/p) for p in helper.ARTIFACTS})
            self.assertEqual(list((root/'.local/docker-state').iterdir()), [])
            self.assertEqual(first['verified_artifacts'], 5)
            self.assertNotIn(env.decode().splitlines()[0], json.dumps(first))
            bundle = root/'.local/docker-runtime'
            (bundle/'models/hawaii_bpr/model.npz').write_bytes(b'tampered fixture')
            with self.assertRaises(ValueError):
                helper.verify_bundle(bundle)
            with self.assertRaises(ValueError):
                helper.prepare(root)

    def test_entrypoint_verifies_before_starting_factory(self):
        entry = load('docker_entry_test', 'docker/backend/entrypoint.py')
        with patch.object(entry, 'verify_bundle') as verify, patch.object(entry.os, 'execvp') as execute:
            entry.main()
            verify.assert_called_once_with('/opt/humsafar-artifacts')
            args = execute.call_args.args[1]
            self.assertIn('backend.api.app:create_app', args)
            self.assertIn('--factory', args)
            self.assertEqual(args[args.index('--root-path')+1], '/api')
        with patch.object(entry, 'verify_bundle', side_effect=ValueError('invalid fixture')), patch.object(entry.os, 'execvp') as execute:
            with self.assertRaises(ValueError):
                entry.main()
            execute.assert_not_called()
