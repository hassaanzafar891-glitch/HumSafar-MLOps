import React from "react";

export function dateBounds(availability) {
  return {
    min: availability?.start_date || undefined,
    max: availability?.end_date || undefined,
    disabled: availability?.status === "conflict",
  };
}

export function PlanningOverview({ planning, onEdit, onConsider }) {
  const a = planning.availability;
  return (
    <section className="planning-board" aria-label="Shared travel planning">
      <div className="planning-intro">
        <p className="eyebrow">PLAN TOGETHER, TRAVEL TOGETHER</p>
        <h2>Find a place. Find your moment.</h2>
        <p>
          1. Share preferences · 2. Compare suggestions · 3. Vote · 4. Build
          your itinerary
        </p>
      </div>
      <div className="planning-grid">
        <article>
          <span className="planning-step">01 / WHERE</span>
          <h3>
            {planning.country_status === "mandatory_conflict"
              ? "Country restrictions need attention"
              : "Room for everyone’s wishes"}
          </h3>
          {planning.messages.map((m) => (
            <p key={m}>{m}</p>
          ))}
          <div className="coverage-pills">
            {Object.entries(planning.compatible_countries).map(([c, n]) => (
              <button type="button" key={c} onClick={() => onConsider(c)}>
                Consider {c} · {n} attractions
              </button>
            ))}
          </div>
          {planning.unavailable_preferred_countries.length > 0 && (
            <p>
              No attraction coverage:{" "}
              {planning.unavailable_preferred_countries.join(", ")}
            </p>
          )}
        </article>
        <article>
          <span className="planning-step">02 / WHEN</span>
          <h3>
            {a.status === "overlap"
              ? "Your common travel window"
              : a.status === "conflict"
                ? "No shared dates yet"
                : "Let’s coordinate dates"}
          </h3>
          {a.start_date && (
            <p className="shared-dates">
              {a.start_date} — {a.end_date}
            </p>
          )}
          <p>{a.message}</p>
          <small>
            {a.members_with_dates} of {a.members_total} members supplied dates.
          </small>
        </article>
      </div>
      <div className="member-plans">
        {planning.members.map((m) => (
          <article key={m.user_id}>
            <strong>{m.display_name}</strong>
            <p>
              {m.has_preferences
                ? m.preferred_countries.join(", ") ||
                  "Open to covered countries"
                : "Preferences not saved"}{" "}
              ·{" "}
              {m.country_requirement === "mandatory"
                ? "Mandatory if selected"
                : "Flexible preference"}
            </p>
            {m.preferred_destination_ids.length > 0 && (
              <small>
                {m.preferred_destination_ids.length} selected destinations ·{" "}
                {m.destination_requirement}
              </small>
            )}
            {m.preferred_regions.length > 0 && (
              <p>Required regions: {m.preferred_regions.join(", ")}</p>
            )}
            <p>
              {m.start_date
                ? `${m.start_date} → ${m.end_date}`
                : "Dates not supplied"}
            </p>
          </article>
        ))}
      </div>
      <button type="button" className="text-link" onClick={onEdit}>
        Update my own preferences & dates →
      </button>
    </section>
  );
}

export function VotingBoard({ summary, results, onRefresh }) {
  if (!summary) return null;
  const names = Object.fromEntries(
    results.map((i) => [i.destination_id, i.name]),
  );
  return (
    <section className="panel voting-board" aria-label="Group voting results">
      <p className="eyebrow">COMPARE, THEN CHOOSE</p>
      <h2>Your group’s shortlist</h2>
      <p>
        {summary.total_votes} of {summary.total_members} members have voted. One
        choice per member; choosing another destination changes your vote.
      </p>
      <progress
        aria-label="Members who voted"
        value={summary.total_votes}
        max={summary.total_members || 1}
      />
      <div className="comparison-scroll">
        <table>
          <caption>Recommendation comparison</caption>
          <thead>
            <tr>
              <th>Destination</th>
              <th>Location</th>
              <th>Votes</th>
            </tr>
          </thead>
          <tbody>
            {results.map((i) => (
              <tr key={i.destination_id}>
                <td>{i.name}</td>
                <td>
                  {[i.city_or_region, i.country].filter(Boolean).join(", ")}
                </td>
                <td>
                  {summary.choices.find(
                    (v) => v.destination_id === i.destination_id,
                  )?.votes || 0}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="voter-list">
        {summary.members.map((m) => (
          <li key={m.user_id}>
            <strong>{m.display_name}</strong>
            <span>{names[m.destination_id] || "Not voted yet"}</span>
          </li>
        ))}
      </ul>
      <p>
        Votes are visible to group members. Voting never adds a stop to the
        itinerary; the organizer makes that separate decision.
      </p>
      <button type="button" onClick={onRefresh}>
        Refresh votes
      </button>
    </section>
  );
}
