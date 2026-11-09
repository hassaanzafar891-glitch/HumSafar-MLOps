# Step 30.2 ? final held-out Hawaii test evaluation

The approved real test evaluation executed once. Frozen artifacts were loaded without training, tuning, model selection, validation rescoring, or serving changes. The exclusive ledger is `.local/step30_2_test_evaluation.json`; it is completed and blocks accidental reruns. Do not delete it to repeat scoring.

## Protocol and counts

- Splits: 182,769 training, 25,908 validation, 25,908 test interactions; 25,908 training users and 1,512 attractions.
- Individual test denominator: **23,844** users with a rating >=4; **2,064** below-threshold users excluded rather than treated as dislikes.
- Full catalog minus complete training history; validation visits remain candidates under the approved frozen protocol. No sampled negative candidates.
- Exact score ties use original attraction-ID ascending order. MF ranks raw unclipped scores. BPR and hybrid use per-user training-unseen min-max normalization.
- Hybrid weights fixed at 75% BPR / 25% log-popularity. BPR: factors=32, regularization=0.01, learning_rate=0.005, epochs=15, batch_size=4096, seed=2026.
- The groups match the audited Step 24 member lists exactly: 500 groups each of sizes 2/3/4/5, seed=2026, formed using training users only before test rows were parsed.
- AGC weights average/minimum/fairness=0.5/0.3/0.2, epsilon=0.05, top_k=10. All methods share candidates excluding every member training history. Individual normalization precedes group restriction, without rescaling.

## Individual ranking

| Model | Recall@10 | NDCG@10 | Hits | Eligible | Excluded |
| --- | ---: | ---: | ---: | ---: | ---: |
| popularity | 0.109629257 | 0.052921515 | 2614 | 23844 | 2064 |
| matrix_factorization | 0.002600235 | 0.001074476 | 62 | 23844 | 2064 |
| bpr | 0.217622882 | 0.115599350 | 5189 | 23844 | 2064 |
| bpr_popularity_hybrid | 0.221145781 | 0.118195623 | 5273 | 23844 | 2064 |

The frozen hybrid outperformed these frozen comparisons on this test set. MF was selected for rating RMSE, not ranking. These findings do not authorize new tuning or model replacement.

## Group denominators and blocked relevance

Group relevance is the union of candidate-eligible test attractions rated >=4 by at least one member, not unanimous preference. Quality metrics macro-average over groups with nonempty eligible relevance. Each size contains 500 groups.

| Size | Evaluable groups | Empty relevance groups | Positive member holdouts | Blocked positives | Eligible member holdouts | Mean candidates | Minimum candidates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 499 | 1 | 940 | 29 | 911 | 1497.958 | 1436 |
| 3 | 500 | 0 | 1407 | 75 | 1332 | 1491.366 | 1426 |
| 4 | 500 | 0 | 1847 | 141 | 1706 | 1485.406 | 1423 |
| 5 | 500 | 0 | 2325 | 209 | 2116 | 1478.270 | 1427 |

An item visited by any member in training is blocked even if another member has a positive test holdout. Secondary recall below retains blocked positive items in the denominator. The reused group summarizer retains a legacy `members_missing_validation` field in the JSON; for this report it checks the **test** lookup. All values are zero.

## Group recommendation quality

| Size | Method | Group Recall@10 | Group NDCG@10 | Recall including blocked positives |
| --- | --- | ---: | ---: | ---: |
| 2 | average | 0.182364729 | 0.112134381 | 0.179358717 |
| 2 | least_misery | 0.143286573 | 0.090809995 | 0.140280561 |
| 2 | adaptive_consensus | 0.179358717 | 0.112066878 | 0.176352705 |
| 3 | average | 0.153666667 | 0.101522078 | 0.142333333 |
| 3 | least_misery | 0.115333333 | 0.076501478 | 0.107000000 |
| 3 | adaptive_consensus | 0.150666667 | 0.098194999 | 0.140333333 |
| 4 | average | 0.135333333 | 0.102244642 | 0.125166667 |
| 4 | least_misery | 0.110000000 | 0.079389534 | 0.102500000 |
| 4 | adaptive_consensus | 0.131166667 | 0.095458616 | 0.121500000 |
| 5 | average | 0.119566667 | 0.098864049 | 0.110900000 |
| 5 | least_misery | 0.093633333 | 0.076194083 | 0.087400000 |
| 5 | adaptive_consensus | 0.119766667 | 0.098122579 | 0.110600000 |

## Predicted utility ? not observed satisfaction

For each member, utility is the mean normalized hybrid score over ten items. Summaries are macro-averages of each group mean/minimum/member range, over all 500 groups per size. These are the same score proxies optimized by aggregation, not independent human-fairness labels.

| Size | Method | Mean utility | Minimum member utility | Member disparity range |
| --- | --- | ---: | ---: | ---: |
| 2 | average | 0.851975360 | 0.814573268 | 0.074804183 |
| 2 | least_misery | 0.839409586 | 0.805171849 | 0.068475474 |
| 2 | adaptive_consensus | 0.849517943 | 0.838604559 | 0.021826768 |
| 3 | average | 0.821710874 | 0.702241682 | 0.198588951 |
| 3 | least_misery | 0.793751586 | 0.724118057 | 0.135172741 |
| 3 | adaptive_consensus | 0.811958934 | 0.771507892 | 0.081927477 |
| 4 | average | 0.807325437 | 0.654529077 | 0.248554125 |
| 4 | least_misery | 0.773966135 | 0.682401907 | 0.176988124 |
| 4 | adaptive_consensus | 0.795959290 | 0.730991142 | 0.126886441 |
| 5 | average | 0.796242543 | 0.625556380 | 0.274415586 |
| 5 | least_misery | 0.761652117 | 0.653153867 | 0.209855641 |
| 5 | adaptive_consensus | 0.785477494 | 0.699443466 | 0.159244910 |

