/**
 * Waits until the API can take a sign-in (free host waking up), WITHOUT
 * sending the credentials: only the anonymous readiness check
 * (/connexion/disponibilite) is repeated. The login form sends the
 * credentials once, after this returns "ready".
 */
export type Readiness = "ready" | "timeout" | "aborted";

export const WAKE_BUDGET_MS = 100_000; // a cold start of the free API takes about a minute
export const WAKE_INTERVAL_MS = 3_000;

export async function checkApiReady(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch("/connexion/disponibilite", { cache: "no-store", signal });
    return response.ok;
  } catch {
    return false;
  }
}

export async function waitForApi({
  check = checkApiReady,
  budgetMs = WAKE_BUDGET_MS,
  intervalMs = WAKE_INTERVAL_MS,
  signal,
  onWaiting,
}: {
  check?: (signal?: AbortSignal) => Promise<boolean>;
  budgetMs?: number;
  intervalMs?: number;
  signal?: AbortSignal;
  /** Called once, when the first check says the API is not ready (it is waking up). */
  onWaiting?: () => void;
} = {}): Promise<Readiness> {
  const deadline = Date.now() + budgetMs;
  let first = true;
  for (;;) {
    if (signal?.aborted) return "aborted";
    if (await check(signal)) return "ready";
    if (signal?.aborted) return "aborted";
    if (first) onWaiting?.();
    first = false;
    if (Date.now() + intervalMs > deadline) return "timeout";
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
