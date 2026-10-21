import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const PASSWORD = process.env.E2E_DEMO_PASSWORD || "";
const ACCOUNTS = {
  parent: "parent.demo@isbree.test",
  enseignant: "enseignant.demo@isbree.test",
  personnel: "personnel.demo@isbree.test",
  gardien: "gardien.demo@isbree.test",
};

async function signIn(page: Page, identifier: string, password = PASSWORD) {
  await page.goto("/connexion");
  await page.getByLabel("Identifiant").fill(identifier);
  await page.getByLabel("Mot de passe").fill(password);
  await page.getByRole("button", { name: "Se connecter" }).click();
}

async function axe(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(result.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

test.describe("without a session", () => {
  test("every private page leads to the login page, never indexed nor cached", async ({ page, request }) => {
    for (const path of ["/", "/espace/parent", "/pages/a-propos?role=PARENT"]) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/connexion$/);
    }
    const response = await request.get("/connexion");
    expect(response.headers()["x-robots-tag"]).toBe("noindex, nofollow");
    expect(response.headers()["cache-control"]).toContain("no-store");
    await page.goto("/connexion");
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
    await axe(page);
  });

  test("a wrong password gets the same neutral refusal", async ({ page }) => {
    await signIn(page, "personne@inconnu.test", "Mauvais-Mot-De-Passe-1");
    await expect(page.getByRole("alert").filter({ hasText: "incorrect" })).toContainText(
      "Identifiant ou mot de passe incorrect.",
    );
  });

  test("an invalid activation link is explained, and the code leaves the address bar", async ({ page }) => {
    await page.goto("/activation#code=CODE-INVENTE-0000");
    await expect(page.getByRole("alert").filter({ hasText: "pas valable" })).toBeVisible();
    expect(new URL(page.url()).hash).toBe("");
    await axe(page);
  });

  test("files cannot be fetched without a session", async ({ request }) => {
    const response = await request.get("/applications/00000000-0000-0000-0000-000000000000/telecharger", { maxRedirects: 0 });
    expect([302, 303, 307]).toContain(response.status());
  });
});

test.describe("role spaces (demo accounts)", () => {
  test.skip(!PASSWORD, "E2E_DEMO_PASSWORD (or .env.isbree.local) is required");

  test("the API readiness is checked first, then the credentials are sent once", async ({ page }) => {
    const calls: string[] = [];
    page.on("request", (r) => {
      const path = new URL(r.url()).pathname;
      if (path === "/connexion/disponibilite") calls.push("ready-check");
      else if (r.method() === "POST" && path === "/connexion") calls.push("login");
    });
    await signIn(page, ACCOUNTS.parent);
    await expect(page).toHaveURL(/\/espace\/parent$/);
    expect(calls.filter((c) => c === "login")).toHaveLength(1);
    expect(calls.indexOf("ready-check")).toBeLessThan(calls.indexOf("login"));
  });

  test("a parent sees a verified child and only the parent space", async ({ page, context }) => {
    await signIn(page, ACCOUNTS.parent);
    await expect(page).toHaveURL(/\/espace\/parent$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Bonjour");
    await expect(page.getByRole("navigation", { name: "Choix de l'enfant" })).toContainText("Léa Mballa");
    await expect(page.getByRole("heading", { name: /Ressources — Léa/ })).toBeVisible();
    await axe(page);

    // The session cookie is HttpOnly: page scripts cannot read it, nothing in localStorage.
    const cookie = (await context.cookies()).find((c) => c.name === "isbree_portal_session");
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.sameSite).toBe("Lax");
    expect(await page.evaluate(() => document.cookie)).not.toContain("isbree_portal_session");
    expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);

    // A role not held: the URL grants nothing.
    await page.goto("/espace/enseignant");
    await expect(page.getByRole("heading", { name: "Espace non accessible" })).toBeVisible();

    // An unknown child id falls back to the parent's own child.
    await page.goto("/espace/parent?enfant=00000000-0000-0000-0000-000000000000");
    await expect(page.getByRole("link", { name: /Léa Mballa/ })).toHaveAttribute("aria-current", "page");

    await page.getByRole("button", { name: "Se déconnecter" }).click();
    await expect(page).toHaveURL(/\/connexion\?deconnexion=1$/);
    await page.goto("/espace/parent");
    await expect(page).toHaveURL(/\/connexion$/);
  });

  for (const [slug, title] of [
    ["enseignant", "Espace Enseignant"],
    ["personnel", "Espace Personnel"],
    ["gardien", "Espace Gardien"],
  ] as const) {
    test(`${title}`, async ({ page }) => {
      await signIn(page, ACCOUNTS[slug]);
      await expect(page).toHaveURL(new RegExp(`/espace/${slug}$`));
      await expect(page.getByText(title, { exact: true }).first()).toBeVisible();
      await expect(page.getByRole("heading", { name: "Ressources" })).toBeVisible();
      // Applications: a download button only for a published release, otherwise an honest notice.
      const app = page.locator("#applications").locator("..");
      const official = await app.getByRole("link", { name: /Télécharger pour Android/ }).count();
      const demo = app.getByRole("link", { name: "Télécharger l'APK (version de test)" });
      if ((await demo.count()) > 0) {
        // A demonstration build: only this project's GitHub Release, and labelled as such.
        await expect(demo.first()).toHaveAttribute(
          "href",
          /^https:\/\/github\.com\/NG-offischield\/school-managing\/releases\/download\/[^/]+\/isbree-demo-[a-z]+-arm64-v8a-debug\.apk$/,
        );
        await expect(app).toContainText("signé avec une clé de débogage");
      } else if (official === 0) {
        await expect(app).toContainText("pas encore disponible");
      }
      await axe(page);
      await page.getByRole("button", { name: "Se déconnecter" }).click();
      await expect(page).toHaveURL(/\/connexion/);
    });
  }
});

// The family journey: an invitation issued by an administrator for an ACCEPTED
// pre-enrollment (desktop "Site ISBREE" module or admin API) is activated, then used.
// Single use: run with E2E_INVITE_LINK=<fresh link> and E2E_INVITE_LOGIN=<family e-mail>.
test("a family activates its invitation and sees its request, without any child", async ({ page, isMobile }) => {
  const link = process.env.E2E_INVITE_LINK || "";
  test.skip(!link || isMobile, "set E2E_INVITE_LINK to a fresh invitation link");
  const password = `Famille-E2E-${Date.now()}`;
  await page.goto(link.replace(/^https?:\/\/[^/]+/, ""));
  await expect(page.getByRole("heading", { name: /^Bonjour/ })).toBeVisible();
  expect(new URL(page.url()).hash).toBe("");
  await page.getByLabel("Nouveau mot de passe").fill(password);
  await page.getByLabel("Confirmer le mot de passe").fill(password);
  await page.getByRole("button", { name: "Activer mon compte" }).click();
  await expect(page.getByRole("heading", { name: "Votre compte est activé" })).toBeVisible();
  // Single use: the same link is refused now.
  await page.goto(link.replace(/^https?:\/\/[^/]+/, ""));
  await expect(page.getByRole("alert").filter({ hasText: "pas valable" })).toBeVisible();

  await signIn(page, process.env.E2E_INVITE_LOGIN || "", password);
  await expect(page).toHaveURL(/\/espace\/parent$/);
  await expect(page.locator("#preinscriptions").locator("..")).toContainText("Acceptée");
  await expect(page.getByText(/Aucun enfant n'est encore rattaché/)).toBeVisible();
});
