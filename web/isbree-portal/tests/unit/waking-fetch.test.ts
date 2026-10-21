import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchWhileWaking } from "@/lib/waking-fetch";

const answer = (status: number) => new Response("{}", { status });

describe("calls to an API that is waking up (free host)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("retries the host's own 502 / 503 / 504 until the API answers", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(answer(502)).mockResolvedValueOnce(answer(503)).mockResolvedValue(answer(200));
    vi.stubGlobal("fetch", fetchMock);
    const response = await fetchWhileWaking("https://api.test/x/", { method: "POST" }, { budgetMs: 5000, pauseMs: 1 });
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("retries a refused connection, but returns the API's own answers at once", async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError("fetch failed")).mockResolvedValue(answer(401));
    vi.stubGlobal("fetch", fetchMock);
    const response = await fetchWhileWaking("https://api.test/x/", {}, { budgetMs: 5000, pauseMs: 1 });
    expect(response.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("gives up when the budget is spent: the last answer is returned", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer(502)));
    const response = await fetchWhileWaking("https://api.test/x/", {}, { budgetMs: 50, pauseMs: 20 });
    expect(response.status).toBe(502);
  });
});
