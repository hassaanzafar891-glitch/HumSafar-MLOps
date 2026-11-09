# HumSafar local Docker application

The existing FastAPI factory runs with Python 3.12 and one Uvicorn worker.
React builds with Node 22 and is served by unprivileged Nginx. Only
`127.0.0.1:8080` is published; the backend is on a private Compose network.
Nginx strips `/api/` exactly as the existing Vite development proxy does.

- Frontend: http://localhost:8080
- Backend health through Nginx: http://localhost:8080/api/health
- Swagger: http://localhost:8080/api/docs

Local authenticated metrics and privacy-safe structured logging are described
in [MONITORING.md](MONITORING.md). Monitoring counters reset on backend restart;
the SQLite database remains persistent.

## Verified results

Both images built successfully and both containers are healthy:
`humsafar-backend-1` and `humsafar-frontend-1`. Docker displays approximately
1.81 GB for the backend image and 97 MB for the frontend; these are image sizes,
not compressed download sizes.

- Compose configuration and Nginx syntax checks passed.
- All 16 lightweight CI/configuration tests passed, including five Docker tests.
- All three real Edge browser tests passed against Nginx: the two-account
  workflow, mobile layouts, and verified destination photographs.
- The 19-request HTTP check passed registration/login for two fixture accounts,
  group creation/joining, own preferences, consensus recommendations, two votes,
  explicit itinerary creation, and shared itinerary reads.
- Both HumSafar containers were restarted. Existing tokens, both users' access,
  vote totals and the persisted itinerary remained valid. Votes alone were
  verified not to create itinerary items.
- In-container artifact loading passed for the 13,625-record catalog,
  69-destination TF-IDF artifact, BPR weights/metadata for 1,512 attractions,
  and BPR configuration. All five serving files match their source checksums.
- PyTorch reports `2.6.0+cpu`; no CUDA/NVIDIA Python packages are installed.
  No training, data regeneration or held-out split evaluation was performed.
- New application users received `pakistan_tfidf_content` recommendations,
  never historical Hawaii user embeddings.
- Git safety review found no exposed private runtime files or candidate files
  over 10 MiB. Secret-pattern matches are existing examples/fixtures and code
  generating a random secret. Nothing was staged, committed or pushed.

Verification creates clearly named local fixture accounts/groups in the
separate Docker database. These are application checks, not ML feedback.
Native tests from the preparation phase also passed: 17 API tests, 19 frontend
unit tests and the production frontend build.

## Storage

Docker Engine 29.8.2 and Compose 5.6.0 were verified. Docker VHDs are under
`E:\DockerData\DockerDesktopWSL`. After building, E: had approximately 127 GiB
free and C: approximately 4.1 GiB free. No images, volumes or caches were deleted.
The unrelated SQLiLab web/MySQL containers were left running and unchanged.

Project runtime state, artifacts, dependency wheels and temporary test files are
on E:. These bind mounts do not themselves relocate Docker's image storage.
Review Docker Desktop's storage settings before future large builds; storage is
never moved automatically. See [Docker Desktop settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/).

