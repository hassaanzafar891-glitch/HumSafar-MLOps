# HumSafar demo readiness

This is a verified **local Docker** demonstration. It does not retrain models,
read held-out ratings, execute a DVC stage, upload private artifacts or deploy
anything. Use explicit demonstration accounts; they are application fixtures,
not genuine ML training feedback.

## Before presenting

Run from `E:\GroupTravelMLOps` with Docker Desktop's Linux engine running:

```powershell
docker compose --env-file .local/docker.env config --quiet
docker compose --env-file .local/docker.env up -d --wait
docker compose --env-file .local/docker.env ps
```

Both services should be healthy. Open http://localhost:8080 and
http://localhost:8080/api/health. Swagger is at `/api/docs`. Full provisioning
and build instructions are in [DOCKER.md](DOCKER.md); an already provisioned
demo needs neither a model rebuild nor a new artifact download.

Keep `.local/docker.env`, historical user metadata, private model bundles and
invitation codes out of presentation logs/screenshots. Do not print resolved
Compose configuration; `config --quiet` validates without displaying secrets.
The database and read-only serving bundle are on E: and remain separate from
the native application's database and all ML data.

## Two-account product walkthrough

1. Use two independent browser profiles/contexts (or one normal and one private
   window). Register and log in each account; do not reuse real personal data.
2. The organizer creates a group. Privately share its invitation code and join
   from the second account. Show that both members appear in the group.
3. Each member saves their **own** preferences. Example demo inputs are
   `mountains hiking nature` and `lakes beautiful scenery`, Pakistan as a flexible
   preference, and the same availability window such as 2030-06-01 to 2030-06-10.
   These are example planning inputs, not observed dataset ratings.
4. Show the shared-date intersection. Explain flexible preferences versus
   mandatory restrictions: only members can change their own choices and
   mandatory conflicts are not silently relaxed. Budgets are stored with an
   unsupported-price-filter disclosure; dates do not establish venue availability.
5. Generate Pakistan group recommendations. Inspect genuine names, regions,
   categories and available licensed photos. Expand **How recommendations work**:
   these application users receive content/preference scores, not Hawaii-trained
   user embeddings. Do not describe similarity or AGC utility as a probability.
6. Both members vote on an eligible recommendation. Inspect totals and member
   votes. Explain that changing/withdrawing a vote is separate from itinerary
   management. An itinerary item must not appear merely because it received votes.
7. The organizer explicitly adds a selected recommendation to the itinerary,
   using a date within shared availability (for the example window, June 2).
   View the shared itinerary from the second account.

For a persistence demonstration:

```powershell
docker compose --env-file .local/docker.env restart backend frontend
docker compose --env-file .local/docker.env ps
```

Wait for health recovery, then verify group/votes/itinerary remain present.
Browser JWTs are in memory: a full page refresh may require login again; that
does not mean SQLite data was lost. Never reset the state directory for a demo.

## Monitoring and MLOps evidence

```powershell
.\.venv\Scripts\python.exe docker/inspect_metrics.py
docker compose --env-file .local/docker.env logs --tail 30 backend
.\.venv\Scripts\python.exe -m dvc dag
.\.venv\Scripts\python.exe -m dvc status
.\.venv\Scripts\python.exe -m dvc status -c
```

The metrics helper hides credentials and uses normal authentication. Show
request/HTTP error counts, latency histogram counts and recommendation counts.
`humsafar_recommendation_approach_info` identifies the last successful approach,
not model readiness. Metrics reset on backend restart; SQLite does not.
Safe structured logs use route templates, never private path values or preferences.

The six-stage DVC DAG and synchronized private cache/remote are lineage evidence,
not proof of a freshly executed pipeline. Never set the training execution gate
or run `dvc repro` during the demo. Test/interactions are uncached producer outputs,
and the completed one-shot test driver is outside automatic pipeline execution.

MLflow has seven existing FINISHED runs: five clearly tagged historical validation
imports and two connectivity checks. Their artifact directories are accessible;
there is no installed/advertised MLflow web UI or new final-test MLflow run.
To show the existing run count without modifying tracking history:

```powershell
.\.venv\Scripts\python.exe -B -c "import sqlite3; c=sqlite3.connect('file:.local/mlflow/tracking.db?mode=ro&immutable=1',uri=True); print(c.execute('SELECT status,COUNT(*) FROM runs GROUP BY status').fetchall()); c.close()"
```

Show the existing CI [successful monitoring-commit run](https://github.com/hassaanzafar891-glitch/HumSafar-MLOps/actions/runs/42589415223).
Check the exact commit SHA of each later GitHub Actions run; a passing prior run
does not verify later changes. CI uses public fixtures and no held-out evaluation.

## Research results walkthrough — saved report only

Open [FINAL_EVALUATION.md](FINAL_EVALUATION.md), not the test driver. Its JSON is
at `data/processed/hawaii/final_test_evaluation.json`; the completed exclusive
ledger is `.local/step30_2_test_evaluation.json`. Do not rerun or delete the ledger.

Explain the four frozen individual ranking comparisons: hybrid Recall@10
0.221146 and NDCG@10 0.118196 over 23,844 relevant-holdout users, with 2,064
excluded below-threshold holdouts. No sampled negatives or test-driven tuning.

Then separate the group evidence:

- Predicted mean/minimum/range use normalized model scores over all members.
  AGC improved predicted minimum and disparity, with a mean-utility tradeoff.
- Observed proxies use binary retrieval of one eligible positive test holdout
  per observed member. Missing member-item ratings are unknown. These proxies
  were mixed; AGC group NDCG was lower than average aggregation at every size.
- The 500 simulated groups at each size 2/3/4/5 overlap in users. Full-graph
  selection, timestamp ties, single-item holdouts and sparse relevance limit
  interpretation. No real-human fairness or worldwide-generalization guarantee.

## Automated checks verified for Step 30.3

| Check | Result |
| --- | --- |
| Docker HTTP two-account workflow | 19 requests passed; two votes and explicit shared itinerary |
| SQLite persistence | Passed after restarting both HumSafar containers |
| Docker browser tests | 3 passed: full workflow, mobile layout and photographs |
| Lightweight Python/monitoring suite | 24 passed |
| Existing API regressions | 17 passed |
| Frontend unit tests | 19 passed |
| Frontend production build | Passed |
| Monitoring verification | 8 counter/latency checks plus authentication and sensitive-data checks passed |
| DVC | Git-integrated; pipeline up to date; cache/remote synchronized |
| MLflow | 7 existing finished runs; historical artifact directories accessible |
| Hosted CI for `429f5ad` | Success; run 42589415223 |

Reproducible application-only checks:

```powershell
.\.venv\Scripts\python.exe docker/verify_workflow.py --restart
.\.venv\Scripts\python.exe docker/verify_monitoring.py
.\.venv\Scripts\python.exe -m unittest discover -s tests/ci -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_api.py -v
cd frontend
npm test
npm run build
npx playwright test --config playwright.docker.config.js
```

Run browser tests after any restart helper finishes. Avoid broad research-test
discovery, which can read private datasets or fit models. No Step 30.3 command
requires running final test evaluation. No deployment is part of this readiness
check; TLS, public access, production backups and international interaction-data
expansion remain separate work.
