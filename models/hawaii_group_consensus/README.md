# Step 24: simulated-group consensus experiment

Run from the project root:

```powershell
.venv/Scripts/python.exe -m backend.evaluate_group_consensus
.venv/Scripts/python.exe -m unittest discover -s tests -p test_group_consensus.py -v
```

No models are trained, weights tuned, or previous artifacts modified here.
backend/group_consensus.py provides reusable formation/scoring/aggregation;
backend/evaluate_group_consensus.py handles the isolated validation phase.

## Individual scores and candidates

Load the saved Step 23 BPR encoder and its training-only item counts and complete
training histories. Verify those counts and histories against train.csv. For
member u and item i, use exactly the selected individual hybrid:

    x_ui = .75 * minmax_u(raw BPR score_ui)
           + .25 * minmax_u(log1p(training interaction count_i))

Each min-max transform is over that user's own unseen catalog, as in Step 23;
constant components become zero. No held-out ratings normalize scores. Then
restrict all members to C_g, the complete catalog minus the UNION of all group
training histories, without additional rescaling. Columns follow original
gmap_id ascending, providing deterministic score tie-breaking for all methods.
Scores in [0,1] are model-based utility proxies, not satisfaction observations,
probabilities, or calibrated interpersonal welfare.

## Exact aggregators

Average ranks by mean_u(x_ui). Least misery ranks by min_u(x_ui). Both select
the ten highest candidate scores with the same ID tie-break.

Adaptive Group Consensus greedily constructs a ten-item list. At position t,
let c_u be member u's sum of predicted scores from the t-1 selected items:

    prior_u = 0                         if t = 1
              c_u / (t-1)              otherwise
    w_u = (1 - prior_u + epsilon) / sum_v(1 - prior_v + epsilon)
    q_ui = (c_u + x_ui) / t
    A_t(i) = lambda_avg * sum_u(w_u * x_ui)
             + lambda_min * min_u(q_ui)
             + lambda_fair * (1 - [max_u(q_ui) - min_u(q_ui)])

Select the remaining item maximizing A_t(i), then add its scores to c_u.
Fixed values: lambda_avg=.5, lambda_min=.3, lambda_fair=.2, epsilon=.05.
Weights are configurable through ConsensusConfig but were prespecified and NOT
tuned using validation in this experiment. Deficit weights adapt after each
selection so members with lower current predicted utility receive more weight.
The projected minimum and range address list-level worst-member utility and
dispersion, while the weighted mean retains group utility. This is a transparent
proposed heuristic, not a proof of fairness, Pareto optimality or research novelty.

For each output list, predicted member satisfaction S_u is the UNDISCOUNTED mean
of its ten individual hybrid scores. Report mean_u(S_u), min_u(S_u), and
range_u(S_u), macro-averaged across all simulated groups. Least-misery per-item
optimization does not guarantee the highest minimum list-level average.

## Group construction and held-out evaluation

For each size 2,3,4,5, create 500 unique random member sets from ALL 25,908
training user IDs. Sort IDs and use NumPy default_rng(SeedSequence([2026,size])).
Members are sampled without replacement within a group; repeated member sets
within a size are rejected. Users may recur across groups and sizes. No
validation-rating threshold or holdout availability influences formation.

All 2,000 groups' recommendations are constructed BEFORE validation.csv is
opened by the evaluator. This phase accepts only fitted training state and
training IDs. The existing BPR/hybrid selection previously used validation;
that inherited selection dependence is not erased by this separation.

Observed group relevance is the binary union of candidate-eligible attractions
with validation rating >=4 from at least one member. It does not imply all
members like the attraction. Missing ratings are unknown, not dislikes. No new
group preferences, ratings or labels are synthesized.

Group Recall@10 = number of retrieved unique relevant items / number of unique
eligible relevant items. Group NDCG@10 uses binary relevance and ideal DCG for
min(10, number of eligible relevant items). Macro-average over groups with at
least one eligible positive; methods use identical groups and denominators.
Groups without relevance still contribute to predicted utility summaries.

Validation positives blocked by ANY member's training history remain excluded.
Report their counts and secondary Recall with all observed union-positive items,
including blocked ones, in the denominator. This makes denominator effects visible.

An additional observed proxy summarizes binary retrieval of each member's single
eligible positive holdout. Only those members have a measured utility proxy;
all other members remain unknown. A miss means failure to retrieve that known
positive, not demonstrated dissatisfaction with the recommended list. Its
conditional mean/min/range are NOT full-group ground-truth satisfaction.

## Measured results and interpretation

Candidate-eligible group evaluation counts by size: 495,499,499,500 out of 500
each. Mean observed unique eligible positive items: 1.782,2.634,3.368,4.240.
Blocked positive member holdouts: 26,64,142,193. Only 2,2,5,12 groups respectively
have a candidate attraction positively observed by multiple members: group
agreement evidence is extremely sparse.

Adaptive Consensus has lower predicted disparity and higher predicted minimum
utility than average aggregation in all four sizes in this run, at lower mean
predicted utility. Its group Recall/NDCG are slightly higher in this simulated
validation sample; no statistical significance is established.

Observed fairness is NOT established. For size 5, the conditional observed
positive-member hit proxy has minimum 0 for both average and adaptive methods,
and its disparity increases from .474 to .514 under adaptive selection, despite
predicted disparity falling from .2744 to .1592. Predicted fairness cannot be
substituted for an independent observed fairness outcome.

## Files and limitations

config.json records the formula, fixed weights, seeds, construction/evaluation
rules and input hashes. data/processed/hawaii/group_validation_metrics.json has
all per-size/method summaries and limitations. group_validation_details.json
preserves actual member IDs, recommendations, predicted member utilities and
observed metrics for independent verification and paired comparisons.

Random groups are not observed friends or trips. Overlapping users make groups
dependent, so there are no independence-based confidence or significance claims.
There is only one validation interaction per member and no real group-satisfaction
ground truth. Full-graph 5-core eligibility uses future membership and favors
active users/popular items. Timestamp ties, cross-user temporal overlap and prior
validation tuning of the BPR hybrid remain. The test split is never accessed.
Hawaii is the first international HumSafar benchmark; these results do not prove
international generalization, actual human welfare fairness or production quality.
