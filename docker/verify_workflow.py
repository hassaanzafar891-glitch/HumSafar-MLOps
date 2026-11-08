"""Explicit local fixture accounts; HTTP workflow through Nginx, never ML feedback.

Run after Compose is healthy. --restart restarts only this Compose project's
services and checks persisted state using the existing tokens.
No passwords, tokens or invitation codes are printed or saved.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import time

import requests

ROOT = Path(__file__).resolve().parents[1]


def run(base='http://localhost:8080', restart=False):
    session = requests.Session()
    session.trust_env = False
    steps = []

    def call(method, path, expected=200, **kwargs):
        response = session.request(method, base+'/api'+path, timeout=120, **kwargs)
        if response.status_code != expected:
            raise RuntimeError(f'{method} {path}: expected {expected}, got {response.status_code}')
        steps.append({'method': method, 'path': path, 'status': response.status_code})
        return response.json()

    page = session.get(base, timeout=20)
    if page.status_code != 200 or '<div id="root">' not in page.text:
        raise RuntimeError('Frontend HTML not served')
    assert call('GET', '/health')['status'] == 'ok'
    marker = secrets.token_hex(6)
    password = secrets.token_urlsafe(32)
    headers = []
    for member in ['owner', 'member']:
        email = f'docker-{member}-{marker}@example.com'
        call('POST', '/auth/register', 201,
             json={'email': email, 'display_name': 'Docker verification '+member, 'password': password})
        token = call('POST', '/auth/login', data={'username': email, 'password': password})
        headers.append({'Authorization': 'Bearer '+token['access_token']})
    owner, member = headers
    created = call('POST', '/groups', 201, headers=owner,
                   json={'name': 'Docker verification fixture '+marker})
    group = created['group']['id']
    call('POST', '/groups/join', headers=member,
         json={'invitation_code': created['invitation_code']})
    for header, interests in zip(headers, [['mountains', 'hiking', 'nature'], ['lakes', 'beautiful scenery']]):
        call('PUT', f'/groups/{group}/preferences/me', headers=header,
             json={'interests': interests, 'preferred_countries': ['Pakistan'],
                   'budget_min': '100', 'budget_max': '500', 'currency': 'USD',
                   'start_date': '2030-06-01', 'end_date': '2030-06-10'})
    rec = call('POST', f'/groups/{group}/recommendations', 201, headers=owner,
               json={'scope': 'pakistan', 'country': 'Pakistan', 'method': 'adaptive_consensus', 'top_k': 5})
    chosen = rec['payload']['results'][0]
    votes_path = f'/groups/{group}/recommendations/{rec["id"]}/votes'
    itinerary_path = f'/groups/{group}/itinerary'
    for header in headers:
        call('PUT', f'/groups/{group}/recommendations/{rec["id"]}/vote', headers=header,
             json={'destination_id': chosen['destination_id']})
    assert call('GET', itinerary_path, headers=member) == [], 'Votes must not create itinerary items'
    totals = call('GET', votes_path, headers=member)
    assert next(row['votes'] for row in totals if row['destination_id'] == chosen['destination_id']) == 2
    planned = call('POST', itinerary_path, 201, headers=owner,
                   json={'recommendation_id': rec['id'], 'destination_id': chosen['destination_id'],
                         'position': 1, 'planned_date': '2030-06-02', 'notes': 'Docker verification fixture; no booking'})
    assert call('GET', itinerary_path, headers=member)[0]['id'] == planned['id']
    if restart:
        subprocess.run(['docker', 'compose', '--env-file', '.local/docker.env', 'restart',
                        'backend', 'frontend'], cwd=ROOT, check=True, capture_output=True)
        deadline = time.monotonic()+90
        while True:
            try:
                response = session.get(base+'/api/health', timeout=3)
                if response.status_code == 200 and response.json()['status'] == 'ok':
                    break
            except (requests.RequestException, ValueError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError('Health did not recover after restart')
            time.sleep(1)
        assert call('GET', itinerary_path, headers=owner)[0]['id'] == planned['id']
        assert call('GET', itinerary_path, headers=member)[0]['id'] == planned['id']
        assert call('GET', votes_path, headers=member) == totals
        assert session.get(base, timeout=20).status_code == 200
    result = {'fixture_notice': 'Local application verification accounts, not model training interactions',
              'frontend': base, 'workflow_passed': True, 'requests': len(steps),
              'two_member_votes': 2, 'vote_does_not_create_itinerary': True,
              'shared_itinerary': True, 'restart_persistence_verified': restart,
              'member_recommendation_modes': rec['payload']['member_modes'],
              'test_split_accessed': False}
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart', action='store_true')
    args = parser.parse_args()
    run(restart=args.restart)
