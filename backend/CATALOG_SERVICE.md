# Step 25: international catalog and reusable recommendation service

This is a local Python service layer, not an HTTP API or an authentication
system. Existing datasets, model weights and experiment modules remain intact.
There are no downloads, synthetic destinations, new ratings, or model fitting.
The Hawaii held-out test split is never read.

## Build, inspect and verify

```powershell
.venv/Scripts/python.exe -m backend.build_catalog
.venv/Scripts/python.exe -m backend.demo_recommendation_service
.venv/Scripts/python.exe -m unittest discover -s tests -p test_catalog.py -v
.venv/Scripts/python.exe -m unittest discover -s tests -p test_recommendation_service.py -v
```

Generated catalog files in data/processed/international/:

- catalog.jsonl: source-scoped destination records, ordered by stable ID.
- schema.json: machine-readable v1 schema; Destination.validate adds identity,
  coordinate-finiteness and source/model-boundary checks.
- coverage.json: source/country/type/model-compatibility counts and provenance.
- coverage_by_country.csv: EVERY source country/territory label, with attraction,
  hotel and total counts; __unknown__ is explicitly separate.
- service_demo.json: example requests/results, not genuine user preferences or
  observed ratings. Example member IDs are request-local labels, not new users.

## Unified schema

| Field | Meaning |
|---|---|
| schema_version | 1 |
| destination_id | data_source + ':' + SHA256(original source_id) |
| name | Genuine source destination/attraction/hotel name |
| kind | attraction or hotel; hotels never counted as attraction coverage |
| country | Nullable source-derived country/territory label |
| city_or_region | Nullable explicit source city or collection/source region |
| latitude, longitude | Nullable finite coordinates with global bounds checked |
| categories | Genuine source category labels; empty when unavailable |
| description, address | Nullable source text, never generated |
| data_source, source_id | Source namespace and original stable record identity |
| geographic_coverage | Explicit source collection coverage, not 'worldwide' |
| model_compatibility | metadata_preference / pakistan_tfidf / hawaii_bpr |
| provenance | Source path/location, country mapping basis and other evidence |

IDs reproduce for unchanged source identities. They do not automatically resolve
the same physical place across sources. In particular, Pakistan's _key is a
source name identifier; changing it needs an explicit migration/crosswalk.
Exact identical repeated IDs collapse; conflicting records for an ID fail before
the prior catalog is replaced. Names are never fuzzy-merged. Unknowns stay null.

To add another country, a source adapter emits Destination objects or canonical
dicts and passes them to catalog.ingest. No schema change is needed. The adapter
must provide genuine source IDs and country provenance, and leave unavailable
values null. Structural validation cannot independently certify that a supplier's
country label or factual description is correct. Review source quality before
enabling a new adapter. New metadata can use metadata_preference; adding a new
trained model requires explicit compatibility and service routing integration.

## Actual coverage and country mapping

| Source | Attractions | Hotels | Usable recommendation mode |
|---|---:|---:|---|
| Pakistan cleaned catalog | 69 | 0 | Saved Pakistan TF-IDF or metadata matching |
| Prepared Google Local Hawaii | 1512 | 0 | Compatible-user BPR hybrid or metadata matching |
| Webis TripAdvisor 2014 | 0 | 12044 | Historical hotel metadata matching only |

Total 13625 source listings. Attraction coverage is ONLY Pakistan (69) and Hawaii,
United States (1512). TripAdvisor adds real historical international HOTEL
metadata, not international attraction ratings or Hawaii-compatible user factors.
There are 117 named country/territory labels and 726 unknown-country hotel rows.
Labels include territories and the historical 'Republic of Macedonia'; this is
not an authoritative current list of sovereign countries or worldwide coverage.

Explicit aliases: 'United Kingdom (UK)' -> 'United Kingdom'; 'The Netherlands'
-> 'Netherlands'. The 342 'Caribbean' country labels become country=null with
their original location preserved in provenance; missing countries (384) remain
null. No country is inferred from a city, address, or hotel description.

Pakistan country derives from its explicitly Pakistan-scoped source collection.
The prepared Hawaii collection maps to United States/Hawaii with this basis
recorded; all 1512 coordinates were checked against conservative Hawaii regional
bounds. This is not geocoding. Individual city values are not parsed from free
text addresses. TripAdvisor location fields are preserved in provenance; all
12044 hotel coordinates remain absent. Missing descriptions total 5593. Source
data and descriptions may be dated; current availability is not established.

## Service routes and score interpretation

```python
from backend.recommendation_service import RecommendationService, UserContext
service = RecommendationService()
content = service.recommend(scope='pakistan', preferences='mountains hiking nature')
hotels = service.recommend(scope='catalog', country='Italy', kind='hotel',
                           preferences='historic hotel')
# For an actual, explicitly linked historical Google Hawaii research identity:
# service.recommend(scope='hawaii',
#     user=UserContext('google_local_hawaii', actual_google_user_id))
```

