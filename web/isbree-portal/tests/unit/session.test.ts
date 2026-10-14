import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SECRET = "test-secret-0123456789-abcdefghijklmnop-XYZ";

async function load() {
  vi.resetModules();
  vi.stubEnv("PORTAL_SESSION_SECRET", SECRET);
  vi.stubEnv("WEB_BFF_TOKEN", "bff-test-token");
  return {
    session: await import("@/lib/session"),
    django: await import("@/lib/django"),
  };
}

const sample = (overrides = {}) => ({
  access: "access-1",
  accessExpiresAt: Date.now() + 15 * 60_000,
  refresh: "refresh-1",
  refreshExpiresAt: Date.now() + 30 * 86_400_000,
  sessionId: "s-1",
  ...overrides,
});

describe("encrypted session cookie", () => {
  beforeEach(() => vi.unstubAllEnvs());

  it("round-trips and hides the tokens", async () => {
    const { session } = await load();
    const sealed = await session.sealSession(sample());
    expect(sealed).not.toContain("access-1");
    expect(sealed).not.toContain("refresh-1");
    expect(await session.unsealSession(sealed)).toMatchObject({ access: "access-1", sessionId: "s-1" });
  });

  it("refuses a tampered, foreign or expired cookie", async () => {
    const { session } = await load();
    const sealed = await session.sealSession(sample());
    expect(await session.unsealSession(`${sealed.slice(0, -4)}AAAA`)).toBeNull();
    expect(await session.unsealSession("not-a-cookie")).toBeNull();
    expect(await session.unsealSession(undefined)).toBeNull();
    const expired = await session.sealSession(sample({ refreshExpiresAt: Date.now() - 1000 }));
    expect(await session.unsealSession(expired)).toBeNull();
  });

  it("refuses to work without a strong secret", async () => {
    vi.resetModules();
    vi.stubEnv("PORTAL_SESSION_SECRET", "short");
    const session = await import("@/lib/session");
    await expect(session.sealSession(sample())).rejects.toThrow(/PORTAL_SESSION_SECRET/);
  });

  it("asks for a refresh one minute before the access token expires", async () => {
    const { session } = await load();
    expect(session.needsRefresh(sample({ accessExpiresAt: Date.now() + 30_000 }))).toBe(true);
    expect(session.needsRefresh(sample())).toBe(false);
  });
});

describe("token refresh", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is shared by parallel requests: a refresh token is never sent twice", async () => {
    const { django } = await load();
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        calls += 1;
        expect(JSON.parse(String(init.body))).toEqual({ refresh_token: "refresh-1" });
        expect((init.headers as Record<string, string>)["X-ISBREE-BFF"]).toBe("bff-test-token");
        await new Promise((r) => setTimeout(r, 20));
        return new Response(
          JSON.stringify({
            data: {
              access_token: "access-2",
              access_expires_in: 900,
              refresh_token: "refresh-2",
              refresh_expires_at: new Date(Date.now() + 86_400_000).toISOString(),
              session_id: "s-1",
            },
          }),
          { status: 200 },
        );
      }),
    );
    const results = await Promise.all([1, 2, 3].map(() => django.refreshSession(sample(), "203.0.113.5")));
    expect(calls).toBe(1);
    expect(results.map((r) => r?.refresh)).toEqual(["refresh-2", "refresh-2", "refresh-2"]);
    // A request arriving just after still reuses the result instead of replaying the old token.
    expect((await django.refreshSession(sample()))?.access).toBe("access-2");
    expect(calls).toBe(1);
  });

  it("returns nothing when Django refuses (revoked or reused session)", async () => {
    const { django } = await load();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "INVALID_REFRESH_TOKEN" } }), { status: 401 })));
    expect(await django.refreshSession(sample({ sessionId: "s-2" }))).toBeNull();
  });
});
