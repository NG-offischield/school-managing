import { describe, expect, it, vi } from "vitest";

import { waitForApi } from "@/lib/wait-for-api";

/** Mocked readiness answers (local unit test: this is not a real Render cold start). */
const answers = (...values: boolean[]) => {
  const check = vi.fn(async () => values.shift() ?? false);
  return check;
};

describe("waiting for the API before signing in", () => {
  it("API available at once: one check, ready, no waiting state", async () => {
    const check = answers(true);
    const onWaiting = vi.fn();
    expect(await waitForApi({ check, onWaiting, intervalMs: 1 })).toBe("ready");
    expect(check).toHaveBeenCalledTimes(1);
    expect(onWaiting).not.toHaveBeenCalled();
  });

  it("API asleep then started: waiting state shown once, then ready", async () => {
    const check = answers(false, false, true);
    const onWaiting = vi.fn();
    expect(await waitForApi({ check, onWaiting, intervalMs: 1, budgetMs: 5000 })).toBe("ready");
    expect(check).toHaveBeenCalledTimes(3);
    expect(onWaiting).toHaveBeenCalledTimes(1);
  });

  it("API still unavailable: stops after the delay (timeout), at a reasonable pace", async () => {
    const check = answers();
    expect(await waitForApi({ check, intervalMs: 20, budgetMs: 100 })).toBe("timeout");
    expect(check.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(check.mock.calls.length).toBeLessThanOrEqual(6);
  });

  it("stops when the form is left (aborted)", async () => {
    const controller = new AbortController();
    const check = vi.fn(async () => {
      controller.abort();
      return false;
    });
    expect(await waitForApi({ check, signal: controller.signal, intervalMs: 1 })).toBe("aborted");
  });
});
