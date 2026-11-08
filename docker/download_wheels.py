"""Download public Python 3.12 Linux CPU wheels on the host, into ignored E: storage."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT/'.local/docker-wheels'


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    common = [sys.executable, '-m', 'pip', 'download', '--disable-pip-version-check',
              '--timeout', '60', '--retries', '3', '--no-cache-dir', '--dest', str(DESTINATION),
              '--platform', 'manylinux_2_28_x86_64', '--platform', 'manylinux2014_x86_64',
              '--platform', 'manylinux_2_17_x86_64', '--platform', 'linux_x86_64',
              '--python-version', '312', '--implementation', 'cp', '--abi', 'cp312',
              '--only-binary=:all:']
    subprocess.run(common+['--no-deps', 'torch==2.6.0+cpu', '--index-url',
                          'https://download.pytorch.org/whl/cpu'], cwd=ROOT, check=True)
    subprocess.run(common+['--index-url', 'https://pypi.org/simple', '--find-links', str(DESTINATION),
                          '-r', 'backend/requirements-api.txt', '-r', 'backend/requirements-ml.txt',
                          '-c', 'docker/backend/constraints.txt'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
