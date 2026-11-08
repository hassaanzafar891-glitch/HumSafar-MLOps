import { afterEach, describe, it, expect, vi } from "vitest";
import { api, setSession, errorMessage } from "./api.js";
afterEach(() => {
  vi.unstubAllGlobals();
  setSession(null);
});
describe("API boundary", () => {
  it("posts form login without persisting credentials", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ access_token: "test-token" }),
      });
    vi.stubGlobal("fetch", fetch);
    await api("/auth/login", {
      method: "POST",
      form: { username: "test@example.com", password: "fixture" },
    });
    expect(fetch.mock.calls[0][0]).toBe("/api/auth/login");
    expect(fetch.mock.calls[0][1].body).toBeInstanceOf(URLSearchParams);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
  it("attaches an in-memory bearer token and clears expired sessions", async () => {
    const expired = vi.fn();
    setSession("fixture-token", expired);
    const fetch = vi
      .fn()
      .mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Expired" }),
      });
    vi.stubGlobal("fetch", fetch);
    await expect(api("/users/me")).rejects.toThrow("Expired");
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe(
      "Bearer fixture-token",
    );
    expect(expired).toHaveBeenCalledOnce();
    fetch.mockResolvedValue({ ok: true, status: 204 });
    await api("/health");
    expect(fetch.mock.calls[1][1].headers.Authorization).toBeUndefined();
  });
  it("surfaces structured backend errors", () => {
    expect(
      errorMessage({
        code: "no_compatible_candidates",
        message: "No matching places",
      }),
    ).toBe("No matching places");
    expect(
      errorMessage([{ loc: ["body", "budget_min"], msg: "Out of range" }]),
    ).toContain("budget_min: Out of range");
  });
});
