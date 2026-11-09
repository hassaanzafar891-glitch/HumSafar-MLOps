# Lightweight local monitoring

The API exposes Prometheus text-format metrics and structured JSON request logs.
There is no Prometheus server, Grafana, external telemetry service or additional
Python runtime dependency. Recommendation algorithms, model files, data splits,
authentication, voting and itinerary rules are unchanged.
The exporter follows the [Prometheus text exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/),
including grouped metric families and cumulative histogram buckets.

## Inspect metrics

Docker endpoint: `http://localhost:8080/api/metrics`.
Native API endpoint: `/metrics`. Both require an existing application's bearer
JWT through the unchanged authentication dependency. Anonymous, expired and
logged-out tokens are rejected. Responses use `Cache-Control: no-store`.
The endpoint is omitted from Swagger; omission is not its security protection.

Use an existing local account without putting credentials into shell history:

```powershell
.\.venv\Scripts\python.exe docker/inspect_metrics.py
```

The helper prompts for email and password with hidden input, keeps the returned
token only in memory, and prints aggregate metrics. It saves no credentials or
responses. It uses the normal login endpoint, so normal login rate limits apply.
For programmatic scraping, supply an existing valid bearer token privately.
Tokens expire normally; the exporter does not provide a new authentication path.

Compose publishes Nginx only on `127.0.0.1:8080`; the backend has no host port.
Any authenticated local application account may view these aggregate counters;
there is no invented administrator role. Do not bind to a public interface or
remove JWT protection. Public deployment requires a separate monitoring-access
review. For native use, bind Uvicorn to `127.0.0.1` as well.

## Metrics and interpretation

| Family | Meaning |
| --- | --- |
| `humsafar_http_requests_total` | Completed API requests by bounded HTTP method, framework route template and status. |
| `humsafar_http_errors_total` | Responses with status at least 400, including permission and validation errors. |
| `humsafar_http_request_duration_seconds` | Cumulative latency histogram with `_bucket`, `_count` and `_sum`, measured using a monotonic clock through ASGI response sending. |
| `humsafar_recommendation_requests_total` | POST attempts to group/individual recommendation-generation routes, including requests rejected before scoring. |
| `humsafar_recommendation_failures_total` | Those recommendation requests returning HTTP status at least 400. |
| `humsafar_recommendation_approach_requests_total` | Successful requests using each distinct observed approach and aggregation; one count per approach per request. |
| `humsafar_recommendation_approach_info` | Approach identifiers in the last successful recommendation request. |
| `humsafar_recommendation_aggregation_info` | Last successful recommendation's individual/average/least-misery/adaptive-consensus method. |
| `humsafar_monitoring_start_time_seconds` | Process-local registry creation time, useful to identify counter resets. |

Observed approach identifiers come from the existing response payload:
`metadata_preference`, `pakistan_tfidf_content`, or
`hawaii_personalized_hybrid`. Unknown future identifiers use the bounded `other`
label. The initial approach/aggregation is `not_observed`. The last successful
approach remains visible after a failed request; it is **not** a model-readiness
check, a deployed-model promotion record, a quality score or a claim that a new
application user has Hawaii history. Multiple group modes are deduplicated per
request. No user/member IDs appear in labels.

Latency includes authentication, database work and serialization; it is not
model-only inference time. Histogram bounds are 5, 10, 25, 50, 100, 250 and
500 milliseconds, then 1, 2.5, 5 and 10 seconds plus infinity. Buckets are
cumulative. For a route, `_sum / _count` is the observed mean in seconds;
subtract two snapshots to obtain interval counts/means. No percentiles or
accuracy claims are fabricated from this small local workload.

Metric scrapes, health checks and authorization failures are counted too.
A scrape's own count is recorded after its response is rendered and therefore
appears in a subsequent snapshot. Unknown URLs share `__unmatched__`; unusual
HTTP methods share `OTHER`, avoiding user-controlled label cardinality.
Proxy/static-file requests that never reach FastAPI are outside these metrics.

