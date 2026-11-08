# Pipeline metadata refresh: no new training

The six stages still call the existing preparation, baseline, MF, BPR, group
evaluation and catalog implementations. Those scientific scripts and the stage
execution gate were not changed. All data/model contents and MLflow records were
preserved. This update is **an inventory/metadata snapshot of existing artifacts**,
not an execution record for the revised commands or a newly trained experiment.
See `backend/mlops/snapshot_provenance.json` for the previous/current lock hashes
and preserved-output evidence.

## Portable execution environment

`params.yaml` now selects `python`. Every stage executes
`python -m backend.mlops.pipeline <stage>`, and explicitly tracks `runtime.python`.
Activate the intended Python 3.12 environment first:

```powershell
# Windows PowerShell, project root
.\.venv\Scripts\Activate.ps1
python -c "import sys; print(sys.executable)"
python -m dvc repro --dry
```

```bash
# Linux, project root
source .venv/bin/activate
python -c "import sys; print(sys.executable)"
python -m dvc repro --dry
```

Install the existing CPU ML requirements and MLOps requirements in that environment.
CPU PyTorch installation remains documented in `MLOPS.md`. `configure.py` preserves
an existing interpreter override rather than resetting it to a Windows executable.
No pipeline execution is authorized by these inspection commands. The existing
`HUMSAFAR_ALLOW_PIPELINE_EXECUTION` gate remains required for a later approved run.

MLOps requirements and the recorded runtime-version file are dependencies for
all stages. ML requirements are dependencies where NumPy/pandas/torch or their
shared modules are used; preparation uses the standard-library implementation.
The tracking helper is a dependency only for stages that actually invoke it.
Changing frontend/API files does not unnecessarily invalidate model stages.

This is not a complete transitive environment lock, and package installation
changes are not detected merely by DVC looking at requirements files. Operators
must create the intended environment and check versions. Cross-platform numeric
or byte-identical reproduction is not claimed. Timing fields in generated reports
also vary across genuine executions.

## Explicit producer-only outputs

Preparation already generates `test.csv` and `interactions.csv`. Both are now
declared with `persist: true` and `cache: false`. Their current byte hashes were
checked against the original preparation audit, then recorded in `dvc.lock`.
Only hashing was performed: no ratings were parsed or evaluated. The unchanged
preparation implementation is their declared producer; no regeneration was run
to demonstrate a new end-to-end result.

No consumer may declare either file as an input. `validate_layout` and data-free
tests enforce that rule and reject cached held-out outputs. Git still ignores
all dataset contents. Uncached outputs are not copied into the DVC object cache,
uploaded, or recoverable by `dvc pull`. Missing copies make preparation stale:
use a protected private copy matching the recorded hashes, or seek separate
authorization for preparation. Do not run preprocessing over existing splits.

MLflow logging is an intentionally local side effect rather than a deterministic
DVC output. Pulling artifacts or skipping up-to-date stages does not recreate
the original run IDs/history. Back up the tracking database and its artifact tree
separately. No MLflow experiment was created or updated during this refresh.

## Raw inputs

Follow [RAW_INPUTS.md](RAW_INPUTS.md). A checked-in manifest records exact sizes,
SHA-256 checksums and publisher references for the three original compressed
archives. A read-only verification helper fails on missing or mismatched inputs;
there are no automatic downloads, extraction, redistribution or uploads. Raw
archives remain declared DVC dependencies but are not DVC-backed objects.

## How the lock was refreshed

Before recording anything, all 30 original objects were checked in workspace,
cache and local remote: 90 checksum checks passed. Existing scientific scripts
and MLflow files were checked unchanged; the added producer-only files matched
their original audit SHA-256 hashes. No inconsistency was overridden.

DVC 3.67.1 supports a non-forced, interactive `dvc commit --no-relink` metadata
snapshot. Each of the six expected declaration changes was separately inspected
and confirmed. Neither `--force` nor stage execution was used; the execution gate
was explicitly disabled. `--no-relink` preserved workspace files. Persistent
outputs disable DVC run-cache entries, and no executed-stage cache was created.
This operation is **not a Git commit** and does not establish that the revised
commands produced these artifacts. Never use this procedure to cover an unexpected
data/hash mismatch; stop and investigate instead.

Subsequent checks compare every original locked output entry unchanged, validate
the two new hashes and all current dependency hashes, and check that all MLflow
files retain their original hashes. `dvc status`/remote status are synchronized;
`dvc repro --dry` only inspects and skips current stages. No stage was executed.

Run the lightweight checks without data regeneration:

```text
python -m backend.mlops.external_inputs
python -m backend.mlops.quality
python -m unittest discover -s tests/ci
python -m dvc status --json
python -m dvc status --cloud --json
python -m dvc repro --dry
```

A clean checkout still needs legitimate raw archives, access to the private
artifact remote, private uncached producer outputs, and the correct environment.
An isolated full rebuild has not been performed. Git/DVC cannot by themselves
provide data access, licensing permission, or a backup outside this E: drive.
