import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi } from "vitest";
import { dateBounds, PlanningOverview, VotingBoard } from "./Planning.jsx";

it("constrains dates to the supplied intersection and disables conflicting dates", () => {
  expect(
    dateBounds({
      status: "overlap",
      start_date: "2030-06-03",
      end_date: "2030-06-08",
    }),
  ).toEqual({ min: "2030-06-03", max: "2030-06-08", disabled: false });
  expect(dateBounds({ status: "conflict" }).disabled).toBe(true);
  expect(dateBounds({ status: "unknown" }).min).toBeUndefined();
});
it("explains mandatory conflicts and offers only supplied catalog alternatives", async () => {
  const onEdit = vi.fn(),
    onConsider = vi.fn();
  const planning = {
    country_status: "mandatory_conflict",
    messages: ["Mandatory countries do not overlap."],
    compatible_countries: {},
    unavailable_preferred_countries: [],
    members: [],
    availability: {
      status: "conflict",
      message: "No shared dates.",
      members_with_dates: 2,
      members_total: 2,
    },
  };
  const { rerender } = render(
    <PlanningOverview
      planning={planning}
      onEdit={onEdit}
      onConsider={onConsider}
    />,
  );
  expect(
    screen.getByText("Country restrictions need attention"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Consider/ }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Update my own/ }));
  expect(onEdit).toHaveBeenCalledOnce();
  rerender(
    <PlanningOverview
      planning={{
        ...planning,
        country_status: "different_preferences",
        compatible_countries: { Pakistan: 69 },
      }}
      onConsider={onConsider}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: /Consider Pakistan/ }),
  );
  expect(onConsider).toHaveBeenCalledWith("Pakistan");
});
it("shows named votes and comparison without creating itinerary actions", async () => {
  const refresh = vi.fn();
  render(
    <VotingBoard
      summary={{
        total_votes: 1,
        total_members: 2,
        choices: [{ destination_id: "fixture", votes: 1 }],
        members: [
          {
            user_id: "a",
            display_name: "Fixture organizer",
            destination_id: "fixture",
          },
          {
            user_id: "b",
            display_name: "Fixture companion",
            destination_id: null,
          },
        ],
      }}
      results={[
        {
          destination_id: "fixture",
          name: "Fixture suggestion",
          country: "Fixture country",
        },
      ]}
      onRefresh={refresh}
    />,
  );
  expect(screen.getByText("Not voted yet")).toBeInTheDocument();
  expect(screen.getByText(/Voting never adds a stop/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Add.*itinerary/ }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Refresh votes" }));
  expect(refresh).toHaveBeenCalledOnce();
});