- scope=hawaii: learned personalization requires an exact google_local_hawaii
  user namespace, a known training user with nonzero learned factors, and catalog
  rows whose source AND source IDs belong to the saved Hawaii BPR model. Score
  is the saved .75 BPR + .25 training-only popularity hybrid. Training visits
  are excluded. Model-compatibility flags alone cannot grant compatibility.
- scope=pakistan: nonblank text uses the existing fitted TF-IDF vectorizer/matrix
  only for compatible Pakistan source IDs. No model is refitted. Service results
  omit zero-similarity padding, while the original experiment module is unchanged.
- scope=catalog: exact metadata preference matching for the requested kind and
  optional canonical country. Hawaiian embeddings are NEVER used, even if a
  caller supplies a known Hawaii user. Pakistan TF-IDF is available explicitly
  through its own scope; no uncalibrated model scores are merged across regions.

Metadata matching lowercases Unicode word tokens, removes sklearn English stop
words, and scores query-token coverage across genuine name, categories,
description, country/region and address. It has no training phase, synonyms,
semantic understanding, rating labels, or accuracy claim. Only positive matches
are returned. A hotel with only a name has correspondingly weak content support.

Responses explicitly state mode, personalized flag and status. Scores have
mode-specific meanings, are not probabilities, and cannot be compared across
modes. The complete country coverage table is the availability authority:
asking for Italy attractions returns no_candidates, not Italy hotels or Hawaii
attractions. A named country in hotel metadata never grants attraction coverage.
Historical MF, MiniLM and other experimental modules are preserved; default
service routing uses the task's selected hybrid, TF-IDF and metadata fallback.

## Safe new-user onboarding

New application users belong to an application namespace, not Google historical
user IDs. Matching digit strings do not establish identity or grant factors.
Without a compatible learned representation, ask for genuine text interests and
geographic scope; use clearly labelled content/preference matching. Missing
preferences return needs_preferences; no matching terms return
no_matching_preferences. No random embeddings, copied users, fabricated ratings,
or fake interaction histories are created.

The 100 historical Hawaii users without positive training feedback have zero
user factors; this service also routes them to preferences, retaining exclusion
of their known training visits. This does not change their saved model state.
There is no invented country preference, budget, price or travel-cost feature.

The caller must establish any application-to-historical-identity linkage outside
this service; UserContext is an explicit research/integration boundary, not an
authentication mechanism. Collect consented genuine feedback for future training
before proposing new personalized factors. Persistence/auth/onboarding UI and
incremental training are outside this step.

## Adaptive Group Consensus for actual requests

GroupMember contains a request-local member_id, genuine supplied preferences,
and optional explicit UserContext. RecommendationService.recommend_group builds
each member's source-compatible score vector, excludes candidates visited by
ANY compatible historical member, and calls the existing Step 24 aggregate
implementation. Anonymous preference-only groups and mixed historical/new-user
groups are supported; simulated Hawaii group formation is not required.

The same average, least_misery and adaptive_consensus methods are available.
Weights remain configurable via ConsensusConfig. Missing member preferences
produce needs_preferences; zero-signal members produce
insufficient_preference_signal. Candidates with zero evidence for every member
are not used to pad output. Fewer than top_k candidates return a shorter list.
Generic service tie-breaks use unified stable IDs; legacy experiment tie rules
and measured evaluation outputs are unchanged.

For complete externally supplied normalized preference/model scores:

    service.group_from_scores({member_id: {destination_id: utility, ...}, ...})

Each member must explicitly supply a finite [0,1] score for EVERY candidate;
missing entries are rejected rather than treated as dislikes. No ratings are
persisted. The standalone aggregate_preference_scores helper also works outside
the catalog if the caller supplies its own consistent candidate IDs. This is a
reusable mathematical interface, not a claim that synthetic utility is feedback.

Outputs distinguish member modes and predicted/supplied utility summaries.
Service group result scores are mean member utilities, not the sequential AGC
objective. Mixing content and collaborative scores does not prove interpersonal
calibration or real fairness. The Step 24 formula/limitations still apply.

## Remaining gaps

International attraction metadata beyond Pakistan/Hawaii is absent. New
countries need genuine attraction catalogs and provenance; their personalization
needs compatible real interactions and separately evaluated models. The hotel
archive has sparse city data and lacks coordinates, and its ratings were not
ingested or trained in this step. Country verification, entity resolution,
licensing/refresh policy, future source adapters, consented identity linkage,
feedback collection and prospective evaluation remain integration work. There
is no claim of worldwide attraction coverage or personalized hotel ranking.
