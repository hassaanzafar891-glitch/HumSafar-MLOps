"""Data-free monitoring, redaction, accounting and existing-auth regression tests."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import logging
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.config import Settings
from backend.api.monitoring import Metrics, SafeJSONFormatter, approaches_from_payload
from backend.catalog import Destination
from backend.recommendation_service import RecommendationService

ROOT = Path(__file__).resolve().parents[2]


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        rows = [Destination.from_dict(row) for row in json.loads(
            (ROOT/'tests/fixtures/catalog_public.json').read_text(encoding='utf-8'))]
        self.service = RecommendationService(rows)
        self.settings = Settings('sqlite:///'+(Path(self.temp.name)/'monitor.db').as_posix(), secrets.token_urlsafe(48))
        self.app = create_app(self.settings, self.service)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def actor(self):
        password = secrets.token_urlsafe(24)
        r = self.client.post('/auth/register', json={'email': 'monitor@example.com', 'display_name': 'Monitoring fixture', 'password': password})
        self.assertEqual(r.status_code, 201)
        r = self.client.post('/auth/login', data={'username': 'monitor@example.com', 'password': password})
        self.assertEqual(r.status_code, 200)
        return {'Authorization': 'Bearer '+r.json()['access_token']}

    def test_metrics_require_existing_auth_and_respect_logout(self):
        self.assertEqual(self.client.get('/metrics').status_code, 401)
        header = self.actor()
        response = self.client.get('/metrics', headers=header)
        self.assertEqual(response.status_code, 200)
        self.assertIn('version=0.0.4', response.headers['content-type'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn('humsafar_http_errors_total{method="GET",route="/metrics",status="401"} 1', response.text)
        self.assertEqual(self.client.post('/auth/logout', headers=header).status_code, 204)
        self.assertEqual(self.client.get('/metrics', headers=header).status_code, 401)

    def test_route_templates_and_logs_do_not_record_sensitive_request_data(self):
        header = self.actor()
        marker = secrets.token_hex(20)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(SafeJSONFormatter())
        logger = logging.getLogger('humsafar.requests')
        logger.addHandler(handler)
        try:
            self.client.get('/unknown-'+marker+'?password='+marker, headers=header)
            self.client.get('/groups/'+marker, headers=header)
            self.client.post('/auth/login', data={'username': marker, 'password': marker})
        finally:
            logger.removeHandler(handler)
        exported = self.app.state.metrics.render()
        self.assertNotIn(marker, exported+stream.getvalue())
        self.assertNotIn(header['Authorization'], exported+stream.getvalue())
        self.assertNotIn(header['Authorization'].removeprefix('Bearer '), exported+stream.getvalue())
        self.assertIn('route="__unmatched__"', exported)
        self.assertIn('route="/groups/{group_id}"', exported)
        for line in stream.getvalue().splitlines():
            self.assertEqual(json.loads(line)['event'], 'http_request')

    def test_recommendation_success_failure_and_observed_approach(self):
        header = self.actor()
        created = self.client.post('/groups', headers=header, json={'name': 'Monitoring fixture'}).json()
        group = created['group']['id']
        self.client.put(f'/groups/{group}/preferences/me', headers=header, json={'interests': ['Mountainous']})
        path = f'/groups/{group}/recommendations/individual'
        body = {'scope': 'catalog', 'country': 'Pakistan'}
        response = self.client.post(path, headers=header, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['payload']['mode'], 'metadata_preference')
        with patch.object(self.service, 'candidates', side_effect=OSError('private exception text')):
            self.assertEqual(self.client.post(path, headers=header, json=body).status_code, 503)
        self.assertEqual(self.client.post(path, json=body).status_code, 401)
        text = self.app.state.metrics.render()
        self.assertIn('humsafar_recommendation_requests_total{kind="individual"} 3', text)
        self.assertIn('humsafar_recommendation_failures_total{kind="individual"} 2', text)
        self.assertIn('humsafar_recommendation_approach_requests_total{approach="metadata_preference",aggregation="individual"} 1', text)
        self.assertIn('humsafar_recommendation_approach_info{approach="metadata_preference"} 1', text)
        self.assertNotIn('private exception', text)

    def test_histogram_thread_safety_and_method_cardinality(self):
        metrics = Metrics()
        def observe(_):
            metrics.observe('GET', '/health', 200, .1)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(observe, range(80)))
        text = metrics.render()
        self.assertIn('humsafar_http_requests_total{method="GET",route="/health",status="200"} 80', text)
        self.assertIn('route="/health",le="0.05"} 0', text)
        self.assertIn('route="/health",le="0.1"} 80', text)
        self.assertIn('route="/health",le="+Inf"} 80', text)
        self.assertIn('humsafar_http_request_duration_seconds_count{method="GET",route="/health"} 80', text)
        self.client.request('UNTRUSTEDMETHOD', '/health')
        self.assertIn('method="OTHER"', self.app.state.metrics.render())
        self.assertNotIn('UNTRUSTEDMETHOD', self.app.state.metrics.render())

    def test_unhandled_error_accounting_and_safe_exception_formatter(self):
        marker = secrets.token_hex(20)
        @self.app.get('/monitoring-test-error')
        def fail():
            raise RuntimeError(marker)
        self.assertEqual(self.client.get('/monitoring-test-error').status_code, 500)
        text = self.app.state.metrics.render()
        self.assertIn('route="/monitoring-test-error",status="500"} 1', text)
        record = logging.LogRecord('uvicorn.error', logging.ERROR, '', 0, marker, (),
                                   (RuntimeError, RuntimeError(marker), None))
        output = SafeJSONFormatter().format(record)
        self.assertNotIn(marker, output+text)
        self.assertEqual(json.loads(output)['event'], 'server_error')

    def test_registry_is_per_app_and_modes_are_finite(self):
        self.client.get('/health')
        another = create_app(self.settings, self.service)
        self.assertNotIn('route="/health"', another.state.metrics.render())
        another.state.engine.dispose()
        self.assertEqual(approaches_from_payload({'member_modes': {'private-user-id': 'metadata_preference',
                                                                'another-id': 'metadata_preference'}}), ['metadata_preference'])
        self.assertEqual(approaches_from_payload({'mode': 'untrusted private mode'}), ['other'])

    def test_container_logging_does_not_use_raw_access_logs(self):
        nginx = (ROOT/'frontend/nginx.conf').read_text()
        self.assertIn('access_log off;', nginx)
        self.assertIn('error_log /dev/null;', nginx)
        config = json.loads((ROOT/'docker/backend/logging.json').read_text())
        self.assertEqual(config['formatters']['safe']['()'], 'backend.api.monitoring.SafeJSONFormatter')
        self.assertEqual(config['root']['handlers'], ['safe'])
        self.assertIn('--no-access-log', (ROOT/'docker/backend/entrypoint.py').read_text())

    def test_prometheus_families_are_grouped_and_samples_unique(self):
        metrics = Metrics()
        metrics.observe('POST', '/groups/{group_id}/recommendations', 201, .1,
                        ['metadata_preference'], 'adaptive_consensus')
        metrics.observe('POST', '/groups/{group_id}/recommendations/individual', 401, .2)
        text = metrics.render()
        self.assertTrue(text.endswith('\n'))
        family = None
        samples = set()
        for line in text.splitlines():
            if line.startswith('# TYPE '):
                family = line.split()[2]
            elif not line.startswith('#'):
                key, number = line.rsplit(' ', 1)
                name = key.split('{')[0]
                self.assertIn(name, {family, family+'_bucket', family+'_count', family+'_sum'})
                self.assertNotIn(key, samples)
                samples.add(key)
                self.assertGreaterEqual(float(number), 0)
