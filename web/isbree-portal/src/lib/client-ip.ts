/**
 * The visitor's address, forwarded to Django (X-ISBREE-Client-IP) so its
 * per-visitor rate limits work behind this web server.
 *
 * X-Forwarded-For is a list "client, proxy1, proxy2": only the entries added
 * by OUR infrastructure can be trusted, i.e. the rightmost ones.
 * ISBREE_TRUSTED_PROXY_HOPS = number of reverse proxies in front of Next
 * (default 1: the address added by the closest proxy, or by Next itself when
 * there is none). In production Next must sit behind a reverse proxy that
 * appends the real address (docs/isbree-web.md): a visitor reaching Next
 * directly could otherwise choose the value.
 */
const IPV4 = /^(\d{1,3})(\.\d{1,3}){3}$/;
const IPV6 = /^[0-9a-f:]+$/i;

export function clientIp(forwardedFor: string | null, hops = Number(process.env.ISBREE_TRUSTED_PROXY_HOPS || 1)) {
  const entries = (forwardedFor || "")
    .split(",")
    .map((e) => e.trim())
    .filter(Boolean);
  if (!entries.length) return "";
  const index = Math.max(0, entries.length - Math.max(1, Math.floor(hops) || 1));
  const candidate = entries[index].replace(/^::ffff:/i, "");
  return IPV4.test(candidate) || (candidate.includes(":") && IPV6.test(candidate)) ? candidate : "";
}
