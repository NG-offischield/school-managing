import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_API_URL, logApiFailure, normalizeApiUrl, normalizeSiteUrl } from "@/lib/api-url";

describe("API base URL (DJANGO_INTERNAL_API_URL)", () => {
  it("accepts the host alone, with or without /api/v1, scheme or trailing slash", () => {
    for (const raw of [
      "https://isbree-api.onrender.com",
      "https://isbree-api.onrender.com/",
      "https://isbree-api.onrender.com/api/v1",
      "https://isbree-api.onrender.com/api/v1/",
      "isbree-api.onrender.com",
      "  https://isbree-api.onrender.com/api/v1  ",
    ]) {
      expect(normalizeApiUrl(raw)).toBe("https://isbree-api.onrender.com/api/v1");
    }
  });

  it("never doubles the prefix and keeps an explicit version or a local http address", () => {
    expect(normalizeApiUrl("https://h.example/api/v2")).toBe("https://h.example/api/v2");
    expect(normalizeApiUrl("http://localhost:8000/api/v1")).toBe("http://localhost:8000/api/v1");
    expect(normalizeApiUrl(undefined)).toBe(DEFAULT_API_URL);
    expect(normalizeApiUrl("")).toBe(DEFAULT_API_URL);
  });

  it("normalises the public addresses without adding a path", () => {
    expect(normalizeSiteUrl("isbree-portal.onrender.com/", "x")).toBe("https://isbree-portal.onrender.com");
    expect(normalizeSiteUrl("", "http://localhost:3001")).toBe("http://localhost:3001");
  });
});

describe("API failure log", () => {
  afterEach(() => vi.restoreAllMocks());

  it("names the call and the outcome, never the query string", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    logApiFailure("GET", "https://api.example/api/v1/portal/resources/?role=PARENT&student=abc", 404);
    logApiFailure("POST", "https://api.example/api/v1/auth/login/", Object.assign(new Error("x"), { name: "TimeoutError" }));
    expect(error.mock.calls.map((c) => c[0])).toEqual([
      "[isbree] API GET https://api.example/api/v1/portal/resources/ -> HTTP 404",
      "[isbree] API POST https://api.example/api/v1/auth/login/ -> network error TimeoutError",
    ]);
  });
});
