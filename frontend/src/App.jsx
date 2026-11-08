import RecommendationInfo from "./RecommendationInfo.jsx";
import { PlanningOverview, VotingBoard, dateBounds } from "./Planning.jsx";
import DestinationPhoto from "./DestinationPhoto.jsx";
import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { api, setSession } from "./api.js";
const Auth = createContext(null);
const useAuth = () => useContext(Auth);
const split = (value) => [
  ...new Set(
    value
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean),
  ),
];
const modeName = {
  metadata_preference: "Preference matching",
  pakistan_tfidf_content: "Content matching",
  hawaii_personalized_hybrid: "Personalized from compatible history",
};
function useLoad(load, deps = []) {
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(true),
    [version, bump] = useState(0);
  useEffect(() => {
    let alive = true;
    setBusy(true);
    setError("");
    Promise.resolve()
      .then(load)
      .then((x) => {
        if (alive) setData(x);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [...deps, version]);
  return { data, error, busy, reload: () => bump((x) => x + 1) };
}
function ErrorNote({ children }) {
  return children ? (
    <div role="alert" className="notice error">
      {children}
    </div>
  ) : null;
}
function Loading() {
  return (
    <div role="status" className="loading">
      <span /> Finding your way…
    </div>
  );
}
function Empty({ title, children }) {
  return (
    <div className="empty">
      <span className="empty-icon">↗</span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function TaskForm({
  onSubmit,
  submit = "Save",
  children,
  className = "",
  disabled = false,
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  return (
    <form
      className={className}
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        setSuccess("");
        try {
          const message = await onSubmit(new FormData(e.currentTarget));
          setSuccess(message || "");
        } catch (e) {
          setError(e.message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <fieldset disabled={busy || disabled}>{children}</fieldset>
      <ErrorNote>{error}</ErrorNote>
      {success && (
        <p role="status" className="success">
          {success}
        </p>
      )}
      <button className="button" type="submit" disabled={busy || disabled}>
        {busy ? "Please wait…" : submit}
      </button>
    </form>
  );
}
function Field({ label, name, children, ...props }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children || <input name={name} {...props} />}
    </label>
  );
}
function Action({ onClick, children, danger = false, disabled = false }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <span className="action">
      <button
        type="button"
        className={danger ? "button danger" : "button secondary"}
        disabled={busy || disabled}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await onClick();
          } catch (e) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Working…" : children}
      </button>
      <ErrorNote>{error}</ErrorNote>
    </span>
  );
}
function AuthProvider({ children }) {
  const [user, setUser] = useState(null),
    [message, setMessage] = useState(""),
    [invites, setInvites] = useState({});
  const timer = useRef();
  const clear = (text = "") => {
    setSession(null);
    setUser(null);
    setInvites({});
    setMessage(text);
    clearTimeout(timer.current);
  };
  useEffect(() => {
    setSession(null, () =>
      clear("Your session expired. Please sign in again."),
    );
    return () => clearTimeout(timer.current);
  }, []);
  async function login(email, password) {
    const result = await api("/auth/login", {
      method: "POST",
      form: { username: email, password },
    });
    setSession(result.access_token, () =>
      clear("Your session expired. Please sign in again."),
    );
    try {
      setUser(await api("/users/me"));
      setMessage("");
      timer.current = setTimeout(
        () => clear("Your session expired. Please sign in again."),
        result.expires_in * 1000,
      );
    } catch (e) {
      clear();
      throw e;
    }
  }
  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
      clear();
    } catch {
      clear("Signed out on this device. Server logout could not be confirmed.");
    }
  }
  return (
    <Auth.Provider
      value={{
        user,
        setUser,
        login,
        logout,
        clear,
        message,
        invites,
        saveInvite: (id, code) => setInvites((x) => ({ ...x, [id]: code })),
      }}
    >
      {children}
    </Auth.Provider>
  );
}
function Brand() {
  return (
    <Link to="/" className="brand" aria-label="HumSafar home">
      <span className="brand-mark">✳</span>
      <span>
        HumSafar<small>BETTER JOURNEYS, TOGETHER</small>
      </span>
    </Link>
  );
}
function Shell() {
  const auth = useAuth();
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <Brand />
        <nav aria-label="Main navigation">
          <NavLink to="/explore">Explore</NavLink>
          {auth.user ? (
            <>
              <NavLink to="/dashboard">My trips</NavLink>
              <NavLink to="/profile">{auth.user.display_name}</NavLink>
              <Action onClick={auth.logout}>Log out</Action>
            </>
          ) : (
            <>
              <NavLink to="/login">Log in</NavLink>
              <Link className="button compact" to="/register">
                Start planning ↗
              </Link>
            </>
          )}
        </nav>
      </header>
      {auth.message && (
        <div role="status" className="notice session">
          {auth.message}
        </div>
      )}
      <main id="main">
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/explore" element={<Explore />} />
          <Route path="/login" element={<AuthPage />} />
          <Route path="/register" element={<AuthPage register />} />
          <Route
            path="/dashboard"
            element={
              <Protected>
                <Dashboard />
              </Protected>
            }
          />
          <Route
            path="/groups/:id"
            element={
              <Protected>
                <GroupPage />
              </Protected>
            }
          />
          <Route
            path="/profile"
            element={
              <Protected>
                <Profile />
              </Protected>
            }
          />
          <Route
            path="*"
            element={
              <Empty title="A little off the beaten path">
                <Link to="/">Return home</Link>
              </Empty>
            }
          />
        </Routes>
      </main>
      <footer>
        <Brand />
        <p>Different people. A shared sense of adventure.</p>
        <Link to="/explore">Explore actual catalog coverage ↗</Link>
        <small>
          Travel planning, not booking. No prices or live availability are
          supplied.
        </small>
      </footer>
    </>
  );
}
function Protected({ children }) {
  const { user } = useAuth(),
    location = useLocation();
  return user ? (
    children
  ) : (
    <Navigate to="/login" replace state={{ from: location.pathname }} />
  );
}
function Landing() {
  const { user } = useAuth(),
    coverage = useLoad(() => api("/catalog/coverage")),
    featured = useLoad(() =>
      api("/catalog?kind=attraction&country=United%20States&limit=3"),
    );
  return (
    <>
      <section className="hero wrap">
        <div className="hero-copy">
          <p className="eyebrow">FOR THE WAY WE TRAVEL TOGETHER</p>
          <h1>
            A world to explore.
            <br />A plan for <em>everyone.</em>
          </h1>
          <p className="lead">
            Bring your people, share what you love, and find a journey you can
            all look forward to.
          </p>
          <div className="button-row">
            <Link className="button" to={user ? "/dashboard" : "/register"}>
              Plan your next trip <span>↗</span>
            </Link>
            <Link className="text-link" to="/explore">
              Find some inspiration →
            </Link>
          </div>
          <div className="hero-note">
            <span>✳</span>
            <p>
              Less back-and-forth.
              <br />
              <strong>More “let’s go.”</strong>
            </p>
          </div>
          <div
            className="journey-highlights"
            aria-label="A simpler way to plan"
          >
            <span>
              01 <strong>Everyone has a say</strong>
            </span>
            <span>
              02 <strong>Find dates that fit</strong>
            </span>
            <span>
              03 <strong>Decide together</strong>
            </span>
          </div>
        </div>
        <div
          className="hero-art"
          role="img"
          aria-label="Abstract illustrated coastline and mountains"
        >
          <div className="sun" />
          <div className="ridge one" />
          <div className="ridge two" />
          <div className="coast" />
          <span className="art-label">THE NEXT CHAPTER STARTS TOGETHER</span>
          <div className="floating-note">
            <span>↗</span>
            <div>
              <strong>Find your common ground</strong>
              <small>Share interests. Discover. Decide together.</small>
            </div>
          </div>
          <small className="illustration-label">
            Landscape illustration · not a destination photograph
          </small>
        </div>
      </section>
      <section className="trust-strip">
        <span>YOUR PEOPLE</span>
        <b>✳</b>
        <span>YOUR PREFERENCES</span>
        <b>✳</b>
        <span>ONE SHARED ADVENTURE</span>
      </section>
      <section className="wrap section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">GO FROM “WHAT IF” TO “WHEN?”</p>
            <h2>
              Great trips start with
              <br />
              everyone in the conversation.
            </h2>
          </div>
          <p>
            No one has to do all the planning.
            <br />A little structure leaves more room for adventure.
          </p>
        </div>
        <div className="steps">
          <article>
            <span>01 / GATHER</span>
            <h3>Your travel circle</h3>
            <p>
              Create a private group and invite your people with a secure code.
            </p>
          </article>
          <article>
            <span>02 / DISCOVER</span>
            <h3>A little of everyone</h3>
            <p>
              Share interests and compare suggestions that balance your group’s
              preferences.
            </p>
          </article>
          <article>
            <span>03 / MAKE IT HAPPEN</span>
            <h3>A plan you share</h3>
            <p>
              Vote on your favorites, then turn selected recommendations into an
              itinerary.
            </p>
          </article>
        </div>
      </section>
      <section className="catalog-band">
        <div className="wrap section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">REAL PLACES. ROOM TO EXPLORE.</p>
              <h2>Your next “we should go there.”</h2>
            </div>
            <Link className="text-link" to="/explore">
              Explore the catalog ↗
            </Link>
          </div>
          <p className="coverage-note">
            Attractions currently cover Hawaii and Pakistan. Historical hotel
            listings extend to other countries and territories. This is a
            growing catalog, not worldwide personalized coverage.
          </p>
          {featured.busy ? (
            <Loading />
          ) : featured.error ? (
            <ErrorNote>{featured.error}</ErrorNote>
          ) : (
            <div className="cards">
              {featured.data?.items.map((item) => (
                <DestinationCard key={item.destination_id} item={item} />
              ))}
            </div>
          )}
          <div className="catalog-summary">
            {coverage.data && (
              <>
                <strong>
                  {coverage.data.total_source_listings.toLocaleString()}
                </strong>{" "}
                source listings · attractions and hotels, clearly separated
              </>
            )}
          </div>
        </div>
      </section>
      <section className="wrap final-cta">
        <p className="eyebrow">THE BEST PART IS WHO YOU GO WITH</p>
        <h2>
          Make room for everyone’s
          <br />
          kind of adventure.
        </h2>
        <Link className="button" to={user ? "/dashboard" : "/register"}>
          Bring your people ↗
        </Link>
      </section>
    </>
  );
}
function DestinationCard({ item, children }) {
  const dialog = useRef();
  return (
    <article className="destination-card">
      <DestinationPhoto item={item} />
      <div className="card-body">
        <p className="eyebrow">
          {item.kind === "hotel" ? "Hotel" : "Attraction"} ·{" "}
          {item.country || "Country not provided"}
        </p>
        <h3>{item.name}</h3>
        <p>{item.city_or_region || "Region not provided"}</p>
        <div className="chips">
          {item.categories?.slice(0, 3).map((x) => (
            <span key={x}>{x}</span>
          ))}
        </div>
        <button
          className="text-link"
          type="button"
          onClick={() => dialog.current.showModal()}
        >
          View details ↗
        </button>
        {children}
      </div>
      <dialog ref={dialog} aria-label={`Details for ${item.name}`}>
        <button
          type="button"
          className="dialog-close"
          aria-label="Close details"
          onClick={() => dialog.current.close()}
        >
          ×
        </button>
        <p className="eyebrow">{item.kind}</p>
        <h2>{item.name}</h2>
        <DestinationPhoto item={item} variant="detail" />
        <p>
          {[item.city_or_region, item.country].filter(Boolean).join(", ") ||
            "Location not supplied"}
        </p>
        <p>{item.categories?.join(" · ") || "No categories supplied"}</p>
        {item.latitude != null && (
          <p>
            Coordinates: {item.latitude}, {item.longitude}
          </p>
        )}
        <p className="muted">
          No prices, visitor ratings, or live booking availability are supplied.
          Photographs are individually credited where verified; other artwork is
          illustrative.
        </p>
      </dialog>
    </article>
  );
}
function AuthPage({ register = false }) {
  const auth = useAuth(),
    navigate = useNavigate(),
    location = useLocation();
  if (auth.user) return <Navigate to="/dashboard" replace />;
  return (
    <section className="auth-layout wrap">
      <div className="auth-story">
        <p className="eyebrow">YOUR NEXT CHAPTER</p>
        <h1>
          {register
            ? "Good company.\nGreat journeys."
            : "Welcome back,\ntraveler."}
        </h1>
        <p>
          One place for your people, your preferences, and the plans you make
          together.
        </p>
        <span className="big-compass">✳</span>
      </div>
      <div className="panel auth-panel">
        <h2>{register ? "Start your journey" : "Let’s pick up the plan"}</h2>
        <p>
          {register
            ? "Create your HumSafar account."
            : "Sign in to your private travel groups."}
        </p>
        {location.state?.notice && (
          <p role="status" className="success">
            {location.state.notice}
          </p>
        )}
        <TaskForm
          key={String(register)}
          submit={register ? "Create account" : "Log in"}
          onSubmit={async (form) => {
            if (register) {
              await api("/auth/register", {
                method: "POST",
                body: {
                  email: form.get("email"),
                  display_name: form.get("display_name"),
                  password: form.get("password"),
                },
              });
              navigate("/login", {
                state: { notice: "Account created. Log in to start planning." },
              });
            } else {
              await auth.login(form.get("email"), form.get("password"));
              navigate(location.state?.from || "/dashboard", { replace: true });
            }
          }}
        >
          {register && (
            <Field
              label="Your name"
              name="display_name"
              required
              maxLength={80}
              autoComplete="name"
            />
          )}
          <Field
            label="Email address"
            name="email"
            type="email"
            required
            autoComplete="email"
          />
          <Field
            label="Password"
            name="password"
            type="password"
            required
            minLength={register ? 12 : 1}
            maxLength={128}
            autoComplete={register ? "new-password" : "current-password"}
          />
          {register && (
            <small>
              Use at least 12 characters. Your account is separate from
              historical dataset users.
            </small>
          )}
        </TaskForm>
        <p>
          {register ? "Already have an account?" : "New here?"}{" "}
          <Link to={register ? "/login" : "/register"}>
            {register ? "Log in" : "Create an account"}
          </Link>
        </p>
        <small className="muted">
          For security, reloading this page ends your browser session. Passwords
          and tokens are never saved in browser storage.
        </small>
      </div>
    </section>
  );
}
function Dashboard() {
  const auth = useAuth(),
    navigate = useNavigate();
  const load = useLoad(async () => {
    const groups = await api("/groups");
    const plans = await Promise.allSettled(
      groups.map((g) => api(`/groups/${g.id}/itinerary`)),
    );
    return {
      groups,
      plans: plans.flatMap((p, i) =>
        p.status === "fulfilled"
          ? p.value.map((x) => ({ ...x, group: groups[i] }))
          : [],
      ),
      partial: plans.some((x) => x.status === "rejected"),
    };
  }, [auth.user.id]);
  return (
    <section className="wrap section">
      <p className="eyebrow">YOUR TRAVEL CIRCLE</p>
      <h1 className="page-title">Where to next, {auth.user.display_name}?</h1>
      <p className="lead">Good plans start with good company.</p>
      <div className="two-column">
        <div className="panel">
          <h2>Create a group</h2>
          <TaskForm
            submit="Create group"
            onSubmit={async (f) => {
              const created = await api("/groups", {
                method: "POST",
                body: { name: f.get("name") },
              });
              auth.saveInvite(created.group.id, created.invitation_code);
              navigate(`/groups/${created.group.id}`);
            }}
          >
            <Field
              label="Group name"
              name="name"
              placeholder="Our next adventure"
              required
              maxLength={100}
            />
          </TaskForm>
        </div>
        <div className="panel">
          <h2>Got an invitation?</h2>
          <TaskForm
            submit="Join group"
            onSubmit={async (f) => {
              const g = await api("/groups/join", {
                method: "POST",
                body: { invitation_code: f.get("code") },
              });
              navigate(`/groups/${g.id}`);
            }}
          >
            <Field
              label="Private invitation code"
              name="code"
              required
              minLength={20}
              maxLength={200}
              autoComplete="off"
            />
          </TaskForm>
        </div>
      </div>
      <div className="section-heading">
        <h2>Your groups</h2>
        <Action onClick={load.reload}>Refresh groups</Action>
      </div>
      {load.busy ? (
        <Loading />
      ) : load.error ? (
        <ErrorNote>{load.error}</ErrorNote>
      ) : (
        <>
          {load.data.groups.length ? (
            <div className="group-grid">
              {load.data.groups.map((g) => (
                <Link className="group-card" key={g.id} to={`/groups/${g.id}`}>
                  <span>↗</span>
                  <h3>{g.name}</h3>
                  <p>
                    {g.archived
                      ? "Archived"
                      : g.owner_id === auth.user.id
                        ? "You’re organizing"
                        : "Planning together"}
                  </p>
                  <strong>Open group →</strong>
                </Link>
              ))}
            </div>
          ) : (
            <Empty title="Your people belong here">
              Create a group or join with an invitation to start planning.
            </Empty>
          )}
          <h2 className="section-title">Upcoming plans</h2>
          {load.data.partial && (
            <ErrorNote>
              Some group plans could not be loaded. Refresh to try again.
            </ErrorNote>
          )}
          {load.data.plans.filter(
            (x) =>
              x.planned_date &&
              x.planned_date >= new Date().toLocaleDateString("en-CA"),
          ).length ? (
            <div className="plan-list">
              {load.data.plans
                .filter(
                  (x) =>
                    x.planned_date &&
                    x.planned_date >= new Date().toLocaleDateString("en-CA"),
                )
                .sort((a, b) => a.planned_date.localeCompare(b.planned_date))
                .map((x) => (
                  <Link key={x.id} to={`/groups/${x.group.id}`}>
                    <time>{x.planned_date}</time>
                    <strong>{x.destination_snapshot.name}</strong>
                    <span>{x.group.name} →</span>
                  </Link>
                ))}
            </div>
          ) : (
            <Empty title="A little anticipation goes a long way">
              Dated itinerary items from your groups will appear here.
            </Empty>
          )}
        </>
      )}
    </section>
  );
}
function Profile() {
  const auth = useAuth();
  return (
    <section className="wrap section narrow">
      <p className="eyebrow">MAKE YOURSELF AT HOME</p>
      <h1 className="page-title">Your profile</h1>
      <div className="panel">
        <p>{auth.user.email}</p>
        <TaskForm
          submit="Save profile"
          onSubmit={async (f) => {
            auth.setUser(
              await api("/users/me", {
                method: "PATCH",
                body: {
                  display_name: f.get("display_name"),
                  bio: f.get("bio"),
                },
              }),
            );
            return "Profile updated.";
          }}
        >
          <Field
            label="Your name"
            name="display_name"
            required
            maxLength={80}
            defaultValue={auth.user.display_name}
          />
          <Field label="About you">
            <textarea name="bio" maxLength={500} defaultValue={auth.user.bio} />
          </Field>
        </TaskForm>
      </div>
      <div className="panel">
        <h2>Change password</h2>
        <p>This signs you out on every device.</p>
        <TaskForm
          submit="Update password"
          onSubmit={async (f) => {
            await api("/users/me/password", {
              method: "POST",
              body: {
                current_password: f.get("current"),
                new_password: f.get("new"),
              },
            });
            auth.clear("Password updated. Please sign in again.");
          }}
        >
          <Field
            label="Current password"
            name="current"
            type="password"
            required
            maxLength={128}
            autoComplete="current-password"
          />
          <Field
            label="New password"
            name="new"
            type="password"
            required
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
          />
        </TaskForm>
      </div>
    </section>
  );
}
const catalogCache = new Map();
function useCatalog(kind, country) {
  return useLoad(async () => {
    const key = `${kind}:${country}`;
    if (catalogCache.has(key)) return catalogCache.get(key);
    let all = [],
      offset = 0,
      total = 1;
    while (offset < total) {
      const result = await api(
        `/catalog?kind=${kind}&limit=100&offset=${offset}${country ? `&country=${encodeURIComponent(country)}` : ""}`,
      );
      all.push(...result.items);
      total = result.total;
      offset += 100;
    }
    catalogCache.set(key, all);
    return all;
  }, [kind, country]);
}
function Explore() {
  const [kind, setKind] = useState("attraction"),
    [country, setCountry] = useState(""),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(0);
  const coverage = useLoad(() => api("/catalog/coverage")),
    catalog = useCatalog(kind, country);
  const filtered = (catalog.data || []).filter((x) =>
    [x.name, x.country, x.city_or_region, ...x.categories]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  useEffect(() => setPage(0), [kind, country, query]);
  return (
    <section className="wrap section">
      <p className="eyebrow">FOLLOW YOUR CURIOSITY</p>
      <h1 className="page-title">Somewhere worth sharing.</h1>
      <p className="lead">
        Explore real catalog listings, then make a plan with your people.
      </p>
      <div className="notice">
        Attractions: Hawaii and Pakistan. Hotels: historical international
        listings, not bookable inventory. No destination photos, prices or live
        availability are supplied.
      </div>
      <div className="filter-bar">
        <Field label="Listing type">
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setCountry("");
            }}
          >
            <option value="attraction">Attractions</option>
            <option value="hotel">Hotels</option>
          </select>
        </Field>
        <Field label="Country or territory">
          <select value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="">All available labels</option>
            {Object.keys(coverage.data?.country_counts_by_kind[kind] || {})
              .filter((x) => x !== "__unknown__")
              .sort()
              .map((c) => (
                <option key={c}>{c}</option>
              ))}
          </select>
        </Field>
        <Field
          label="Search catalog"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Name, region or category"
        />
      </div>
      {catalog.busy ? (
        <Loading />
      ) : catalog.error ? (
        <>
          <ErrorNote>{catalog.error}</ErrorNote>
          <Action onClick={catalog.reload}>Retry catalog</Action>
        </>
      ) : (
        <>
          <p className="muted">
            {filtered.length.toLocaleString()} matching{" "}
            {kind === "hotel" ? "hotel" : "attraction"} listings · search covers
            all loaded results for these filters
          </p>
          {filtered.length ? (
            <div className="cards">
              {filtered.slice(page * 12, page * 12 + 12).map((x) => (
                <DestinationCard key={x.destination_id} item={x} />
              ))}
            </div>
          ) : (
            <Empty title="No matching places yet">
              Try different terms or filters. We won’t substitute invented
              listings.
            </Empty>
          )}
          <div className="pagination">
            <button
              className="button secondary"
              disabled={page === 0}
              onClick={() => setPage((x) => x - 1)}
            >
              ← Previous
            </button>
            <span>
              Page {page + 1} of {Math.max(1, Math.ceil(filtered.length / 12))}
            </span>
            <button
              className="button secondary"
              disabled={(page + 1) * 12 >= filtered.length}
              onClick={() => setPage((x) => x + 1)}
            >
              Next →
            </button>
          </div>
        </>
      )}
    </section>
  );
}
function GroupPage() {
  const { id } = useParams(),
    auth = useAuth(),
    navigate = useNavigate();
  const [tab, setTab] = useState("Preferences");
  const [alternative, setAlternative] = useState("");
  const [toast, setToast] = useState("");
  const load = useLoad(async () => {
    const [group, members, prefs, runs, itinerary, planning] =
      await Promise.all([
        api(`/groups/${id}`),
        api(`/groups/${id}/members`),
        api(`/groups/${id}/preferences/me`).catch((e) => {
          if (e.status === 404) return null;
          throw e;
        }),
        api(`/groups/${id}/recommendations`),
        api(`/groups/${id}/itinerary`),
        api(`/groups/${id}/planning`),
      ]);
    return { group, members, prefs, runs, itinerary, planning };
  }, [id, auth.user.id]);
  if (load.busy) return <Loading />;
  if (load.error)
    return (
      <section className="wrap section">
        <ErrorNote>{load.error}</ErrorNote>
        <Link to="/dashboard">Back to your groups</Link>
        <Action onClick={load.reload}>Retry</Action>
      </section>
    );
  const { group, members, prefs, runs, itinerary, planning } = load.data,
    owner = group.owner_id === auth.user.id;
  const refresh = (message) => {
    if (typeof message === "string") setToast(message);
    load.reload();
  };
  return (
    <section className="wrap section">
      <Link className="text-link" to="/dashboard">
        ← My trips
      </Link>
      <div className="section-heading group-heading">
        <div>
          <p className="eyebrow">
            {group.archived ? "ARCHIVED GROUP" : "YOUR SHARED ADVENTURE"}
          </p>
          <h1 className="page-title">{group.name}</h1>
          <p>
            {members.length} members ·{" "}
            {owner ? "You’re organizing" : "Every preference matters"}
          </p>
        </div>
        <Action onClick={load.reload}>Refresh group</Action>
      </div>
      {toast && (
        <p role="status" className="success">
          {toast}
        </p>
      )}
      {owner && auth.invites[id] && <Invitation code={auth.invites[id]} />}
      <PlanningOverview
        planning={planning}
        onEdit={() => setTab("Preferences")}
        onConsider={(country) => {
          setAlternative(country);
          setTab("Recommendations");
        }}
      />
      <div className="tabs" role="navigation" aria-label="Group sections">
        {[
          "Preferences",
          "Recommendations",
          "Itinerary",
          "Members",
          ...(owner ? ["Manage"] : []),
        ].map((x) => (
          <button
            key={x}
            type="button"
            className={tab === x ? "active" : ""}
            onClick={() => setTab(x)}
          >
            {x}
          </button>
        ))}
      </div>
      {group.archived && (
        <div className="notice">
          This group is archived. Plans can be read; the owner can reopen it in
          Manage.
        </div>
      )}
      {tab === "Preferences" && (
        <PreferencesForm
          groupId={id}
          saved={prefs?.values}
          disabled={group.archived}
          reload={refresh}
        />
      )}{" "}
      {tab === "Recommendations" && (
        <Recommendations
          group={group}
          runs={runs}
          key={alternative}
          alternative={alternative}
          availability={planning.availability}
          owner={owner}
          reload={refresh}
        />
      )}{" "}
      {tab === "Itinerary" && (
        <Itinerary
          group={group}
          items={itinerary}
          availability={planning.availability}
          owner={owner}
          reload={refresh}
        />
      )}{" "}
      {tab === "Members" && (
        <div className="panel">
          <h2>Your travel circle</h2>
          {members.map((m) => (
            <div className="member-row" key={m.user_id}>
              <span className="avatar">{m.display_name[0].toUpperCase()}</span>
              <div>
                <strong>
                  {m.display_name}
                  {m.user_id === auth.user.id ? " (you)" : ""}
                </strong>
                <small>{m.role}</small>
              </div>
              {m.user_id !== group.owner_id &&
                (owner || m.user_id === auth.user.id) && (
                  <Action
                    danger
                    onClick={async () => {
                      if (
                        !confirm(
                          "Remove this membership? Preferences and votes will be removed.",
                        )
                      )
                        return;
                      await api(`/groups/${id}/members/${m.user_id}`, {
                        method: "DELETE",
                      });
                      if (m.user_id === auth.user.id) navigate("/dashboard");
                      else load.reload();
                    }}
                  >
                    {m.user_id === auth.user.id
                      ? "Leave group"
                      : "Remove member"}
                  </Action>
                )}
            </div>
          ))}
        </div>
      )}{" "}
      {tab === "Manage" && owner && (
        <div className="two-column">
          <div className="panel">
            <h2>Group settings</h2>
            <TaskForm
              submit="Save group"
              onSubmit={async (f) => {
                await api(`/groups/${id}`, {
                  method: "PATCH",
                  body: {
                    name: f.get("name"),
                    archived: f.get("archived") === "on",
                  },
                });
                load.reload();
              }}
            >
              <Field
                label="Group name"
                name="name"
                required
                maxLength={100}
                defaultValue={group.name}
              />
              <label className="check">
                <input
                  type="checkbox"
                  name="archived"
                  defaultChecked={group.archived}
                />{" "}
                Archive this group
              </label>
            </TaskForm>
            <h3>Invitation</h3>
            <p>Codes are shown once. Rotating invalidates older invitations.</p>
            <Action
              disabled={group.archived}
              onClick={async () => {
                const r = await api(`/groups/${id}/invitation`, {
                  method: "POST",
                });
                auth.saveInvite(id, r.invitation_code);
              }}
            >
              Create new invitation
            </Action>
            {auth.invites[id] && <Invitation code={auth.invites[id]} />}
          </div>
          <div className="panel">
            <h2>Ownership</h2>
            <TaskForm
              disabled={group.archived}
              submit="Transfer ownership"
              onSubmit={async (f) => {
                if (!confirm("Transfer ownership to this member?")) return;
                await api(`/groups/${id}/transfer-ownership`, {
                  method: "POST",
                  body: { user_id: f.get("user_id") },
                });
                load.reload();
                setTab("Members");
              }}
            >
              <Field label="New owner">
                <select name="user_id" required disabled={group.archived}>
                  <option value="">Choose a member</option>
                  {members
                    .filter((x) => x.user_id !== auth.user.id)
                    .map((x) => (
                      <option key={x.user_id} value={x.user_id}>
                        {x.display_name}
                      </option>
                    ))}
                </select>
              </Field>
            </TaskForm>
            <h3>Delete group</h3>
            <p>
              This permanently removes the group’s preferences, votes and
              itinerary.
            </p>
            <Action
              danger
              onClick={async () => {
                if (
                  !confirm("Permanently delete this group and all its plans?")
                )
                  return;
                await api(`/groups/${id}`, { method: "DELETE" });
                navigate("/dashboard");
              }}
            >
              Delete group
            </Action>
          </div>
        </div>
      )}
    </section>
  );
}
function Invitation({ code }) {
  const [show, setShow] = useState(false);
  return (
    <div className="invitation">
      <Field
        label="Private invitation code"
        type={show ? "text" : "password"}
        value={code}
        readOnly
        autoComplete="off"
      />
      <button className="button secondary" onClick={() => setShow((x) => !x)}>
        {show ? "Hide" : "Show"} code
      </button>
      <Action
        onClick={async () => {
          if (!navigator.clipboard)
            throw new Error(
              "Clipboard unavailable. Show the code and copy it manually.",
            );
          await navigator.clipboard.writeText(code);
        }}
      >
        Copy code
      </Action>
      <small>
        Share privately. This code is kept only in this browser session.
      </small>
    </div>
  );
}
function PreferencesForm({ groupId, saved, disabled, reload }) {
  const coverage = useLoad(() => api("/catalog/coverage"));
  const [countries, setCountries] = useState(saved?.preferred_countries || []),
    [destinations, setDestinations] = useState(
      saved?.preferred_destination_ids || [],
    ),
    [pickCountry, setPickCountry] = useState("Pakistan");
  const choices = useCatalog("attraction", pickCountry);
  return (
    <div className="preferences-layout">
      <div className="panel">
        <p className="eyebrow">YOUR KIND OF JOURNEY</p>
        <h2>What would make this trip yours?</h2>
        <p>
          Only you can change your preferences. Everyone’s choices feed into the
          shared plan.
        </p>
        <TaskForm
          disabled={disabled}
          submit="Save preferences"
          onSubmit={async (f) => {
            if (disabled)
              throw new Error("Reopen the group to update preferences.");
            const optional = (name) => f.get(name) || null;
            await api(`/groups/${groupId}/preferences/me`, {
              method: "PUT",
              body: {
                interests: split(f.get("interests")),
                free_text: f.get("free_text"),
                preferred_countries: countries,
                country_requirement: f.get("country_requirement"),
                destination_requirement: f.get("destination_requirement"),
                preferred_regions: split(f.get("regions")),
                preferred_destination_ids: destinations,
                budget_min: optional("budget_min"),
                budget_max: optional("budget_max"),
                currency: optional("currency"),
                start_date: optional("start_date"),
                end_date: optional("end_date"),
              },
            });
            reload("Preferences saved.");
            return "";
          }}
        >
          <fieldset disabled={disabled}>
            <Field
              label="Interests and categories (comma-separated)"
              name="interests"
              placeholder="Hiking, lakes, history"
              defaultValue={saved?.interests?.join(", ")}
            />
            <Field label="Tell us more">
              <textarea
                name="free_text"
                maxLength={1000}
                placeholder="What do you love discovering?"
                defaultValue={saved?.free_text || ""}
              />
            </Field>
            <Field label="Preferred countries (optional)">
              <select
                multiple
                value={countries}
                onChange={(e) =>
                  setCountries(
                    [...e.target.selectedOptions].map((x) => x.value),
                  )
                }
              >
                {Object.keys(coverage.data?.country_counts || {})
                  .sort()
                  .map((c) => (
                    <option key={c}>{c}</option>
                  ))}
              </select>
            </Field>
            <Field label="Country flexibility">
              <select
                name="country_requirement"
                defaultValue={
                  saved ? saved.country_requirement || "mandatory" : "preferred"
                }
              >
                <option value="preferred">
                  Preferred — consider alternatives
                </option>
                <option value="mandatory">
                  Mandatory — only these countries
                </option>
              </select>
            </Field>
            <small>
              Use Ctrl/Command to select multiple labels. No selection means no
              country restriction. Flexible choices influence ranking; mandatory
              choices restrict the catalog. Existing saved choices remain
              mandatory until you change them.
            </small>
            <Field
              label="Required regions (comma-separated, exact catalog labels)"
              name="regions"
              placeholder="Hawaii, Punjab"
              defaultValue={saved?.preferred_regions?.join(", ")}
            />
            <details>
              <summary>Choose specific attractions (optional)</summary>
              <Field label="Attraction country">
                <select
                  value={pickCountry}
                  onChange={(e) => setPickCountry(e.target.value)}
                >
                  <option>Pakistan</option>
                  <option value="United States">United States · Hawaii</option>
                </select>
              </Field>
              {choices.busy ? (
                <Loading />
              ) : (
                <>
                  <ErrorNote>{choices.error}</ErrorNote>
                  <Field label="Specific attractions">
                    <select
                      multiple
                      value={destinations}
                      onChange={(e) => {
                        const current = new Set(
                          (choices.data || []).map((x) => x.destination_id),
                        );
                        setDestinations([
                          ...destinations.filter((id) => !current.has(id)),
                          ...[...e.target.selectedOptions].map((x) => x.value),
                        ]);
                      }}
                    >
                      {choices.data?.map((x) => (
                        <option key={x.destination_id} value={x.destination_id}>
                          {x.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </>
              )}
              <Field label="Destination flexibility">
                <select
                  name="destination_requirement"
                  defaultValue={
                    saved
                      ? saved.destination_requirement || "mandatory"
                      : "preferred"
                  }
                >
                  <option value="preferred">
                    Preferred — consider alternatives
                  </option>
                  <option value="mandatory">
                    Mandatory — only selected attractions
                  </option>
                </select>
              </Field>
              <p>
                {destinations.length} selected. Mandatory selections must
                overlap across members.
              </p>
              <button
                type="button"
                className="text-link"
                onClick={() => setDestinations([])}
              >
                Clear specific destinations
              </button>
            </details>
            <div className="form-grid">
              <Field
                label="Minimum budget"
                name="budget_min"
                type="number"
                min="0"
                max="1000000000"
                step="0.01"
                defaultValue={saved?.budget_min || ""}
              />
              <Field
                label="Maximum budget"
                name="budget_max"
                type="number"
                min="0"
                max="1000000000"
                step="0.01"
                defaultValue={saved?.budget_max || ""}
              />
              <Field
                label="Currency (3 uppercase letters)"
                name="currency"
                pattern="[A-Z]{3}"
                maxLength={3}
                placeholder="USD"
                defaultValue={saved?.currency || ""}
              />
              <span />
              <Field
                label="Travel start date"
                name="start_date"
                type="date"
                defaultValue={saved?.start_date || ""}
              />
              <Field
                label="Travel end date"
                name="end_date"
                type="date"
                defaultValue={saved?.end_date || ""}
              />
            </div>
          </fieldset>
        </TaskForm>
      </div>
      <aside className="panel sidebar-note">
        <span>✳</span>
        <h3>A clearer plan, without false promises.</h3>
        <p>
          Budgets and dates help record your plans. The catalog does not provide
          comparable prices or live venue availability, so they do not filter
          recommendations.
        </p>
        <p>
          Attraction coverage is currently Hawaii and Pakistan. International
          hotel records are historical metadata.
        </p>
        <p>
          New accounts use your stated interests, not historical users’
          identities.
        </p>
      </aside>
    </div>
  );
}
function Recommendations({
  group,
  runs,
  owner,
  reload,
  availability,
  alternative,
}) {
  const [selected, setSelected] = useState(runs[0]?.id || ""),
    [type, setType] = useState("group");
  const run = runs.find((r) => r.id === selected) || runs[0];
  return (
    <>
      <div className="panel">
        <h2>Find your common ground</h2>
        <p>
          Every member must save interests first. Conflicting hard destination
          choices need to be resolved together.
        </p>
        <TaskForm
          disabled={group.archived}
          submit="Generate recommendations"
          onSubmit={async (f) => {
            if (group.archived) throw new Error("Reopen the group first.");
            const body = {
              scope: f.get("scope"),
              kind: f.get("kind"),
              method: f.get("method"),
              top_k: Number(f.get("top_k")),
            };
            if (f.get("country")) body.country = f.get("country");
            const r = await api(
              `/groups/${group.id}/recommendations${type === "individual" ? "/individual" : ""}`,
              { method: "POST", body },
            );
            setSelected(r.id);
            reload("Recommendations generated.");
          }}
        >
          <div className="form-grid">
            <Field label="Plan for">
              <select value={type} onChange={(e) => setType(e.target.value)}>
                <option value="group">Everyone in the group</option>
                <option value="individual">Just my preferences</option>
              </select>
            </Field>
            <Field label="Catalog scope">
              <select name="scope" defaultValue="catalog">
                <option value="pakistan">Pakistan attractions</option>
                <option value="hawaii">Hawaii attractions</option>
                <option value="catalog">International catalog metadata</option>
              </select>
            </Field>
            <Field label="Listing type">
              <select name="kind">
                <option value="attraction">Attractions</option>
                <option value="hotel">Hotels (metadata only)</option>
              </select>
            </Field>
            <Field
              label="Country filter (optional, exact catalog label)"
              name="country"
              defaultValue={alternative}
              placeholder="Leave blank to compare covered countries"
            />
            <Field label="How to find agreement">
              <select name="method">
                <option value="adaptive_consensus">
                  Balance everyone’s preferences
                </option>
                <option value="average">Average preference</option>
                <option value="least_misery">
                  Prioritize the least satisfied
                </option>
              </select>
            </Field>
            <Field
              label="Number of suggestions"
              name="top_k"
              type="number"
              min="1"
              max="20"
              defaultValue="10"
              required
            />
          </div>
        </TaskForm>
      </div>
      {runs.length ? (
        <>
          <Field label="Saved recommendation list">
            <select
              value={run?.id || ""}
              onChange={(e) => setSelected(e.target.value)}
            >
              {runs.map((r, i) => (
                <option key={r.id} value={r.id}>
                  {new Date(r.created_at).toLocaleString()} ·{" "}
                  {r.method === "individual" ? "Individual" : "Group"} ·{" "}
                  {r.is_current ? "Current" : "Needs regeneration"} · {i + 1}
                </option>
              ))}
            </select>
          </Field>
          <RecommendationRun
            key={run.id + String(run.is_current)}
            run={run}
            availability={availability}
            group={group}
            owner={owner}
            reload={reload}
          />
        </>
      ) : (
        <Empty title="The first step is a shared shortlist">
          Save preferences, then generate recommendations for your group.
        </Empty>
      )}
    </>
  );
}
function RecommendationRun({ run, group, owner, reload, availability }) {
  const totals = useLoad(
      () =>
        run.method === "individual"
          ? Promise.resolve(null)
          : api(`/groups/${group.id}/recommendations/${run.id}/voting`),
      [run.id],
    ),
    eligible = run.is_current && run.method !== "individual" && !group.archived;
  const [choice, setChoice] = useState("");
  return (
    <>
      <RecommendationInfo
        run={run}
        approach={
          run.payload.mode
            ? modeName[run.payload.mode] || run.payload.mode
            : [...new Set(Object.values(run.payload.member_modes || {}))]
                .map((x) => modeName[x] || x)
                .join(" / ")
        }
      />
      <ErrorNote>{totals.error}</ErrorNote>
      <VotingBoard
        summary={totals.data}
        results={run.payload.results}
        onRefresh={totals.reload}
      />
      <div className="cards">
        {run.payload.results.map((item) => (
          <DestinationCard key={item.destination_id} item={item}>
            <p className="vote-count">
              {run.method !== "individual"
                ? totals.busy
                  ? "Loading votes…"
                  : `${totals.data?.choices.find((v) => v.destination_id === item.destination_id)?.votes || 0} group votes`
                : "Individual suggestion"}
            </p>
            {eligible && (
              <Action
                onClick={async () => {
                  await api(
                    `/groups/${group.id}/recommendations/${run.id}/vote`,
                    {
                      method: "PUT",
                      body: { destination_id: item.destination_id },
                    },
                  );
                  setChoice(item.destination_id);
                  totals.reload();
                }}
              >
                {(totals.data?.own_destination_id || choice) ===
                item.destination_id
                  ? "Your current vote"
                  : "Vote for this place"}
              </Action>
            )}
            {owner && eligible && (
              <details className="itinerary-add">
                <summary>Add to itinerary</summary>
                <p>
                  {availability?.message} Leave the date blank to keep this stop
                  unscheduled.
                </p>
                <TaskForm
                  submit="Add itinerary item"
                  onSubmit={async (f) => {
                    await api(`/groups/${group.id}/itinerary`, {
                      method: "POST",
                      body: {
                        recommendation_id: run.id,
                        destination_id: item.destination_id,
                        position: Number(f.get("position")),
                        planned_date: f.get("date") || null,
                        notes: f.get("notes"),
                      },
                    });
                    reload("Added to itinerary.");
                    return "Added. Open the Itinerary section to view your plan.";
                  }}
                >
                  <Field
                    label={`Position for ${item.name}`}
                    name="position"
                    type="number"
                    min="1"
                    max="1000"
                    required
                  />
                  <Field
                    label={`Visit date for ${item.name}`}
                    {...dateBounds(availability)}
                    name="date"
                    type="date"
                  />
                  <Field
                    label={`Notes for ${item.name}`}
                    name="notes"
                    maxLength={1000}
                  />
                </TaskForm>
              </details>
            )}
          </DestinationCard>
        ))}
      </div>
      {eligible && (
        <Action
          onClick={async () => {
            await api(`/groups/${group.id}/recommendations/${run.id}/vote`, {
              method: "DELETE",
            });
            setChoice("");
            totals.reload();
          }}
        >
          Withdraw my vote
        </Action>
      )}
      <p className="muted">
        Votes are one per member per list. Choosing another place changes your
        vote. Totals refresh after voting or when you refresh the group; they
        are not live updates.
      </p>
    </>
  );
}
function Itinerary({ group, items, owner, reload, availability }) {
  return (
    <>
      <div className="section-heading">
        <div>
          <p className="eyebrow">FROM SHORTLIST TO SHARED PLAN</p>
          <h2>Your itinerary</h2>
        </div>
      </div>
      <div className="notice">
        {availability?.message} An itinerary is a plan, not a booking. Dates are
        checked against saved member travel windows, not venue opening or
        availability.
      </div>
      {items.length ? (
        items.map((item) => (
          <article className="panel itinerary-item" key={item.id}>
            <span className="itinerary-number">
              {item.position.toString().padStart(2, "0")}
            </span>
            <div>
              <p className="eyebrow">
                {item.planned_date || "DATE TO BE DECIDED"}
              </p>
              <h3>{item.destination_snapshot.name}</h3>
              <DestinationPhoto
                item={item.destination_snapshot}
                variant="itinerary"
              />
              <p>
                {[
                  item.destination_snapshot.city_or_region,
                  item.destination_snapshot.country,
                ]
                  .filter(Boolean)
                  .join(", ")}
              </p>
              <p>{item.notes}</p>
              {item.planned_date &&
                (availability?.status === "conflict" ||
                  (availability?.start_date &&
                    item.planned_date < availability.start_date) ||
                  (availability?.end_date &&
                    item.planned_date > availability.end_date)) && (
                  <p className="notice">
                    This stop’s saved date no longer fits the shared
                    availability. The organizer must reschedule it or clear its
                    date; nothing was changed automatically.
                  </p>
                )}
              {owner && !group.archived && (
                <details>
                  <summary>Edit this stop</summary>
                  <TaskForm
                    submit="Save itinerary item"
                    onSubmit={async (f) => {
                      if (availability?.status === "conflict" && f.get("date"))
                        throw new Error(
                          "No common dates: clear the planned date or ask members to update availability.",
                        );
                      await api(`/groups/${group.id}/itinerary/${item.id}`, {
                        method: "PATCH",
                        body: {
                          position: Number(f.get("position")),
                          planned_date: f.get("date") || null,
                          notes: f.get("notes"),
                        },
                      });
                      reload();
                    }}
                  >
                    <div className="form-grid">
                      <Field
                        label="Position"
                        name="position"
                        type="number"
                        min="1"
                        max="1000"
                        defaultValue={item.position}
                        required
                      />
                      <Field
                        label="Planned date"
                        min={availability?.start_date || undefined}
                        max={availability?.end_date || undefined}
                        name="date"
                        type="date"
                        defaultValue={item.planned_date || ""}
                      />
                    </div>
                    <Field label="Plan notes">
                      <textarea
                        name="notes"
                        maxLength={1000}
                        defaultValue={item.notes}
                      />
                    </Field>
                  </TaskForm>
                  <Action
                    danger
                    onClick={async () => {
                      if (!confirm("Remove this stop from the itinerary?"))
                        return;
                      await api(`/groups/${group.id}/itinerary/${item.id}`, {
                        method: "DELETE",
                      });
                      reload();
                    }}
                  >
                    Remove stop
                  </Action>
                </details>
              )}
            </div>
          </article>
        ))
      ) : (
        <Empty title="A shared adventure, still unwritten">
          The owner can add stops from a current group recommendation list.
        </Empty>
      )}
    </>
  );
}
export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}
