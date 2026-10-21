import { config } from "@/lib/config";

/**
 * Is the API ready to answer a sign-in? Asked by the login form before it
 * sends the credentials (login-form.tsx): on a free host the API sleeps after
 * 15 minutes and needs about a minute to start. One short check of Django's
 * liveness endpoint (/health/: the database answers) per call; the form
 * repeats the call every few seconds. Public, anonymous, no data, never cached.
 */
export const dynamic = "force-dynamic";

export async function GET() {
  let ready = false;
  try {
    const response = await fetch(`${config.apiUrl}/health/`, { cache: "no-store", signal: AbortSignal.timeout(10000) });
    ready = response.ok;
    await response.body?.cancel();
  } catch {
    // asleep, starting or unreachable: not ready yet
  }
  return Response.json({ ready }, { status: ready ? 200 : 503, headers: { "Cache-Control": "no-store" } });
}
