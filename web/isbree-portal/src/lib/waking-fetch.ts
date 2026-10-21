/**
 * fetch() towards an API on a free host that sleeps after 15 minutes. While it
 * boots, the host's proxy may answer 502 / 503 / 504 itself, in a few seconds,
 * before the request ever reaches Django: shown as is, that was "service
 * unavailable" after a pause. Those answers (and a refused connection) are
 * retried until the request succeeds or `budgetMs` is spent.
 * For READS only (dal.ts): a POST is never repeated (django.ts postJson).
 */
export const WAKING_STATUSES = new Set([502, 503, 504]);

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function fetchWhileWaking(
  url: string | URL,
  init: RequestInit,
  { budgetMs, pauseMs = 3000 }: { budgetMs: number; pauseMs?: number },
): Promise<Response> {
  const deadline = Date.now() + budgetMs;
  for (;;) {
    const remaining = deadline - Date.now();
    try {
      const response = await fetch(url, { ...init, signal: AbortSignal.timeout(Math.max(remaining, 1)) });
      if (!WAKING_STATUSES.has(response.status) || deadline - Date.now() <= pauseMs) return response;
      await response.body?.cancel();
    } catch (error) {
      // A timeout means the budget is spent; a refused connection is retried like a 502.
      if ((error as Error)?.name === "TimeoutError" || deadline - Date.now() <= pauseMs) throw error;
    }
    await sleep(pauseMs);
  }
}
