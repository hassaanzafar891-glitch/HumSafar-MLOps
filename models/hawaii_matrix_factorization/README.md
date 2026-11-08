# Step 22: explicit-rating matrix factorization

Run from the project root with the existing CPU PyTorch environment:

```powershell
.venv/Scripts/python.exe -m backend.train_matrix_factorization
.venv/Scripts/python.exe -m unittest discover -s tests -p test_matrix_factorization.py -v
```

The script reads only train.csv, validation.csv, attraction_mapping.csv and
baseline_validation_metrics.json. It verifies the first three input checksums
against Step 21 provenance. No test data, raw metadata or full-data rating
statistics are read, and no split or baseline artifact is modified.

Model equation: predicted rating = training global mean + user bias + item bias
+ dot(user factors, item factors). The mean stays fixed. The fit method accepts
only training interactions, a catalog of IDs and a configuration; validation is
not an argument and never enters gradient updates. Unknown IDs use the available
known-side bias or global mean when both are unknown. This fallback is not
claimed to provide cold-start personalization. Rankings require a known user.

Training minimizes mean batch squared error plus lambda times the batch mean of
the squared factor norms and squared user/item biases. This is regularization
weighted by observed interaction frequency, not an unweighted full-table penalty.
Adam uses its default betas/epsilon and no additional weight decay. Factors
start Normal(0,.05), biases start zero, and batches are reshuffled each epoch.

The prespecified grid is factors {8,16}, regularization {.01,.1}, learning rate
{.005,.02}: eight trials, 20 epochs each, batch size 4096, seed 2026. Training is
CPU-only, deterministic algorithms enabled, one PyTorch/BLAS thread during the
run. Choose the lowest final-epoch validation RMSE; exact ties use grid order.
Ranking is evaluated only after selection, not used to choose a configuration.
The selected checkpoint is retained without refitting on validation data.
config.json records software versions, objective, seed, grid and source hashes.
Reproducibility is expected within the recorded software/CPU environment;
cross-version numerical identity is not guaranteed.

MAE/RMSE use all validation ratings with predictions clipped to [1,5]. Ranking
uses raw scores to avoid artificial clipping ties. Items are ordered by raw
score descending then original gmap_id ascending. All 1,512 catalog attractions
are scored, each user's training history excluded, with no sampled negatives.
Unobserved attractions are unknown, not confirmed dislikes. Macro Recall@10 and
NDCG@10 use the same 23,806 users with a validation rating >=4 as Step 21.
Each has exactly one relevant held-out item; Recall equals hit rate and NDCG is
1/log2(rank+1) for a hit, otherwise zero. Neither measures all potential relevant
attractions or represents a probability.

Files:

- model.npz: user/item latent factors and biases (float32, no pickle required).
- metadata.json: original ID mappings, training mean and histories, configuration
  and model checksum. Required alongside model.npz for inference.
- config.json: reproducible fitting and selection protocol.
- data/processed/hawaii/matrix_factorization_search.json: every trial's final
  validation rating metrics, epoch objectives and measured training runtime.
- data/processed/hawaii/matrix_factorization_validation_metrics.json: selected
  validation rating/ranking metrics, baseline comparisons and measured runtimes.

Python inference:

```python
from backend.train_matrix_factorization import MatrixFactorization
model = MatrixFactorization.load()
# Use actual original user/attraction IDs from the prepared mappings:
ratings = model.predict(user_ids, attraction_ids)
top_ten = model.recommend(user_ids[0], k=10)
```

Observed outcome: selected MF improves validation MAE/RMSE over item mean but
substantially underperforms popularity for Recall@10/NDCG@10. An explicit-rating
squared-error objective and RMSE-based selection do not establish useful top-k
ranking; no ranking superiority is claimed and no additional search was added
after seeing the ranking result.

Limitations: selection and reporting reuse validation, so metrics are
selection-conditioned. Full-graph 5-core selection uses future graph membership
and favors active users/popular items. Existing per-user chronological splits
include timestamp ties and cross-user temporal overlap; they are not a globally
chronological prospective benchmark. There is one validation item per user,
rating/exposure imbalance, one training seed and a small grid. The test split
remains untouched. Hawaii is the first international HumSafar benchmark; these
results do not establish performance on unseen regions, group consensus, or
fairness outcomes.
