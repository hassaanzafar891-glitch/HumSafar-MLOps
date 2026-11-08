import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect } from "vitest";
import RecommendationInfo from "./RecommendationInfo.jsx";

const run = {
  method: "adaptive_consensus",
  is_current: true,
  payload: { score_interpretation: "Ranking utility is not a probability." },
  warnings: [
    {
      code: "new_application_users",
      message: "Original backend identity disclosure.",
    },
    {
      code: "budget_filter_unsupported",
      message: "No budget filtering was applied.",
    },
    {
      code: "date_availability_unsupported",
      message: "Live venue availability is unknown.",
    },
  ],
};

it("keeps the new-user approach visible while retaining every backend disclosure in one expandable section", async () => {
  render(<RecommendationInfo run={run} approach="Preference matching" />);
  expect(screen.getByText(/New accounts use stated preferences/)).toBeVisible();
  expect(
    screen.getByText("No budget filtering was applied."),
  ).not.toBeVisible();
  await userEvent.click(screen.getByText("How recommendations work"));
  for (const warning of run.warnings)
    expect(screen.getByText(warning.message)).toBeVisible();
  expect(screen.getByText(run.payload.score_interpretation)).toBeVisible();
  await userEvent.click(screen.getByText("How recommendations work"));
  expect(
    screen.getByText("No budget filtering was applied."),
  ).not.toBeVisible();
});

it("never collapses conflicts or stale recommendation warnings", () => {
  render(
    <RecommendationInfo
      run={{
        ...run,
        is_current: false,
        warnings: [
          ...run.warnings,
          {
            code: "mandatory_restriction_conflict",
            message: "Mandatory restrictions have no common options.",
          },
          {
            code: "member_date_conflict",
            message: "Travel dates do not overlap.",
          },
        ],
      }}
      approach="Preference matching"
    />,
  );
  expect(screen.getAllByRole("alert")).toHaveLength(3);
  expect(
    screen.getByText("Mandatory restrictions have no common options."),
  ).toBeVisible();
  expect(screen.getByText("Travel dates do not overlap.")).toBeVisible();
});

it("keeps individual-list voting and itinerary limitations visible", () => {
  render(
    <RecommendationInfo
      run={{ ...run, method: "individual" }}
      approach="Content matching"
    />,
  );
  expect(
    screen.getByText(/individual suggestions cannot be used for group voting/),
  ).toBeVisible();
});

it("does not substitute a new-user claim for a compatible historical model mode", () => {
  render(
    <RecommendationInfo
      run={{ ...run, warnings: [] }}
      approach="Personalized from compatible history"
    />,
  );
  expect(screen.queryByText(/New accounts/)).not.toBeInTheDocument();
  expect(
    screen.getByText("Personalized from compatible history"),
  ).toBeVisible();
});
