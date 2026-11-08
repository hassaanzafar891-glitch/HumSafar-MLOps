# Git preparation review

The initial prospective audit was completed before Git initialization. Git has
now been initialized locally on `main`, and project files are staged for first-commit
review under separate user authorization. No commit, GitHub connection, push or
upload has been made. The reusable audit below checks prospective working-tree
files; staged blobs are also checked separately during first-commit review.

## Ignore policy

The root `.gitignore` now excludes:

- Real `.env`/`.env.*`/`*.env` files, common private key formats, credential JSON
  filenames, `.aws`, `.ssh` and `secrets` directories. Reviewed `.env.example`
  files remain included at both root and frontend level.
- Python environments/bytecode/tool caches, Node dependencies/npm cache, build
  output, coverage output, browser reports/screenshots, editor cache, temporary
  files and logs.
- SQLite `.db`, `.sqlite`, `.sqlite3` files and WAL/SHM/journal sidecars;
  all `backend/var` application state.
- `.local`, local MLflow runs/artifacts, DVC cache/tmp/local remotes and
  `.dvc/config.local`. External E: cache/remote directories are outside the
  future project repository; configuration referring to them stays local.
- All data payloads under `data`, except `.dvc` pointer files. All model
  payloads under `models`, except `.dvc` pointers, project README documentation
  and the reviewed registry JSON manifest. Hugging Face cache and downloaded
  encoder directories are excluded entirely, including their cached READMEs.
- Common serialized model/weight extensions if accidentally copied outside
  the canonical model directory.

None of the excluded data, databases, models or experiment storage was deleted
or moved. Existing nested frontend ignore rules remain intact.

## Files preserved

The audit verified source code, tests, documentation, both safe environment
examples, all five Python requirements files, npm package/lock files, the GitHub
Actions workflow, `.dvc/config`, `.dvcignore`, `dvc.yaml`, `dvc.lock`, `params.yaml`,
all three existing `.dvc` pointer files and `models/registry/model_manifest.json`.
All 32 licensed frontend photo assets and their attribution/manifest files remain
included. No candidate file exceeded 10 MiB. The full candidate set is about 4 MB.

The DVC configuration currently uses `core.no_scm = True` for the existing
standalone workflow. It was preserved. Review the intended Git/DVC integration
when initialization is separately authorized. A fresh clone will require the
artifact/data retrieval described in `MLOPS.md`; Git will not contain data or
model payloads, local application state, or the machine-specific DVC remote.

## Secret review

Candidate text was checked for recognizable cloud/GitHub/API keys, private key
blocks, literal JWTs, credential-bearing URLs and quoted credential assignments.
Candidate text was also compared against nonempty secret values in the local
`.env`, without printing or copying those values. **No candidate matched the local
environment secret, and no live credential was identified.**

Five heuristic matches were manually reviewed and retained:

| File | Classification |
| --- | --- |
| `.env.example` | Commented PostgreSQL URL with literal `USER:PASSWORD@HOST` placeholders |
| `frontend/src/api.test.js` | Mock access-token response for isolated frontend tests |
| `tests/ci/test_ci.py` (two occurrences) | Explicit fixture password for temporary CI application accounts |
| `tests/test_api.py` | Explicit fixture password for temporary API-test accounts |

These are not deployable credentials. The audit deliberately continues to report
them for review, rather than exempting all test/example files from secret checks.
The scanner is heuristic: an unrecognized or encoded secret can escape detection.
There is no commit history yet. The initial prospective scan was followed by
a separate staged-index review after initialization.

## Repeat verification

```powershell
.venv\Scripts\python.exe scripts\audit_git_safety.py
.venv\Scripts\python.exe -m unittest discover -s tests -p test_git_safety.py
```

The audit requires `pathspec`, already installed through the project's DVC
dependencies. It models nested Git ignore rules without creating a repository,
prunes ignored runtime directories and does not read dataset/model/database
contents. Only the local `.env` is read for redacted secret comparison. Its
detailed path/rule report is saved under ignored `.local/git_safety_audit.json`;
it contains no matched credential values. Four automated fixture tests cover
payload exclusion, safe metadata inclusion, nested rules, redaction and avoiding
payload-content reads. All four passed locally.

Local initialization and staging are authorized; creating the first commit is
not yet authorized. Inspect the actual Git status and staged diff again before
any later approved commit: `.gitignore` cannot protect files deliberately force-added
or files already tracked in a future repository. Do not publish local runtime
folders or upload this workspace wholesale as a substitute for reviewing Git's
candidate/staged file list.
