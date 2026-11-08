# External raw-input procedure

Raw archives are intentionally **operator supplied**, not embedded in Git or
uploaded by this project. This is an explicit input policy, not an assertion that
`dvc pull` can retrieve the raw archives. Keep a private backup of original files.

Obtain the exact existing files from the original publishers, subject to their
current terms and required attribution:

- [Google Local Data (2021), UCSD](https://mcauleylab.ucsd.edu/public_datasets/gdrive/googlelocal/):
  Hawaii **10-core** reviews named `review-Hawaii_10.json.gz`, plus Hawaii business
  metadata named `meta-Hawaii.json.gz`. Do not substitute the full-review or
  ratings-only collection for the 10-core input.
- [Webis-Tripad-14](https://webis.de/data/webis-tripad-14.html):
  `corpus-webis-tripad-14.tar.gz`, following the publisher's dataset/DOI link.

Place those compressed files directly under `data/raw/`. No extraction or
automatic download is required. Then, using the activated project environment:

```text
python -m backend.mlops.external_inputs
```

This verifies existence, exact byte lengths and SHA-256 hashes from
`backend/mlops/external_inputs.json` without reading individual ratings or
evaluating recommendations. The manifest was generated from the actual existing
archives and is also a declared dependency of their pipeline stages. DVC separately
records the archive MD5 hashes as stage dependencies. An input mismatch is an error;
do not substitute data, silently edit hashes, or force a stage to appear current.

The prepared Pakistan catalog is already a DVC-backed snapshot; recreating its
earlier raw-data preparation/TF-IDF experiment is outside this six-stage Hawaii
pipeline. The local DVC remote is machine-local and private; another operator
must obtain authorized access or provide their own approved artifact storage.
Data/model access must not be inferred from access to the public GitHub code.

Held-out files `data/processed/hawaii/test.csv` and `interactions.csv` are explicit
**uncached preparation outputs**. DVC records their hashes but never uploads or
restores them from the remote. Supply a private, checksum-verified copy alongside
restored train/validation artifacts, or obtain separate approval to run preparation
from the pinned raw archives. Missing uncached outputs make preparation stale;
they must not trigger unreviewed preprocessing. Never run preparation over the
existing held-out snapshot without separate authorization. The existing execution
opt-in gate remains unchanged.
