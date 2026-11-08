"""Validate read-only private artifacts, then launch the existing app factory."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from humsafar_artifacts import verify_bundle

def main():
    verify_bundle('/opt/humsafar-artifacts')
    # Only Nginx can reach this backend through Compose's private API network.
    # It replaces incoming forwarding headers; do not publish backend port 8000.
    os.execvp('python', ['python', '-m', 'uvicorn', 'backend.api.app:create_app',
        '--factory', '--host', '0.0.0.0', '--port', '8000', '--workers', '1',
        '--root-path', '/api', '--proxy-headers', '--forwarded-allow-ips', '*'])

if __name__ == '__main__':
    main()
