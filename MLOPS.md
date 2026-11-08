# Step 28: reproducibility without retraining or test-set access

**Current configuration:** DVC is now Git-integrated, with its active site cache
on E:. Portable commands, environment dependencies, and uncached preparation-only
outputs are defined in the current pipeline. Read
[PIPELINE_REPRODUCIBILITY.md](PIPELINE_REPRODUCIBILITY.md) and
[RAW_INPUTS.md](RAW_INPUTS.md) for the current rules. The Step 28 account below is
historical; its original no-SCM setup and held-out-ignore policy are superseded.

This workspace initially had no local Git repository. DVC was initialized with
--no-scm; no GitHub repository, remote Git repository, commit or push was created.
GitHub Actions configuration is supplied, but no hosted CI execution is claimed.
There is no new model training, test evaluation or deployment in this step.

## Storage and privacy

All default paths resolve beneath E:\GroupTravelMLOps:

- .local/dvc-cache: private content-addressed DVC cache, copy link type.
- .local/dvc-site-cache: active DVC internal status/index bookkeeping on E:.
- .local/dvc-remote: private default local DVC remote named dev.
- .local/mlflow/tracking.db: MLflow SQLite metadata backend.
- .local/mlflow/artifacts: configuration/report provenance artifacts.
- .local/tmp: project temporary files for explicitly approved pipeline executions.
- .local/pip-cache: dependency download cache on E:, not C:.

Machine-local DVC cache/remote paths are in .dvc/config.local, excluded from Git.
.local, application databases/.env, raw and processed data, model weights and
model metadata containing user IDs are excluded. Only small .dvc pointer files,
dvc.yaml/dvc.lock/params.yaml, code, docs, tests and the model-reference manifest
are intended for source control. Public-place test fixtures contain only five
small derived metadata records and no profiles, reviews, ratings or interactions.

The DVC cache and local remote contain real user IDs and model-related private
data: keep their Windows access permissions private and never publish them.
DVC is versioning, not anonymization or encryption. Do not indiscriminately git
add datasets or upload caches. Current no-SCM mode has content snapshots but no
Git version history; adding a local Git repository/source-controlled revisions
is a later explicit operator action. GitHub publication still needs approval.

Raw archives and large pretrained MiniLM encoder/cache files are not duplicated
into DVC here. They remain untouched in their existing local locations. Inputs
are declared as dependencies where required; source archives must be supplied
separately from their legitimate original sources on a fresh machine. No new
dataset downloads were performed.

## Pipeline and artifact snapshots

    prepare -> baselines -> mf -> bpr -> groups
       \_________________________\----> catalog

The exact DAG has direct train/validation/mapping dependencies as well as these
logical edges. Catalog building is a separate branch after preparation and BPR
compatibility metadata. Source adapters, inspection rules and tracking wrappers
are dependencies. Each output has persist:true so a failed opt-in check does
not cause DVC to delete existing datasets/models first.

The six stages call existing code through backend.mlops.pipeline; no training
algorithm was rewritten. Hyperparameter grids/seeds are defined by the existing
training scripts and captured in their existing config/search reports, not by
decorative parameters that the scripts ignore. params.yaml controls the Python
executable (.venv/Scripts/python.exe on Windows). Override this for another OS.

The current dvc.lock was created with dvc commit --no-relink from EXISTING
artifacts. It is an inventory snapshot, not evidence that these new wrappers
were executed end-to-end. Historical reports were retained unchanged. Copy cache
plus --no-relink avoids replacing, moving or write-protecting workspace artifacts.
The local remote intentionally stores another recoverable copy of the selected
outputs; large raw archives/encoders are excluded to limit duplication.

Trackable outputs: Hawaii train/validation, maps, attraction metadata and audit;
baseline/MF/BPR weights/configs/reports; group results/config; unified catalog.
Three additional .dvc pointers track the Pakistan cleaned catalog, its fitted
TF-IDF artifact and Hawaii inspection report. No parent directory that contains
the held-out split is added as a DVC target.