## Provision and build

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe docker/prepare_local.py
.\.venv\Scripts\python.exe docker/download_wheels.py
docker compose --env-file .local/docker.env config --quiet
docker compose --env-file .local/docker.env build
docker compose --env-file .local/docker.env up -d --wait
docker compose --env-file .local/docker.env ps
```

`prepare_local.py` copies only five trusted existing serving files into ignored
`.local/docker-runtime/`, verifies SHA-256 checksums, creates an empty state
directory and generates a private JWT secret if none exists. Originals are
untouched. Existing secrets and different bundles are never overwritten.

- `data/processed/international/catalog.jsonl`
- `models/tfidf_baseline.joblib`
- `models/hawaii_bpr/model.npz`
- `models/hawaii_bpr/metadata.json`
- `models/hawaii_bpr/config.json`

Missing artifacts require authorized private provisioning; startup never fits
models or downloads datasets. Load joblib files only from trusted sources.
The BPR metadata contains historical user identifiers: never publish the bundle.
The manifest detects changes relative to locally provisioned files; it is not a
signature or independent authenticity guarantee.

`download_wheels.py` provisions **Python 3.12 Linux amd64** wheels through the
host into ignored `.local/docker-wheels/`. Torch is fetched with `--no-deps`
only from the official CPU index; ordinary dependencies are resolved using
PyPI and the existing API/ML requirements with serving constraints. BuildKit
mounts that directory read-only, installs with networking disabled and runs
`pip check`. Wheel files are not copied into the resulting image layers.
Keep the wheel directory for identical offline reuse. Unpinned transitive
dependencies can change when provisioning a fresh wheel directory.
ARM builds are not supported by this wheel provisioning script.

This host download step fixes observed Docker outbound package-index timeouts:
the initial online backend build timed out and eventually reported an unavailable
SQLAlchemy candidate even though the required Linux wheel exists. Host downloads
and the offline installation succeeded without changing package/model versions.
Base-image pulls, Debian packages and frontend npm installation still need
network access on a fresh build.

The second runtime fix quotes comma-containing tmpfs strings in Compose.
Unquoted YAML flow lists otherwise split mount options into invalid mount paths;
the tests now assert each service has one complete tmpfs setting.

## Secrets and persistent SQLite

The private environment file is `.local/docker.env`; `docker/.env.example`
contains only safe settings. Never print full resolved `docker compose config`
output because it includes the JWT secret. Use `config --quiet` for validation.
Protect the private file using Windows ACLs; Unix file modes alone do not enforce
Windows access control. Do not rotate the secret during ordinary restarts.

SQLite is stored separately from the native application's database:

`E:\GroupTravelMLOps\.local\docker-state\humsafar.db` -> `/state/humsafar.db`

The state directory is a writable bind mount; the serving bundle is read-only.
No native database was copied or modified. Windows Docker Desktop must be able
to share these E: directories. On Linux, the provisioning helper configures the
current non-root UID/GID; root-run provisioning requires explicitly assigning
state-directory ownership to the configured container UID/GID.

## Repeat checks, inspect and stop

```powershell
docker compose --env-file .local/docker.env logs --tail 100 frontend backend
.\.venv\Scripts\python.exe docker/verify_workflow.py --restart
Get-Content -Raw docker/verify_artifacts.py | docker compose --env-file .local/docker.env exec -T backend python -
docker compose --env-file .local/docker.env exec -T frontend nginx -t
cd frontend
npx playwright test --config playwright.docker.config.js
cd ..
docker compose --env-file .local/docker.env stop
docker compose --env-file .local/docker.env down
```

The HTTP helper restarts **only HumSafar's backend/frontend** when explicitly
given `--restart`. The browser configuration uses already-running Nginx; it
starts no native development servers. Screenshots and traces are disabled to
avoid retaining private group details.

Stopping/removing the Compose containers preserves the bind-mounted state and
artifacts. To start with a fresh development database, stop HumSafar, back up the
entire state directory, create a different empty directory, and set its absolute
path as `HUMSAFAR_STATE_DIR` in the private environment file. Do not delete the
existing database as an incidental reset step.

## Boundaries and remaining limitations

Build contexts use allowlists, and no credentials, databases, datasets, model
weights, DVC caches or MLflow storage are baked into images. Containers use
non-root users, read-only roots, dropped capabilities, bounded logs, health
checks and restart policies. Nginx replaces forwarded client-address headers;
the unpublished backend trusts that private proxy boundary. Do not publish the
backend port directly. One worker retains the existing process-local limiter.

No source ML logic, rankings, datasets, authentication or voting behavior changed.
No DVC, MLflow or sentence-transformers are installed in the serving image.
Base-image tags are not digest-locked; a complete transitive dependency lock is
also not provided. This verified local HTTP setup still needs a separate TLS,
backup and deployment review before any public cloud release.
