"""Exercise real local metrics and logging with explicit fixture data, not ML feedback."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '--env-file', '.local/docker.env']
BASE = 'http://localhost:8080/api'


def value(text, name):
    for line in text.splitlines():
        if line.startswith(name+' '):
            return float(line.rsplit(' ', 1)[1])
    return 0.


def main(restart=False):
    session = requests.Session()
    session.trust_env = False
    def call(method, path, expected=200, **kwargs):
        response = session.request(method, BASE+path, timeout=120, **kwargs)
        if response.status_code != expected:
            raise RuntimeError(f'Monitoring fixture {method}: expected {expected}, got {response.status_code}')
        return response
    call('GET', '/metrics', 401)
    marker = secrets.token_hex(16)
    email, password = 'monitor-'+marker+'@example.com', secrets.token_urlsafe(32)
    call('POST', '/auth/register', 201,
         json={'email': email, 'display_name': 'Monitoring verification fixture', 'password': password})
    token = call('POST', '/auth/login', data={'username': email, 'password': password}).json()['access_token']
    headers = {'Authorization': 'Bearer '+token}
    def metrics():
        return call('GET', '/metrics', headers=headers).text
    before = metrics()
    created = call('POST', '/groups', 201, headers=headers,
                   json={'name': 'Monitoring verification fixture'}).json()
    group = created['group']['id']
    invitation = created['invitation_code']
    call('PUT', f'/groups/{group}/preferences/me', headers=headers,
         json={'interests': ['mountains', 'nature'], 'free_text': marker})
    call('GET', '/health')
    call('GET', '/private-monitoring-fixture-'+marker+'?sensitive='+marker, 404)
    call('POST', f'/groups/{group}/recommendations', 409, headers=headers, json={'scope': 'pakistan'})
    body = {'scope': 'pakistan', 'country': 'Pakistan', 'top_k': 5}
    response = call('POST', f'/groups/{group}/recommendations/individual', 201, headers=headers, json=body)
    assert response.json()['payload']['mode'] == 'pakistan_tfidf_content'
    call('POST', f'/groups/{group}/recommendations/individual', 401, json=body)
    after = metrics()
    expected = {
        'humsafar_http_requests_total{method="GET",route="/health",status="200"}': 1,
        'humsafar_http_errors_total{method="GET",route="__unmatched__",status="404"}': 1,
        'humsafar_recommendation_requests_total{kind="group"}': 1,
        'humsafar_recommendation_failures_total{kind="group"}': 1,
        'humsafar_recommendation_requests_total{kind="individual"}': 2,
        'humsafar_recommendation_failures_total{kind="individual"}': 1,
        'humsafar_recommendation_approach_requests_total{approach="pakistan_tfidf_content",aggregation="individual"}': 1,
        'humsafar_http_request_duration_seconds_count{method="POST",route="/groups/{group_id}/recommendations/individual"}': 2,
    }
    for key, amount in expected.items():
        assert value(after, key)-value(before, key) >= amount, 'Counter did not update: '+key
    assert 'humsafar_recommendation_approach_info{approach="pakistan_tfidf_content"} 1' in after
    if restart:
        started = value(after, 'humsafar_monitoring_start_time_seconds')
        subprocess.run(COMPOSE+['restart', 'backend'], cwd=ROOT, capture_output=True, check=True)
        deadline = time.monotonic()+90
        while True:
            try:
                if session.get(BASE+'/health', timeout=3).status_code == 200:
                    break
            except requests.RequestException:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError('Backend health did not recover')
            time.sleep(1)
        reset = metrics()
        assert value(reset, 'humsafar_monitoring_start_time_seconds') > started
        assert value(reset, 'humsafar_recommendation_requests_total{kind="individual"}') == 0
        assert 'humsafar_recommendation_approach_info{approach="not_observed"} 1' in reset
        call('GET', f'/groups/{group}', headers=headers)  # SQLite/auth survive metrics reset.
    logs = subprocess.run(COMPOSE+['logs', '--no-color', 'backend', 'frontend'], cwd=ROOT,
                          check=True, capture_output=True, text=True).stdout
    for private in (marker, email, password, token, group, invitation):
        assert private not in logs+after, 'Sensitive fixture information appeared in telemetry'
    assert '"event":"http_request"' in logs
    print(json.dumps({'metrics_authentication': True, 'counter_and_latency_checks': len(expected),
                      'observed_approach': 'pakistan_tfidf_content', 'http_and_recommendation_errors_counted': True,
                      'sensitive_fixture_data_absent_from_metrics_and_logs': True,
                      'restart_resets_metrics_preserves_database': restart,
                      'test_split_accessed': False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart', action='store_true')
    main(parser.parse_args().restart)
