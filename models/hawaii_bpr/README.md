# Step 23: BPR and popularity-personalization hybrid

Run from the project root using the existing CPU PyTorch environment:

```powershell
.venv/Scripts/python.exe -m backend.train_bpr
.venv/Scripts/python.exe -m unittest discover -s tests -p test_bpr.py -v
```

Inputs are explicitly limited to train.csv, validation.csv, attraction_mapping.csv,
baseline_validation_metrics.json and matrix_factorization_validation_metrics.json
in data/processed/hawaii/. The split/catalog checksums must match the previous
experiments. No test data, raw metadata, or full-corpus review statistics are read.
Original datasets and previous model artifacts are not written.

Training uses actual training ratings >=4 as positive user-attraction pairs.
Each epoch visits every positive once in a seeded random order, drawing one
uniform comparison item with replacement from outside that user's COMPLETE
training history. This excludes training ratings below 4 as well as positives.
A dense boolean seen matrix (~37.4 MiB for the prepared data) makes rejection
sampling efficient. No history is inferred from validation. Consequently a
held-out attraction can be sampled as an unknown comparison; it is never looked
up as a validation label. Comparison items are unobserved, not verified dislikes.
The pairwise preference is a modeling assumption, not fabricated negative data.

Raw score: dot(user factors, item factors) + item bias. A user bias would cancel
in the pairwise difference, so it is omitted. Mean softplus of the negative
positive/comparison score difference is minimized, plus observation-weighted L2
regularization of sampled user/item factors and both item biases. Adam has no
additional weight decay. Factors start Normal(0,.05), biases zero; users without
training positives have zero user factors and rank by learned item biases.

Prespecified grid: factors {16,32}, regularization {.001,.01}, learning rate
{.005,.02}. Each of eight trials gets 15 epochs, batch size 4096, seed 2026,
deterministic CPU algorithms and one PyTorch/BLAS thread. Select maximum final
validation NDCG@10; ties use Recall@10 then grid order. No validation gradients or
train+validation refitting occur. All trials/objectives/runtimes are saved.

For the selected BPR, tune alpha over {0,.25,.5,.75,1}:

    hybrid = alpha * minmax(raw BPR score)
             + (1-alpha) * minmax(log1p(training interaction count))

Both components are scaled independently to [0,1] over each user's eligible
unseen catalog. Constant components become zero. Popularity counts include all
valid training interactions, matching Step 21. alpha=0 is pure popularity;
alpha=1 is pure BPR. Both endpoints are included and alpha=0 must reproduce the
previous popularity metrics. Hybrid ties on NDCG and Recall prefer lower alpha.
A selected endpoint must not be described as successful personalization mixing.

Evaluation uses the identical 23,806 users whose single validation rating is >=4.
Rank the complete 1,512-attraction catalog minus each user's complete training
history. Sort scores descending then original gmap_id ascending; no sampled
evaluation candidates. With one relevant holdout, Recall@10 equals hit rate and
NDCG@10 is 1/log2(rank+1) on a hit, zero otherwise. Scores are not probabilities,
and unobserved attractions remain unknown rather than confirmed negatives.

Artifacts required for inference: model.npz (factors, item biases, train counts)
and metadata.json (string IDs, train histories, selected config, alpha, checksum).
config.json records normalization, objective, grid, software and provenance.
The NPZ is loaded with allow_pickle=False and its checksum/array shapes checked.

```python
from backend.train_bpr import BPR
model = BPR.load()
# Use a real original training user ID:
bpr_top10 = model.recommend(user_id, alpha=1)
hybrid_top10 = model.recommend(user_id)  # saved selected alpha
```

Results: data/processed/hawaii/bpr_validation_metrics.json contains comparisons
with popularity/MF and the selected BPR/hybrid metrics. bpr_search.json contains
all eight configurations and five mixing-weight results. No rating MAE/RMSE is
claimed for these implicit ranking scores.

Measured validation outcome: selected BPR has 32 factors, regularization .01 and
learning rate .005. Its Recall@10 is .249685 and NDCG@10 .133115. Selected alpha
is .75; hybrid Recall@10 is .249643 and NDCG@10 .134468. The hybrid has one fewer
hit than BPR (5943 vs 5944), while improving discounted rank on this validation
set. Both exceed the previous popularity/MF ranking metrics in this experiment;
this is not an independent test or statistical-significance result. Training
uses 167010 positive interactions; 100 training users have no >=4 positive and
therefore use the learned item-bias ordering.

Limitations: BPR selection and alpha tuning both reuse validation, making reported
scores selection-conditioned; no independent final test result exists yet.
5-core filtering uses full-graph future membership and favors active users and
popular attractions. Timestamp ties and cross-user temporal overlap in the
existing per-user splits prevent a strict global chronological interpretation.
There is one validation item per user; it cannot represent every relevant item
or establish statistical significance. Explicit-rating thresholds, exposure
bias, one seed and a small grid limit conclusions. Hawaii is the first
international HumSafar experiment, not proof of international generalization
or Adaptive Group Consensus/fairness outcomes.
