import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { it, expect, vi, afterEach } from "vitest";
import App from "./App.jsx";
afterEach(() => vi.unstubAllGlobals());
it("protects private pages without accessing private APIs", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <App />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "Let’s pick up the plan" }),
  ).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});
it("registers through the real contract then shows login", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ id: "isolated-test-user" }),
    });
  vi.stubGlobal("fetch", fetch);
  render(
    <MemoryRouter initialEntries={["/register"]}>
      <App />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Your name"), "Example");
  await user.type(
    screen.getByLabelText("Email address"),
    "example@example.com",
  );
  await user.type(screen.getByLabelText("Password"), "test-only-password");
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(
    await screen.findByText("Account created. Log in to start planning."),
  ).toBeInTheDocument();
  expect(fetch.mock.calls[0][0]).toBe("/api/auth/register");
  expect(JSON.parse(fetch.mock.calls[0][1].body).display_name).toBe("Example");
  expect(localStorage.length).toBe(0);
});