## Privacy-safe logs

```powershell
docker compose --env-file .local/docker.env logs --tail 50 backend
```

Request records contain only UTC time, level, event name, HTTP method, route
**template**, status, duration and bounded recommendation identifiers. They do
not contain raw URLs, query strings, path values, client addresses, headers,
bodies, email addresses, group/member/destination IDs, preferences, passwords,
JWTs or invitation codes. These deliberately limited fields support aggregate
diagnosis without user activity records.

Docker disables raw Uvicorn and Nginx access logs. Nginx error output is also
disabled because its raw errors may include private URLs. Uvicorn and fallback
Python loggers use a formatter that discards message text, exception values and
tracebacks, retaining only severity and a generic server event. This trades
detailed production debugging for privacy; investigate local unit tests and
health/metrics when deeper diagnosis is needed. Logs are not security audit
trails and contain no request correlation IDs.

Native startup must explicitly use the same safe logging configuration:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --log-config docker/backend/logging.json
```

The monitoring formatter does not sanitize unrelated tools, native frontend dev
server logs, third-party handlers configured outside this app, or old logs made
before this feature. Do not print private resolved Compose configuration or
enable raw debug/access logs during the demo.

## Reset and retention

Metrics live in memory in the existing **single backend worker**. They reset on
backend restart/recreation, separately from persistent SQLite users/groups and
model files. They are not persisted, aggregated across processes, or exported
to a remote service. Do not add workers and assume these counters combine.

Compose's existing Docker JSON log files are bounded to 10 MB each, three files
per container. Logs survive a restart of that container; recreating it starts
a new container log. There is no additional log bind mount or database table.
Old pre-monitoring containers/logs are not modified or deleted by this work.

## Local MLOps evaluation demonstration

After building the changed images and starting HumSafar:

```powershell
docker compose --env-file .local/docker.env build
docker compose --env-file .local/docker.env up -d --wait
.\.venv\Scripts\python.exe docker/verify_monitoring.py --restart
.\.venv\Scripts\python.exe docker/verify_workflow.py --restart
.\.venv\Scripts\python.exe docker/inspect_metrics.py
```

The monitoring check creates clearly named local fixture users/groups, captures
before/after metrics, makes health and failed requests, generates a genuine
content recommendation and verifies count/latency/approach updates. It checks
logs and metrics for sensitive fixture markers without printing them. With
`--restart`, it restarts only HumSafar's backend, verifies metrics reset, and
checks that the existing token and SQLite group still work. These fixture
preferences are application tests, never training labels or model feedback.

The separate two-account workflow verifies authentication, group membership,
preferences, recommendations, votes and explicit shared itinerary persistence.
Only HumSafar services are restarted. No training, model selection, dataset
regeneration or held-out test access occurs.

Tests: `python -m unittest discover -s tests/ci -v` includes exporter accounting,
histogram/concurrency, authentication/revocation, bounded labels, error handling,
privacy-safe formatting and Docker logging configuration. No real data or
model artifacts are required for that suite.

## Verified local results

- GitHub Actions for `e87684e` completed successfully:
  [run 42512351439](https://github.com/hassaanzafar891-glitch/HumSafar-MLOps/actions/runs/42512351439).
- All 24 lightweight tests passed, including eight monitoring tests.
- All 17 existing API regression tests passed.
- Both updated Docker images built using cached CPU dependencies; both services
  are healthy. No new monitoring runtime dependency was installed.
- Docker verification passed eight counter/latency checks, authenticated
  access, observed approach identification, HTTP/recommendation failure counts,
  and absence of sensitive fixture values from metrics and logs.
- Backend restart reset metrics and the observed approach while preserving
  authentication and the SQLite group.
- The 19-request two-account workflow passed with two votes and a shared
  itinerary; persistence survived restarting both HumSafar services.

These results describe the small local verification workload, not production
load testing or recommendation-quality evaluation. No commit or push was made
for the monitoring changes.
