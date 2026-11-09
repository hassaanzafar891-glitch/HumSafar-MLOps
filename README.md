# HumSafar

**An international, adaptive fairness-aware group travel recommendation system
using machine learning and MLOps.**

HumSafar lets friends create a private travel group, save their own interests
and restrictions, coordinate dates, compare group recommendations, vote, and
explicitly build a shared itinerary. React/Vite connects to FastAPI through
Nginx; SQLAlchemy and persistent SQLite store application state.

The research benchmark uses real Hawaii attraction ratings. The application
also supports Pakistan content recommendations and international hotel metadata.
**Newly registered application users receive preference/content matching, not
historical Hawaii user embeddings or worldwide trained personalization.**

## Local Docker demo

For this already provisioned local workspace, run from the project root:

```powershell
docker compose --env-file .local/docker.env up -d --wait
docker compose --env-file .local/docker.env ps
```

- Website: http://localhost:8080
- Backend health: http://localhost:8080/api/health
- Swagger: http://localhost:8080/api/docs
- Authenticated metrics: http://localhost:8080/api/metrics

Use two accounts: **register → log in → create/join a group → save each member's
preferences → generate group recommendations → vote → explicitly add an itinerary
item**. Both members can view the shared itinerary. Voting never automatically
adds a stop. Mandatory restrictions are enforced; flexible preferences can
consider alternatives. Shared dates describe member availability, not venue or
booking availability. Budgets are saved but cannot filter prices absent from
the catalog.

For a fresh checkout, obtain authorized private artifacts and follow
[DOCKER.md](DOCKER.md). The five-file serving bundle, JWT environment file,
SQLite state and Linux wheels live under ignored `.local/` directories on E:.
They are not embedded in Git or Docker images. A source checkout alone does not
provide datasets, weights or credentials. Never overwrite an existing secret
or native database just to start the demo.

Repeat the local application checks without training or test evaluation:

```powershell
.\.venv\Scripts\python.exe docker/verify_workflow.py --restart
.\.venv\Scripts\python.exe docker/verify_monitoring.py
cd frontend
npx playwright test --config playwright.docker.config.js
```

These commands create explicit local verification accounts/groups. The workflow
helper restarts only HumSafar when `--restart` is supplied and verifies SQLite
persistence. Browser tests use the running Docker application. Neither creates
ML training interactions or accesses held-out ratings.

## Actual catalog and recommendation coverage

| Source | Listings | Scope and supported recommendation mode |
| --- | ---: | --- |
| Pakistan tourism catalog | 69 attractions | Saved TF-IDF content matching |
| Google Local Hawaii | 1,512 attractions | Frozen BPR hybrid for compatible historical training identities; preference matching for new app users |
| Webis TripAdvisor 2014 | 12,044 hotels | Metadata preference matching; no trained hotel personalization or booking |

The unified catalog contains **13,625 source listings**, with **117 named country
or territory labels** and **726 listings with unknown country**. Labels include
territories/historical source names and are not a verified sovereign-country
count. Cross-source listings are not resolved into unique physical entities.
International hotel coverage does not imply international attraction coverage.
Missing coordinates, descriptions and photographs remain missing or use clear
fallbacks; prices, ratings, availability and locations are never invented.

## Final held-out Hawaii results

The approved Step 30.2 test evaluation ran **once**, using frozen artifacts and
full-catalog ranking with training-history exclusions. Of 25,908 test users,
**23,844** had a rating >=4 and were eligible; **2,064** were excluded because
their only holdout was below that threshold. Missing ratings remain unknown.

| Frozen model | Recall@10 | NDCG@10 |
| --- | ---: | ---: |
| Training popularity | 0.109629 | 0.052922 |
| Matrix Factorization | 0.002600 | 0.001074 |
| Pure BPR | 0.217623 | 0.115599 |
| **75% BPR + 25% popularity** | **0.221146** | **0.118196** |

These are ranking metrics, not rating accuracy or prediction probabilities.
MF was originally selected for rating RMSE. No test-driven tuning, retraining
or serving-model replacement followed the final evaluation.

Adaptive Group Consensus was evaluated against average and least-misery
aggregation using the same fixed groups and candidate sets: 500 groups per
size 2/3/4/5, seed 2026, and fixed weights 0.5/0.3/0.2. It improved **predicted
minimum utility and predicted disparity** at every group size, but had lower
group NDCG than average aggregation at every size. **Observed positive-holdout
retrieval proxies were mixed**; these findings do not establish better human
satisfaction, interpersonal welfare or a formal fairness guarantee.

All group quality, predicted utility and observed proxy tables are in
[FINAL_EVALUATION.md](FINAL_EVALUATION.md). The reviewed
[machine-readable aggregate report](data/processed/hawaii/final_test_evaluation.json)
is versioned without interaction records or private identifiers; the completed ledger is
`.local/step30_2_test_evaluation.json`. **Do not rerun held-out evaluation.**

Limitations include full-graph 5-core selection and latest-review bias,
per-user rather than global chronology, timestamp ties, one heldout per user,
validation visits remaining candidates under the approved training-only
exclusion protocol, sparse group relevance and overlapping simulated groups.
Hawaii results do not establish international or new-user generalization.

## Architecture, MLOps and verification

- [Architecture](ARCHITECTURE.md): routing, identity boundaries, group consensus,
  persistence and the separation of research evaluation from application use.
- [MLOps workflow](MLOPS.md): Git-integrated DVC, local MLflow, artifact approval,
  validation versus final evaluation, and CI.
- [Pipeline provenance](PIPELINE_REPRODUCIBILITY.md) and
  [external raw-input procedure](RAW_INPUTS.md).
- [Docker operations](DOCKER.md) and [monitoring/privacy](MONITORING.md).
- [Backend API](backend/API.md), [frontend](frontend/README.md), and
  [licensed photographs](frontend/PHOTOGRAPHS.md).

GitHub Actions runs lightweight Python/API tests plus frontend tests/build,
without private data, model training or held-out evaluation. The last verified
hosted run for monitoring commit `429f5ad` [passed](https://github.com/hassaanzafar891-glitch/HumSafar-MLOps/actions/runs/42589415223).
This is evidence for that commit. Check each subsequent run's commit SHA in
[GitHub Actions](https://github.com/hassaanzafar891-glitch/HumSafar-MLOps/actions)
before claiming later changes have passed hosted CI.

Python 3.12, CPU PyTorch 2.6.0+cpu and Node 22 are used. Existing requirement
files, the frontend lockfile, Docker constraints and recorded runtime versions
describe the environment; a complete cross-platform transitive lock is not
claimed. Private DVC/model access is required separately.

No AWS deployment, payments, bookings, production TLS or cloud-operated model
registry is included. Docker is a verified local demo, not a completed public
production deployment.