## Observed positive-holdout retrieval proxies

Only members with candidate-eligible positive test holdouts are included. Their hit utility is 1 if that single positive appears and 0 otherwise. Unknown or blocked members are not assigned dislike/dissatisfaction values. Summaries macro-average across evaluable groups.

| Size | Method | Mean member hit | Minimum member hit | Member hit disparity range |
| --- | --- | ---: | ---: | ---: |
| 2 | average | 0.182364729 | 0.052104208 | 0.260521042 |
| 2 | least_misery | 0.143286573 | 0.042084168 | 0.202404810 |
| 2 | adaptive_consensus | 0.179358717 | 0.046092184 | 0.266533066 |
| 3 | average | 0.154333333 | 0.022000000 | 0.332000000 |
| 3 | least_misery | 0.116000000 | 0.016000000 | 0.248000000 |
| 3 | adaptive_consensus | 0.151333333 | 0.024000000 | 0.314000000 |
| 4 | average | 0.136666667 | 0.008000000 | 0.390000000 |
| 4 | least_misery | 0.110500000 | 0.002000000 | 0.336000000 |
| 4 | adaptive_consensus | 0.132666667 | 0.008000000 | 0.380000000 |
| 5 | average | 0.119500000 | 0.000000000 | 0.426000000 |
| 5 | least_misery | 0.094733333 | 0.000000000 | 0.344000000 |
| 5 | adaptive_consensus | 0.120166667 | 0.000000000 | 0.428000000 |

AGC improved predicted minimum utility and reduced predicted disparity relative to both alternatives at every group size, with lower predicted mean utility than average aggregation. Group NDCG was lower than average aggregation at all sizes; group Recall was lower at sizes 2/3/4 and slightly higher at size 5. Observed retrieval-proxy fairness is mixed: no consistent improvement in the observed minimum or disparity, and no human-satisfaction or formal fairness guarantee is established.

## Verification and reproducibility

- Nine synthetic-only tests passed before real scoring, covering split structure, timestamps and ties, exclusion, deterministic order, relevance/denominators, group eligibility and blocked positives, forbidden fitting/IO calls, and rerun blocking.
- Real preflight passed: original split hashes, mapping/catalog compatibility, frozen BPR/MF/baseline checksums, exact train-only histories/popularity, fixed AGC configuration and exact audited groups, disjoint valid chronological splits, and at least ten candidates per user/group.
- All 38 protected input/source files remained unchanged, including every existing validation output and serving artifact. No held-out test evaluation ran before the synthetic/integrity gates passed.
- The driver calls pure `ranking_metrics`, BPR `evaluate` with only the two fixed comparison weights, baseline `recommend`, and group `recommend_group`/`observed_metrics`/`summarize`. It never calls training/tuning `run()` or `fit()`.
- New files: `backend/evaluate_final_test.py`, `tests/test_final_evaluation.py`, this document, and the reviewed aggregate `data/processed/hawaii/final_test_evaluation.json`. An exact-path Git ignore exception includes only that JSON report; its original bytes are preserved by `.gitattributes`. The private ledger and console transcript remain ignored under `.local/`.
- The report records SHA-256 hashes for every protected input and relevant source file. It contains no raw user IDs or group membership lists. Group membership is recorded by a digest and reproducible generation rule.
- The frozen registry manifest is preserved as its pre-test reference, including its old `test_evaluated:false` field. The final report and completed ledger are authoritative that Step 30.2 has now evaluated test; do not infer untouched test status from the old manifest.
- Synthetic checks can be rerun with `python -m unittest discover -s tests -p test_final_evaluation.py -v`; do not rerun real scoring. These tests are outside the default data-free CI directory because legacy model loaders import CPU PyTorch.

- Group membership SHA-256: `00eef8c54bffa06ec24ab421b97a83310b8453d9255cab200832d448cd374bff`.
- Runtime: 46.70 seconds, including real preflight/group construction/scoring; synthetic gate and report serialization are outside that timer.
- Software: Python 3.12.10, NumPy 2.5.4, pandas 3.1.1, PyTorch 2.6.0+cpu; BLAS limited to one thread.
- Base Git commit: `429f5ad84f55c0a974b7dfc0c31afbeca86e31c4`; dedicated evaluation code was uncommitted and is bound by source hashes in the report.

## Remaining limitations

- Full-graph 5-core and latest-review deduplication expose future cohort membership and create selection bias.
- Per-user split is not a global temporal cutoff; timestamp ties do not prove strict chronology.
- One heldout item per user and unknown missing ratings limit observed relevance.
- Validation visits remain candidates under the approved train-only exclusion protocol.
- Simulated groups overlap; groups are not independent observations or actual friend groups.
- Predicted fairness uses optimized model scores, not independently observed human satisfaction.
- Union relevance is not unanimous preference; conditional observed proxies omit unobserved members.
- Test results must not trigger new tuning; a future changed model requires a new evaluation plan.
- Hawaii historical-ID benchmark does not establish international or new-application-user personalization.
