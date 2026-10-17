import { after } from "next/server";

import { config } from "./config";

/**
 * On a free host the API sleeps after 15 minutes without traffic and needs up
 * to about a minute to wake up. Pages where someone is about to sign in call
 * this: once the page is sent, the health endpoint is requested in the
 * background, so the API is usually awake by the time the form is submitted.
 * Read-only, anonymous, no data sent.
 */
export function wakeApiInBackground() {
  after(async () => {
    try {
      await fetch(`${config.apiUrl}/health/`, { cache: "no-store", signal: AbortSignal.timeout(75000) });
    } catch {
      // nothing to do: the sign-in itself will report an unavailable service
    }
  });
}