test.csv and the full interactions.csv are excluded from DVC targets/dependencies
and .dvcignore prevents accidental traversal. The original preparation PRODUCER
can create these files on an explicitly approved future full preparation run,
but they are not input to selection, evaluation, tracking or checks here. Their
known hashes already recorded in the old audit may exist as audit metadata; this
step does not open or rehash either file. Full three-way integrity is therefore
NOT revalidated. Treat held-out acquisition/versioning as a separate quarantined
procedure with explicit authorization; do not dvc add the Hawaii parent folder.

## Setup and no-training verification (PowerShell, project root)

```powershell
.venv\Scripts\python.exe -m pip install -r backend\requirements-mlops.txt --cache-dir E:\GroupTravelMLOps\.local\pip-cache
.venv\Scripts\python.exe -m dvc dag
.venv\Scripts\python.exe -m dvc repro --dry
.venv\Scripts\python.exe -m dvc status -c
.venv\Scripts\python.exe -m backend.mlops.quality
.venv\Scripts\python.exe -m backend.mlops.tracking smoke
```

For a fresh source checkout, create the Python environment and install the
application/ML dependencies as well. DVC and MLflow are additions to the existing
ML environment, not replacements for torch/sklearn/numpy. Runtime versions are
recorded in backend/mlops/runtime_versions.json (safe package/version metadata only).
Python 3.12 and Node 22.18 were used. Frontend dependencies are pinned by its
package-lock.json. Original model configs also record training library versions;
matching those matters when reproducing numerical results or loading sklearn.

