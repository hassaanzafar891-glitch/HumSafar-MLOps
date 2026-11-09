"""View local metrics without putting credentials in shell history or files."""
from getpass import getpass
import requests


def main():
    session = requests.Session()
    session.trust_env = False
    credentials = {'username': getpass('Local account email (hidden): '),
                   'password': getpass('Password (hidden): ')}
    response = session.post('http://localhost:8080/api/auth/login', data=credentials, timeout=30)
    credentials.clear()
    if response.status_code != 200:
        raise SystemExit('Login failed (HTTP '+str(response.status_code)+').')
    token = response.json()['access_token']
    response = session.get('http://localhost:8080/api/metrics',
                           headers={'Authorization': 'Bearer '+token}, timeout=30)
    if response.status_code != 200:
        raise SystemExit('Metrics unavailable (HTTP '+str(response.status_code)+').')
    print(response.text, end='')


if __name__ == '__main__':
    main()
