# HumSafar REST backend (Step 26)

This document retains the original API implementation account. For current
product coverage, Docker startup, privacy-safe monitoring and the completed
held-out evaluation, start with [README](../README.md),
[architecture](../ARCHITECTURE.md) and the [demo guide](../DEMO.md).
The frontend is now implemented; no deployment or new-user historical-identity
linkage is implied by the older step-specific statements below.

FastAPI routes wrap the existing recommendation service and Step 24 consensus
implementation. SQLAlchemy ORM persists application data separately from all
datasets and model artifacts. No model fitting, test-split access, historical
identity linkage, live booking, payments, frontend or deployment is implemented.

## Windows local startup

Run PowerShell in E:\GroupTravelMLOps with the existing ML virtual environment:

```powershell
.venv\Scripts\python.exe -m pip install -r backend\requirements-api.txt
# Only on initial setup if .env does not already exist; never replace a secret.
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into JWT_SECRET_KEY in .env. Do not use the command's
example text as a secret. Keep .env private; it and backend/var are ignored by
.gitignore. No real secret is supplied in .env.example. Then:

```powershell
.venv\Scripts\python.exe -m backend.api.init_db
.venv\Scripts\python.exe -m uvicorn backend.api.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --log-config docker/backend/logging.json
```

Swagger: http://127.0.0.1:8000/docs ; ReDoc: /redoc ; schema: /openapi.json.
Register via /auth/register. Login takes URL-encoded username=email and password
(not JSON). Swagger's Authorize button uses this OAuth2 password flow. Other
private endpoints accept Authorization: Bearer <access_token>. Keep tokens out
of URLs and logs. No CORS wildcard is enabled; future frontend origins need an
explicit decision. HTTPS is needed before any remote use; this is a local app.

DATABASE_URL defaults to an absolute backend/var/humsafar.db path when omitted.
.env.example uses sqlite:///backend/var/humsafar.db, relative to project root.
The DB file persists across process restarts; SQLite foreign keys are enabled.
For later PostgreSQL, configure postgresql+psycopg://... and install psycopg.
The ORM uses portable JSON, dates and constraints, but PostgreSQL has NOT been
integration-tested or deployed in this step. API requirements are additions to
the existing ML environment; keep its sklearn version compatible with saved
TF-IDF artifacts. Do not replace those artifacts to resolve a version mismatch.

## Schema initialization and evolution

initialize_schema creates v1 only in an EMPTY database, records schema_info=1,
and verifies version/table presence on repeat runs. Startup does the same when
AUTO_INIT_DB=true; set it false to require prior CLI initialization. Existing
unversioned or differently versioned databases fail rather than being silently
modified, dropped or reseeded. No real users or demo actions are seeded into the
default database. For a future schema change, back up the database and add an
explicit migration (e.g. Alembic) before changing the version. create_all is an
initialization process, not an upgrade migration mechanism.

| Table | Relationships and purpose |
|---|---|
| users | UUID identity, canonical email, Argon2id hash, profile, token version |
| travel_groups | Owner -> users; hashed invitation, revision, archive flag |
| group_memberships | Composite group/user primary key; owner/member role |
| member_preferences | Composite FK to membership; validated preference JSON |
| group_recommendations | FK to group/creator; revision, filters, warnings, result snapshot |
| votes | FK to recommendation+group and membership; one vote per user/run |
| itinerary_items | FK to recommendation+group/creator; selected destination snapshot, position/date/notes |
| schema_info | Version ledger, no application preferences or model data |

Removing membership cascades its preferences and votes. Group deletion cascades
memberships, preferences, recommendations, votes and itinerary items. Registered
users persist. No recommendation is itself an observed user rating, and votes
and demo actions are never automatically used as ML labels.

## Endpoints

| Method | Path | Access/behavior |
|---|---|---|
| GET | /health | Public health and schema version |
| GET | /catalog/coverage | Public actual source/type/country coverage |
| GET | /catalog | Public paginated catalog; country, kind, limit, offset |
| POST | /auth/register | Email, display_name, password (12-128 chars) |
| POST | /auth/login | Form username=email/password; short-lived JWT |
| POST | /auth/logout | Revoke all current tokens for authenticated user |
| GET/PATCH | /users/me | Own profile only |
| POST | /users/me/password | Current-password check; change and revoke tokens |
| GET/POST | /groups | Own groups / create group, returning invitation once |
| POST | /groups/join | Join by invitation_code in JSON body |
| GET/PATCH/DELETE | /groups/{g} | Member read; owner rename/archive/delete |
| POST | /groups/{g}/invitation | Owner issues fresh code; old codes invalidated |
| GET | /groups/{g}/members | Members only; no emails, hashes or invitation codes |
| DELETE | /groups/{g}/members/{u} | Owner removes member, or member leaves |
| POST | /groups/{g}/transfer-ownership | Owner transfers to an existing member |
| GET/PUT | /groups/{g}/preferences/me | Read/save ONLY own group preferences |
| POST | /groups/{g}/recommendations | All-member average/least-misery/AGC snapshot |
| POST | /groups/{g}/recommendations/individual | Own saved-preference recommendations |
| GET | /groups/{g}/recommendations | Member-only saved runs and current/stale flag |
| GET | /groups/{g}/recommendations/{r} | Member-only recommendation snapshot |
| PUT/DELETE | /groups/{g}/recommendations/{r}/vote | Cast/change/withdraw own single ballot |
| GET | /groups/{g}/recommendations/{r}/votes | Members see counts, including zero-vote choices |
| GET/POST | /groups/{g}/itinerary | Members read; owner adds a recommended item |
| PATCH/DELETE | /groups/{g}/itinerary/{i} | Owner edits/removes planned item |

The owner cannot leave until transferring ownership or deleting the group.
Ownership transfers and owner-initiated removals invalidate prior invitations;
the owner can issue a new shareable code through the invitation endpoint.
Membership checks return 404 for outsiders; owner-only violations return 403.
Unknown inputs (including user_id or historical identity injection) return 422.
Cross-group recommendation/itinerary IDs cannot bypass membership checks.

## Preferences and recommendation semantics

Preferences contain interests, free_text, optional budget_min/budget_max/currency,
preferred_countries, preferred_regions, preferred_destination_ids and paired
start_date/end_date. Budgets are nonnegative ordered decimals; currency has
three-uppercase-letter format, not verified exchange-rate support. Lists and
text are bounded. Unknown destination IDs are rejected.

Geographic constraints use metadata: requested scope/kind/country plus the
intersection of every participating member's nonempty country/region/destination
lists. Lists express alternatives within a member, and intersections express
compatibility across members. Missing source geography is never inferred. Source
country labels/case can be obtained from /catalog/coverage; explicit source alias
mapping is used for saved country preferences. An impossible intersection or
unsupported catalog scope returns 409 no_compatible_candidates, not unrelated
substitute destinations. Interests/free_text provide soft metadata/text scoring,
not a guaranteed hard taxonomy match.

ALL group members must save their own preferences before group generation, and
each needs nonempty interests/free_text. Single-member groups can request their
individual recommendations; consensus requires at least two members. The request
selects scope (catalog/hawaii/pakistan), kind, optional country, method and top_k.
Actual routes/modes come from recommendation_service.py: Pakistan uses saved
TF-IDF; new application users in Hawaii/international catalogs use metadata
preference matching. Public app requests cannot link themselves to historical
Google users, and registration NEVER creates or copies Hawaii factors. No model
is fitted on preferences or votes. Identity namespace and compatibility boundaries
remain intact. Utilities are predicted/matched scores, not probabilities or
observed human satisfaction; the Step 24 fairness limitations still apply.

Responses explicitly include notices:

- budget_filter_unsupported: saved budget/currency only; no comparable trip
  costs, budget filtering, price guarantees, or currency conversion.
- date_availability_unsupported: saved dates only; no attraction opening/capacity
  or live availability filtering. Nonoverlapping member windows add a conflict
  notice; date conflicts are not silently resolved.
- new_application_users: no automatic historical-user personalization.

Dates assigned to itinerary items must fall inside every supplied member travel
window. This is a user-calendar constraint, NOT confirmation that a venue is
open/bookable. Undated itinerary entries remain unscheduled. Existing itineraries
are owner-managed snapshots and are not silently changed when preferences change.

Preference changes and membership changes advance the group revision. Previously
generated recommendations remain readable but stale; new votes and itinerary
selections against stale recommendations return 409 until regeneration. Saved
votes are advisory: an owner explicitly chooses among current recommendations
for the itinerary. The API does not falsely infer unanimous approval or perform
automatic route optimization, booking or payment.

Individual recommendation runs cannot be used for group ballots or itinerary
selection; an all-member group run is required so individual suggestions cannot
bypass the other members' saved constraints.

## Authentication and operational boundaries

Passwords use pwdlib's recommended Argon2id hashing (unique salt). JWTs are HS256
with a mandatory generated environment secret; issuer/audience/subject/expiry/
issued-at/token-ID/version are checked. Database token-version checks revoke all
tokens on logout/password changes. No plaintext passwords or shareable invitation
codes are stored. Invitations have 256 bits of entropy and are stored as SHA-256
digests. Sensitive responses use no-store; validation errors omit input values.

Login/registration/invitation joining have bounded in-process IP attempt limits.
These are local-development controls, not distributed production abuse protection.
There is no refresh token, email verification/recovery, MFA, historical identity
linking or external identity provider in this step. Access tokens expire after
30 minutes by default. New data still needs explicit feedback governance and
model evaluation before any future personalization training. Future deployment
requires managed secrets, transport security, backups and shared rate limiting;
no remote deployment was performed.

## Tests and complete workflow demonstration

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_api.py -v
.venv\Scripts\python.exe -m backend.demo_api_workflow
```

Tests use temporary file-backed SQLite databases and the genuine catalog. The
demo issues real ASGI HTTP requests with FastAPI TestClient, registers/logs in
two explicit DEMO fixtures, creates/joins a group, saves preferences, generates
consensus results, votes, persists an itinerary and verifies it through a new
app/engine instance. It then removes the temporary database. Sanitized evidence
is written to backend/var/api_workflow_demo.json, with no passwords, JWTs or
invitation codes. These fixtures are NOT genuine recommendation training data.
The temporary demonstration does not alter the native backend/var database.
Existing application databases may already contain local accounts and plans;
do not assume they are empty or reset them as a setup step.

Dependencies follow the [FastAPI JWT/password tutorial](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
and [SQLAlchemy SQLite foreign-key guidance](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html).
# Group planning additions

See [GROUP_PLANNING.md](GROUP_PLANNING.md) for flexible versus mandatory country
choices, private `/groups/{id}/planning` and recommendation `/voting` summaries,
shared-date rules, backwards compatibility and verification commands.
