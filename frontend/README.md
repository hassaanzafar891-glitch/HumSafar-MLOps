# HumSafar web application (Step 27)

React + Vite + React Router, with responsive CSS and the existing FastAPI API.
No backend security changes, new model training, dataset edits or deployment.

## Local startup on Windows

In E:\GroupTravelMLOps, prepare the backend using backend/API.md. Copy the root
.env.example to .env only if not already configured, and set a generated private
JWT_SECRET_KEY. Do not replace an existing secret unnecessarily. Then:

```powershell
.venv\Scripts\python.exe -m backend.api.init_db
.venv\Scripts\python.exe -m uvicorn backend.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

In a second PowerShell terminal:

```powershell
cd E:\GroupTravelMLOps\frontend
npm.cmd ci --cache E:\GroupTravelMLOps\frontend\.npm-cache
npm.cmd run dev
```

Visit http://127.0.0.1:5173. Node 22.18 was used for verification. The local npm
cache was placed on E: because C: was full. No system-drive files were deleted.
Optional frontend/.env can contain HUMSAFAR_API_TARGET (see .env.example).
This is a server-side proxy setting, NOT a browser secret. No JWT secret belongs
in frontend environment variables. All client requests use relative /api paths;
Vite forwards them to the backend and strips /api. Backend CORS/auth rules are
unchanged. Requests remain same-origin from the browser's perspective.

```powershell
npm.cmd run build
npm.cmd test
npm.cmd run test:e2e
```

The production bundle is in dist/. npm run preview uses port 4173 with the same
local proxy. For any future hosting, a server/reverse proxy must serve the SPA
with history fallback and route /api to FastAPI. Merely uploading dist without
that routing is not a functioning API deployment. No hosting was performed.

## Pages and implementation

- /: landing page, live featured catalog listings, coverage explanation and CTAs.
- /explore: attractions/hotels, actual country labels, metadata search, pagination,
  native details dialogs and source-supplied coordinates where available.
- /register and /login: actual register endpoint followed by OAuth2 form login.
- /dashboard: private group list, creation/joining and dated upcoming itinerary.
- /groups/:id: preferences, individual/group recommendations, voting, itinerary,
  member listing/leaving/removal, and owner settings/invite/transfer/archive/delete.
- /profile: display name/bio and password changes with required reauthentication.

src/api.js owns a fetch boundary, safe structured errors and an in-memory bearer
token. App.jsx contains named page/view components, shared form/loading/error
components and session context. styles.css contains responsive layouts, focus
styles, reduced-motion support and the original decorative landscape artwork.
There are no UI-framework, charting, booking or payment dependencies.

Every catalog card is backed by API data. Catalog search loads all pages for the
selected kind/country before displaying filtered results; it is not silently
limited to the first server page. This is workable at the current catalog size,
but server-side search/pagination should replace client-side full loading for
larger catalogs. Public catalog results may be cached in memory; private group
data is refreshed from authenticated endpoints. There are no fake prices, stars,
testimonials, booking availability, destination records or visitor counts.

No catalog photo URLs are exposed by the existing API. The hero and cards use
labelled CSS landscape illustrations, not photographs of named places. Extra
details unavailable from the API are not manufactured. Attractions currently
cover Pakistan/Hawaii; other international records are historical hotel metadata.
New application users see preference/content matching, not historical Hawaii
personalization. The model's existence is not presented as worldwide coverage.

## Authentication and private data

Passwords are sent only to the actual authentication/password endpoints. Tokens,
passwords and invitation codes are never written to localStorage/sessionStorage,
URLs, logs or a persisted frontend state store. Access tokens are held in module
memory; invite codes are shown only to owners and retained in session memory.
An expired token/401 clears session state and returns protected pages to login.
Logout calls backend revocation; offline failures clearly report local-only
logout. Password changes require logging in again.

Because the backend has no refresh-token cookie flow, refreshing the browser
ends the frontend session. This is intentional; no insecure persistent token
workaround was added. Automatic session restoration would need an explicitly
designed backend flow, not weaker CORS/authentication rules.

The UI is permission-aware, while the backend remains authoritative. Owner-only
controls are hidden from members. Individual/stale recommendation lists cannot
be voted on or used for itinerary selection. Server conflicts are surfaced.
Voting allows casting/changing/withdrawing and shows totals; totals are refreshed
after actions or explicit group refresh, not pushed live. The API has no current
user vote-read endpoint, so the selected vote indicator is session-local; server
totals remain authoritative and changing/withdrawing still works after refresh.

Budgets/currency and dates are saved as preferences, not presented as working
cost/live-availability filters. Backend notices are shown directly. Country,
region and selected-destination preferences are real hard constraints, so groups
with incompatible choices must revise them. Native multi-select controls support
keyboard selection and include usage hints. Itineraries are plans, not bookings.

## Test and browser evidence

Vitest/Testing Library cover registration, protected routing, form-login request
format, memory-only auth, expiry handling and backend error messages. These tests
mock transport only; they do not invent catalog records or claim recommendation
quality. Playwright launches an isolated FastAPI process with a temporary SQLite
database and random in-memory secret, plus the real Vite proxy and installed
Microsoft Edge (headless). No browser download is required on this machine.
If Edge is unavailable elsewhere, install/configure an approved browser before
running the browser suite rather than weakening application security.

The full browser workflow uses two independent contexts: register/login, create,
privately invite/join, save both members' preferences, generate consensus, vote,
and create/view an itinerary. Demo accounts/actions are isolated test fixtures,
not genuine ML feedback. Another test covers a 390px viewport, horizontal layout,
actual catalog search and keyboard dismissal of a details dialog. Screenshots
and local test results are ignored by Git. Existing split files and model
weights, including the Hawaii test split, are never used by this browser setup.

Remaining limits: historical/incomplete metadata; no full-country attraction
coverage beyond current sources; no photo, price or live availability API; no
refresh-token session restoration, live vote push or hotel booking. Keyboard and
mobile checks are included, but this is not a full accessibility certification
or cross-browser matrix. Existing consensus utilities remain predicted scores,
not proof of real satisfaction or fairness.
# Group planning improvements

Verified destination photos, sources, licenses, asset reproduction and fallback
behavior are documented in [PHOTOGRAPHS.md](PHOTOGRAPHS.md).

Private groups now show member country choices, genuine compatible alternatives,
shared-date intersections, named voting summaries and itinerary date constraints.
Members choose preferred versus mandatory country/destination restrictions; legacy
restrictions remain mandatory until explicitly edited. Voting never adds a stop.
See [group planning protocol](../backend/GROUP_PLANNING.md) for exact behavior.
Browser tests use isolated frontend port 5174 by default (`HUMSAFAR_E2E_PORT` overrides it).
