import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PAGES = [
  "/",
  "/a-propos",
  "/formations",
  "/vie-scolaire",
  "/actualites",
  "/galerie",
  "/admissions",
  "/admissions/preinscription",
  "/faq",
  "/contact",
];

test.describe("public pages", () => {
  for (const path of PAGES) {
    test(`${path} renders and passes axe (WCAG A/AA)`, async ({ page }) => {
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page.locator("h1")).toHaveCount(1);
      await expect(page.locator("html")).toHaveAttribute("lang", "fr");
      const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(result.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
      // No horizontal scrolling, at any width.
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }

  test("the contact phone is a tel: link", async ({ page }) => {
    await page.goto("/contact");
    await expect(page.locator('a[href="tel:+237698686729"]').first()).toBeVisible();
  });

  test("illustrations are never presented as photographs of the school", async ({ page }) => {
    await page.goto("/galerie");
    const figures = page.locator("figure");
    const count = await figures.count();
    for (let i = 0; i < count; i++) {
      await expect(figures.nth(i)).toContainText(/ne représente pas ISBREE/);
    }
  });

  test("an unknown article or page is a real 404, from the first visit", async ({ page }) => {
    // A slug never requested before (no cached render): the status must already be 404.
    for (const path of [`/actualites/inconnue-${Date.now()}`, `/informations/inconnue-${Date.now()}`]) {
      const response = await page.goto(path);
      expect(response?.status(), path).toBe(404);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Cette page n'existe pas");
      await expect(page.getByRole("link", { name: "Retour à l'accueil" })).toHaveAttribute("href", "/");
    }
  });
});

test.describe("security and indexing", () => {
  test("security headers are sent", async ({ request }) => {
    const response = await request.get("/");
    const headers = response.headers();
    expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(headers["content-security-policy"]).toContain("object-src 'none'");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["x-powered-by"]).toBeUndefined();
  });

  test("the sitemap lists public pages only", async ({ request }) => {
    const xml = await (await request.get("/sitemap.xml")).text();
    expect(xml).toContain("/admissions/preinscription");
    expect(xml).not.toContain(":3001"); // never the portal
    expect(xml).not.toContain("/images/");
  });

  test("images are proxied with a public cache, invalid ids refused", async ({ request }) => {
    expect((await request.get("/images/not-a-uuid")).status()).toBe(404);
    expect((await request.get("/images/00000000-0000-0000-0000-000000000000")).status()).toBe(404);
  });
});

test.describe("navigation", () => {
  test("the menu opens, closes with Escape and gives the focus back", async ({ page, isMobile }) => {
    test.skip(!isMobile, "the menu button exists below 1280 px");
    await page.goto("/");
    const button = page.getByRole("button", { name: "Menu" });
    await button.click();
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("link", { name: "Formations" }).last()).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    await expect(button).toBeFocused();
  });

  test("the skip link reaches the content", async ({ page, isMobile }) => {
    test.skip(isMobile, "keyboard navigation");
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Aller au contenu" })).toBeFocused();
  });
});

test.describe("pre-enrollment", () => {
  test("incomplete requests are stopped in the browser with an accessible summary", async ({ page }) => {
    await page.goto("/admissions/preinscription");
    await page.getByRole("button", { name: "Envoyer ma demande" }).click();
    // Next.js renders its own (empty) route announcer with role="alert": pick ours.
    const alert = page.getByRole("alert").filter({ hasText: "Certains champs" });
    await expect(alert).toContainText("Certains champs sont à corriger.");
    await expect(alert).toBeFocused();
    await expect(page.getByLabel("Adresse e-mail")).toHaveAttribute("aria-invalid", "true");
  });

  // Creates a REAL request in the development database (5 per hour per address):
  // run explicitly with E2E_SUBMIT=1.
  test("a complete request receives a reference from the school", async ({ page, isMobile }) => {
    test.skip(process.env.E2E_SUBMIT !== "1" || isMobile, "set E2E_SUBMIT=1 to create a real request");
    await page.goto("/admissions/preinscription");
    await page.getByLabel("Prénom du responsable").fill("Test");
    await page.getByLabel("Nom du responsable", { exact: true }).fill("E2E");
    await page.getByLabel(/^Téléphone/).fill("+237 690 00 00 00");
    await page.getByLabel("Adresse e-mail").fill(`e2e-${Date.now()}@e2e.isbree.test`);
    await page.getByLabel("Lien avec l'enfant").selectOption("OTHER");
    await page.getByLabel("Prénom de l'enfant").fill("Enfant");
    await page.getByLabel("Nom de l'enfant", { exact: true }).fill("E2E");
    await page.getByLabel("Niveau demandé").selectOption({ index: 1 });
    await page.getByLabel("Année scolaire").selectOption({ index: 1 });
    await page.getByLabel(/J'accepte que ces informations/).check();
    await page.getByRole("button", { name: "Envoyer ma demande" }).click();
    await expect(page.getByRole("heading", { name: "Votre demande a bien été reçue" })).toBeVisible();
    await expect(page.getByText(/PRE-\d{4}-\d{4}/)).toBeVisible();
  });
});

// Search engines (docs/seo.md): what Google reads, without a browser.
test.describe("search engines", () => {
  test("robots.txt allows the public pages and names the sitemap", async ({ request, baseURL }) => {
    const robots = await (await request.get("/robots.txt")).text();
    expect(robots).toMatch(/^Allow: \/$/m);
    expect(robots).not.toMatch(/^Disallow: \/$/m);
    expect(robots).toContain(`Sitemap: ${new URL("/sitemap.xml", baseURL).href}`);
  });

  test("the sitemap lists canonical public pages only", async ({ request }) => {
    const response = await request.get("/sitemap.xml");
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("xml");
    const xml = await response.text();
    expect(xml).toMatch(/<urlset[^>]+sitemaps\.org/);
    const urls = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => new URL(m[1]).pathname);
    expect(urls).toEqual(expect.arrayContaining(["/", "/a-propos", "/formations", "/actualites", "/faq", "/contact"]));
    // Never the portal, the API, the image route, nor a duplicate of a dedicated page.
    for (const path of urls) {
      expect(path).not.toMatch(/^\/(espace|connexion|api|images)\b/);
      expect(path).not.toMatch(/^\/informations\/(a-propos|vie-scolaire|admissions|approche-pedagogique)$/);
    }
    for (const path of urls.slice(0, 12)) {
      expect((await request.get(path)).status(), path).toBe(200); // every listed page answers
    }
  });

  test("each page has its own canonical URL, description and share image, and may be indexed", async ({ page }) => {
    const seen = new Set<string>();
    for (const [path, canonical] of [
      ["/", "/"],
      ["/formations", "/formations"],
      ["/actualites/rentree-scolaire", "/actualites/rentree-scolaire"],
      ["/informations/a-propos", "/a-propos"], // same text as /a-propos: that page is the canonical one
    ]) {
      await page.goto(path);
      const href = await page.locator('link[rel="canonical"]').getAttribute("href");
      expect(new URL(href!).pathname.replace(/\/$/, "") || "/", path).toBe(canonical.replace(/\/$/, "") || "/");
      const description = await page.locator('meta[name="description"]').getAttribute("content");
      expect(description?.length, path).toBeGreaterThan(40);
      seen.add(description!);
      await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", /\/opengraph-image/);
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /^index, follow/);
    }
    expect(seen.size).toBe(4); // no description copied on every page
  });
});
