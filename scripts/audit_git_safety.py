r"""Prospective Git audit without initializing/staging a repository.

Requires pathspec (already installed with DVC). No dataset/model/database content
is read; ignored directories are pruned. Findings contain paths/rules, not secrets.
Run: .venv\Scripts\python.exe scripts/audit_git_safety.py
"""
import json
import os
from pathlib import Path
import re
import subprocess

from pathspec import GitIgnoreSpec, PathSpec

ROOT = Path(__file__).resolve().parents[1]
TEXT = {'.py', '.js', '.jsx', '.json', '.yaml', '.yml', '.md', '.txt', '.toml',
        '.ini', '.cfg', '.html', '.css', '.ps1', '.sh', '.ipynb', '.dvc', '.lock', '.example'}
RULES = {
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'aws_access_key_id': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'github_token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
    'google_api_key': r'\bAIza[A-Za-z0-9_-]{35}\b',
    'jwt_literal': r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{15,}\b',
    'credential_url': r'[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]{5,}@',
    'credential_literal': r'''(?i)(?<![\w-])(?:jwt_secret(?:_key)?|api[_-]?key|client[_-]?secret|password|access[_-]?token)\b["']?\s*[:=]\s*["'][^"'\r\n]{8,}["']''',
}


def ignored(path, contexts):
    result = False
    for base, spec, _ in contexts:
        check = spec.check_file(path.relative_to(base).as_posix())
        if check.include is not None:
            result = check.include
    return result


def inventory(root=ROOT):
    candidates, excluded, links = [], [], []

    def visit(directory, contexts):
        rulefile = directory / '.gitignore'
        if rulefile.is_file():
            rules = rulefile.read_text(encoding='utf-8').splitlines()
            contexts = [*contexts, (directory, GitIgnoreSpec.from_lines(rules), PathSpec.from_lines('gitignore', rules))]
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root).as_posix()
            if path.name == '.git':
                continue
            if path.is_symlink():
                if ignored(path, contexts):
                    excluded.append(relative)
                else:
                    links.append(relative)
                continue
            if path.is_dir():
                # A trailing slash is needed to apply directory-only patterns.
                is_ignored = False
                # GitIgnoreSpec's file-over-directory priority is useful for
                # files, but directory traversal needs last-match directory
                # rules so explicit !/data/**/ parents remain traversable.
                for base, _, spec in contexts:
                    check = spec.check_file(path.relative_to(base).as_posix() + '/')
                    if check.include is not None:
                        is_ignored = check.include
                if is_ignored:
                    excluded.append(relative + '/')
                else:
                    visit(path, contexts)
            elif ignored(path, contexts):
                excluded.append(relative)
            else:
                candidates.append(path)
    visit(root, [])
    return candidates, excluded, links


def scan(candidates):
    known_secrets = []
    # Compare candidate contents with local secret values without printing them.
    env = ROOT / '.env'
    if env.is_file():
        for line in env.read_text(encoding='utf-8').splitlines():
            key, separator, value = line.partition('=')
            value = value.strip().strip('\"\'')
            if separator and re.search(r'SECRET|TOKEN|PASSWORD|API.?KEY|ACCESS.?KEY', key, re.I) and len(value) >= 16:
                known_secrets.append(value)
    findings, scanned = [], 0
    for path in candidates:
        if path.suffix.lower() not in TEXT and path.name not in {'.gitignore', '.dvcignore', 'config', 'Dockerfile', 'Makefile', '.npmrc'}:
            continue
        if path.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        scanned += 1
        relative = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(content.splitlines(), 1):
            for rule, expression in RULES.items():
                if re.search(expression, line):
                    findings.append({'path': relative, 'line': number, 'rule': rule})
            if any(secret in line for secret in known_secrets):
                findings.append({'path': relative, 'line': number, 'rule': 'matches_local_environment_secret'})
    return scanned, findings


def main():
    candidates, excluded, links = inventory()
    scanned, findings = scan(candidates)
    relative = {p.relative_to(ROOT).as_posix() for p in candidates}
    required = ['.gitignore', '.env.example', 'frontend/.env.example', '.dvc/config',
                '.dvcignore', 'dvc.yaml', 'dvc.lock', 'params.yaml',
                '.github/workflows/ci.yml', 'frontend/package.json', 'frontend/package-lock.json',
                'models/registry/model_manifest.json', 'backend/api/app.py', 'frontend/src/App.jsx',
                'frontend/public/images/destinations/ATTRIBUTION.md']
    preserved_groups = {key: sum(p.startswith(prefix) and p.endswith(suffix) for p in relative)
                        for key, prefix, suffix in [('dvc_pointers','', '.dvc'),
                            ('python_dependencies','backend/requirements-', '.txt'),
                            ('python_tests','tests/', '.py'), ('frontend_photos','frontend/public/images/', '.webp')]}
    git = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    report = {'git_initialized': git.returncode == 0,
              'git_root': git.stdout.strip() if git.returncode == 0 else None,
              'method': 'Prospective Git wildmatch with nested .gitignore files; not an index/history audit.',
              'candidate_count': len(candidates), 'candidate_bytes': sum(p.stat().st_size for p in candidates),
              'text_files_scanned': scanned, 'preserved_groups': preserved_groups,
              'missing_or_excluded_required_files': sorted(set(required) - relative),
              'candidate_files_over_10_mib': [{'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size}
                                              for p in candidates if p.stat().st_size > 10 * 1024 * 1024],
              'symlinks_needing_review': links, 'potential_secret_findings': findings,
              'excluded_paths': excluded, 'candidate_paths': sorted(relative)}
    output = ROOT / '.local/git_safety_audit.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    # Omit verbose inventory. Match values, environment secrets and credentials
    # never appear in either stdout or the JSON report.
    print(json.dumps({k: v for k, v in report.items() if k not in {'candidate_paths','excluded_paths'}}, indent=2))
    print('Local-only detailed report: .local/git_safety_audit.json')


if __name__ == '__main__':
    main()
