# Shared travel planning

Run the backend and frontend with the existing commands in API.md and
frontend/README.md. No database migration is needed: preferences are already
stored as validated JSON. No dataset, trained weights, or authentication policy
changes are required.

## Countries and destinations

Preferences now include `country_requirement` and `destination_requirement`,
each `preferred` or `mandatory`. Omitted fields default to **mandatory** in the
API, preserving existing saved restrictions. New frontend forms explicitly use
`preferred`; editing an older preference keeps it mandatory until its owner
changes it. Required regions remain hard constraints.

All mandatory country, region and destination restrictions are intersected
before scoring. An empty intersection still produces HTTP 409; the planning
summary explains the restrictions by member. Nobody can edit another member's
preferences. A “Consider country” action selects a request filter only; it does
not save or relax anyone's preferences.

For flexible choices the application preference adapter uses
`0.85 * content_score + 0.15 * geographic_preference`, where geographic preference
is the mean of supplied country-match and selected-destination-match indicators
(omit a component when no choices are supplied). Without flexible choices,
scores remain unchanged. Existing group aggregation then normalizes and combines
these utilities as before. These weights are product defaults, not experimentally
validated improvements. Scores are not probabilities or observed satisfaction.
Mandatory filters always take precedence over this scoring.

New application UUIDs use the `humsafar` identity namespace, never historical
Hawaii identities. They continue to use content matching, not BPR user factors.
Choosing catalog scope uses metadata matching; choosing compatible Pakistan scope
retains the TF-IDF route. Attraction alternatives currently cover Pakistan and
Hawaii only; historical international hotels are not worldwide attraction coverage.

## Availability

`GET /groups/{id}/planning?scope=catalog&kind=attraction` is membership protected.
It returns named coordinating preferences, genuine compatible-country counts,
missing countries, and date status. It does not expose budgets, email addresses,
or free-text preferences of other members.

Intersection: `start = max(member starts)`, `end = min(member ends)`, inclusive.
A single shared day is valid. Status is `unknown` when nobody supplies dates,
`incomplete` when some dates are missing, `conflict` when supplied intervals do
not intersect, and `overlap` when every member supplies compatible dates.
Incomplete windows are explicitly provisional, not confirmation by missing members.
Date inputs use the supplied intersection as min/max; a conflict disables adding
a dated stop, while an undated stop remains possible. The backend independently
rejects dates outside any supplied member window. Missing dates impose no invented
restriction. Existing dated stops that no longer fit receive a visible warning;
no dates are changed automatically. Opening hours/live availability remain unknown.

## Voting

`GET /groups/{id}/recommendations/{rec_id}/voting` returns named member choices,
totals, the caller's saved vote and current eligibility. Only group members can
read it, with existing individual-list visibility rules preserved. Votes are
visible to fellow group members. One vote per member per list; PUT changes the
caller's vote, DELETE withdraws it. Neither action creates an itinerary item.
Only the organizer can add itinerary items from current group lists. Existing
stale-list, archived-group and membership checks remain enforced.

The frontend compares destinations, locations and votes, displays nonvoters,
and restores the caller's saved selection when revisiting the list. Updates are
request based: use Refresh group or Refresh votes to see another session's changes.

## Verification

Run selected backend suites (not unrestricted discovery, which includes data
preparation tests that may inspect the held-out split):

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_api.py
.venv\Scripts\python.exe -m unittest discover -s tests -p test_planning.py
.venv\Scripts\python.exe -m unittest discover -s tests -p test_recommendation_service.py
.venv\Scripts\python.exe -m unittest discover -s tests -p test_group_consensus.py
cd frontend
npm test
npm run build
npm run test:e2e
```

Browser tests launch an isolated temporary application database/API on 8765 and
Vite on 5174 (override `HUMSAFAR_E2E_PORT`), leaving a development server on 5173
alone. Installed Microsoft Edge is used; no browser download is required. Test
accounts and votes are isolated fixtures and never become ML training data.

Verified locally: 41 selected backend tests (17 API, 5 planning, 11 service,
8 group-consensus), 8 frontend unit tests, 2 real Edge browser tests, and the
Vite production build. The browser workflow covers separate accounts, flexible
country differences, explicit mandatory-country conflicts, common-date bounds,
non-overlapping dates, voting without automatic itinerary creation, and an
organizer-created itinerary. Mobile catalog/dialog and overflow checks passed.