For a fresh Windows ML environment (this task did not recreate the working venv):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu --cache-dir E:\GroupTravelMLOps\.local\pip-cache
.venv\Scripts\python.exe -m pip install -r backend\requirements-ml.txt -r backend\requirements-api.txt -r backend\requirements-mlops.txt --cache-dir E:\GroupTravelMLOps\.local\pip-cache
```

The compact requirements-ml.txt pins the installed core training packages; the
runtime JSON records the other observed package versions. This is not a universal
cross-platform transitive lock. A single-drive local DVC remote is not an
off-machine disaster-recovery backup; copying/mounting private remote storage on
another machine is a separate authorized operation.

Since machine config is not committed, configure a private remote/cache on a
new machine (adapt the E: path to that workspace):

```powershell
.venv\Scripts\python.exe -m dvc config --local cache.dir E:/GroupTravelMLOps/.local/dvc-cache
.venv\Scripts\python.exe -m dvc config --local cache.type copy
.venv\Scripts\python.exe -m dvc remote add --local -d dev E:/GroupTravelMLOps/.local/dvc-remote
.venv\Scripts\python.exe -m dvc pull
```

Only pull when files are missing/need restoration, after protecting local work.
Do not blindly checkout/pull over modified artifacts. Existing raw inputs must
be available before reproduction. Normal dependency hashing skips unchanged
stages; it does not automatically justify retraining changed inputs.

An actual rebuild requires review/backup and explicit opt-in:

```powershell
.venv\Scripts\python.exe -m dvc repro --dry
# Only AFTER approving data preparation/model training for this workspace:
$env:HUMSAFAR_ALLOW_PIPELINE_EXECUTION='1'
.venv\Scripts\python.exe -m dvc repro
Remove-Item Env:HUMSAFAR_ALLOW_PIPELINE_EXECUTION
```

Preparation can regenerate splits; training can replace its declared outputs.
Do not use --force casually. This task did NOT set the opt-in or execute stages.
When taking an approved existing-output snapshot instead of rebuilding:

Follow the verified, non-forced snapshot procedure and evidence described in
PIPELINE_REPRODUCIBILITY.md. Do not override unexpected hash mismatches or upload
private artifacts. An inventory snapshot never proves training execution.

## MLflow: truthful historical imports and future runs

backend.mlops.tracking uses a forced LOCAL SQLite URI, independent of ambient
cloud credentials/tracking URIs. It disables telemetry/system-metric logging.
MLflow skinny plus SQLAlchemy/Alembic provides the lightweight local backend.
The smoke run is named/tagged tracking_smoke_test and logs only a connectivity
value, not model performance. It is separate from experiment runs.

```powershell
.venv\Scripts\python.exe -m backend.mlops.tracking import-history
```

This imports five existing report components (baselines, MF, BPR, hybrid,
group consensus), tagged origin=imported_historical. It never claims they trained
today. Source hashes, objective/config/seed, validation metrics, stored training
objectives and reported historical runtimes are logged. Group construction seed
and consensus weights are logged. Historical import creation times are NOT
claimed to be original training times. Repeating imports reuses matching runs;
missing training-curve metadata can be enriched from the same genuine reports.
No metrics, timestamps, parameters or historical labels are invented.

Weights and user-ID metadata remain in private DVC rather than being duplicated
in MLflow. MLflow logs small configs/search reports and exact SHA256/path model
artifact references. This is artifact lineage, not a newly serialized MLflow
pyfunc deployment. The hybrid references the same BPR weights; it is not logged
as a separately trained factor model. Future successful opted-in stages use
origin=executed_pipeline_stage; tracking happens after the actual script succeeds.
The local run receipts are under .local/mlflow and are not committed.

A full MLflow UI/server is optional and not installed by skinny dependencies;
use the Python MlflowClient for local inspection. If a UI is later needed,
install the full matching MLflow package separately and bind only to loopback,
pointing at the same SQLite backend/artifact directory. No server, cloud registry
or remote tracking service was deployed here.

## Selection manifest and approval gate

models/registry/model_manifest.json identifies the already user-approved Hawaii
75% BPR + 25% popularity ranking reference, scope, config, validation metrics,
dataset hashes and exact artifact hashes. It separately records MF as a rating
prediction reference; lower RMSE is not treated as better top-k ranking.
The current app routes remain unchanged, and this manifest is not an automatic
serving pointer or claim of worldwide personalization.

Candidate integration requires an operator-supplied approval JSON containing
approved=true, reviewer, reason, and SHA256 of the exact candidate manifest.
backend.mlops.registry approve --candidate ... --approval ... validates the
approval and artifact scope/path/hashes, then records permission for a FUTURE
manual integration only. No promotion was performed here. This lightweight
manifest registry is not a configured MLflow Model Registry deployment service.
A metric threshold alone cannot authorize a model replacement.

## CI and checks

.github/workflows/ci.yml has read-only repository permissions and two jobs:

- Python 3.12: install backend/requirements-ci.txt, compileall syntax checks,
  explicit tests/ci unittest discovery, and static DAG validation.
- Node 22: npm ci using the frontend lockfile, frontend tests and production build.

No raw data, trained weights, personal IDs, AWS secrets, paid service or training
is required. CI fixtures are five genuine public-place metadata records with
descriptions/reviews/user fields removed. API actors and utility matrices are
explicit isolated test/math fixtures, not real ML interaction records. Full
existing tests are NOT blindly discovered on CI because some require private
datasets (and preparation tests read the quarantined test split). Browser E2E
requires the real local catalog and is separately run locally, not faked in CI.
Workflows have not been executed on GitHub because no repository was published.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests/ci -v
.venv\Scripts\python.exe -m unittest discover -s tests -p test_api.py -v
.venv\Scripts\python.exe -m unittest discover -s tests -p test_recommendation_service.py -v
.venv\Scripts\python.exe -m unittest discover -s tests -p test_group_consensus.py -v
cd frontend
npm.cmd test
npm.cmd run build
```

quality checks schema, unique pairs, train-validation nonoverlap, train history,
validation entity coverage, prepared hashes, compatible model identity maps and
weight checksums, metric denominators/hit arithmetic and DAG structure. Group
math/routing/API tests cover aggregation, exclusions, authorization and service
boundaries. They do not claim independently measured generalization or fairness.

Remaining limits: no Git revision history in current no-SCM workspace; private
raw data must be separately supplied; held-out files remain quarantined; no fresh
training reproducibility claim; no hosted CI result; no native MLflow model-serving
registry/rollout. Existing selection bias, timestamp ties, single-item validation
and international coverage limitations remain unchanged. C: is full, so local
verification uses the unaffected E: workspace and outside-sandbox execution.
