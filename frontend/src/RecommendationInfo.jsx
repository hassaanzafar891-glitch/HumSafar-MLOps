import React from "react";

const needsAttention = (warning) =>
  /conflict|restriction|no_compatible|error|preferences_required/.test(
    warning.code,
  );

export default function RecommendationInfo({ run, approach }) {
  const warnings = run.warnings || [];
  const applicationUser = warnings.some(
    (w) => w.code === "new_application_users",
  );
  return (
    <section
      className="recommendation-context"
      aria-label="Recommendation information"
    >
      <p className="recommendation-mode">
        <strong>{approach}</strong>
        {applicationUser && (
          <span>
            New accounts use stated preferences. The trained Hawaii model
            requires compatible historical interaction data.
          </span>
        )}
      </p>
      {!run.is_current && (
        <p className="planning-alert" role="alert">
          Preferences or membership changed. Generate a new list before voting
          or planning.
        </p>
      )}
      {warnings.filter(needsAttention).map((w, i) => (
        <p className="planning-alert" role="alert" key={`${w.code}-${i}`}>
          {w.message}
        </p>
      ))}
      {run.method === "individual" && (
        <p className="individual-list-note">
          Your individual suggestions cannot be used for group voting or the
          itinerary.
        </p>
      )}
      <details className="recommendation-explainer">
        <summary>How recommendations work</summary>
        <div>
          <p>
            {run.method === "individual"
              ? "Suggestions reflect the available metadata and your preferences."
              : "Group suggestions balance predicted preference scores, not verified real-world satisfaction."}
          </p>
          {run.payload.score_interpretation && (
            <p>{run.payload.score_interpretation}</p>
          )}
          <ul>
            {warnings
              .filter((w) => !needsAttention(w))
              .map((w, i) => (
                <li key={`${w.code}-${i}`}>{w.message}</li>
              ))}
          </ul>
        </div>
      </details>
    </section>
  );
}
