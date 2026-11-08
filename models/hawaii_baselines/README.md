# Hawaii Step 21 baselines

Run from the project root:

```powershell
.venv/Scripts/python.exe -m backend.train_baselines
.venv/Scripts/python.exe -m unittest discover -s tests -p test_train_baselines.py -v
```

Inputs are explicitly limited to train.csv, validation.csv and
attraction_mapping.csv in data/processed/hawaii/. The test split, full interaction
file, metadata averages and metadata review counts are never read.

The global-mean predictor returns the mean training rating. Item mean returns
the attraction's mean training rating, with training global mean as fallback for
an unseen attraction. Popularity sorts the full prepared catalog by descending
training interaction count, breaking ties by original gmap_id ascending. Each
user's previously rated training attractions are excluded. No negative candidates
are sampled. Catalog membership comes from the existing retrospective 5-core;
this does not create a new prospective catalog protocol.

Rating MAE and RMSE use all validation ratings on the original 1-5 scale.
Ranking uses binary relevance: the single held-out validation rating must be
>=4. Users below that threshold have no observed relevant held-out attraction
and are excluded from ranking averages; their count is explicitly reported.
Recall@10 therefore equals hit rate among relevant-holdout users. With one
relevant item, ideal DCG is 1, so NDCG@10 is 1/log2(rank+1) on a hit and zero
otherwise. Unobserved attractions remain unknown; they are not verified dislikes.
These metrics describe only the single observed validation item, not all items
the user might enjoy. No probability or accuracy interpretation is implied.

Artifacts:

- baselines.joblib: global mean, item means/counts, complete catalog, and training
  histories for reusable predictions and exclusion at inference. Load only trusted
  artifacts; joblib uses pickle internally.
- item_statistics.csv: training-only item means and counts for inspection.
- manifest.json: fitting protocol and train/validation/catalog provenance hashes.
- data/processed/hawaii/baseline_validation_metrics.json: validation metrics,
  denominator, candidate rules and limitations.

Python inference:

```python
from backend.train_baselines import HawaiiBaselines, MODELS
model = HawaiiBaselines.load(MODELS / 'baselines.joblib')
predictions = model.predict_item(['an original gmap_id'])
recommendations = model.recommend('an original user_id', k=10)
```

Only training statistics are fitted. Popularity provides a common ordering with
per-user exclusions; it does not learn individual preferences. Existing 5-core
selection bias, equal timestamp boundaries, cross-user temporal overlap and
rating/exposure imbalance remain limitations. Test data is reserved for a later
approved stage. No matrix factorization or group consensus is implemented.
