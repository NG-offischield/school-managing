import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ActivationState, FormState } from "@/lib/auth-actions";
import { portalRoles, roleFromSlug, spaceHref } from "@/lib/roles";
import type { Readiness } from "@/lib/wait-for-api";

vi.mock("@/lib/auth-actions", () => ({
  login: vi.fn(),
  logout: vi.fn(),
  checkActivation: vi.fn(),
  completeActivation: vi.fn(),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const { LoginForm } = await import("@/app/connexion/login-form");
const { ActivationForm, readCodeFromHash } = await import("@/app/activation/activation-form");
const { Apps } = await import("@/components/sections");

describe("roles", () => {
  it("keeps only the portal roles really held, under their French names", () => {
    expect(portalRoles(["ADMIN", "GUARDIAN", "TEACHER"])).toEqual(["TEACHER", "GUARDIAN"]);
    expect(roleFromSlug("gardien")).toBe("GUARDIAN");
    expect(roleFromSlug("admin")).toBeNull();
    expect(spaceHref("STAFF")).toBe("/espace/personnel");
  });
});

describe("login form", () => {
  const ready = vi.fn(async (): Promise<Readiness> => "ready");

  async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, button = "Se connecter") {
    await user.type(screen.getByLabelText("Identifiant"), "parent.demo@isbree.test");
    await user.type(screen.getByLabelText("Mot de passe"), "un-mot-de-passe");
    await user.click(screen.getByRole("button", { name: button }));
  }

  it("API ready at once: the credentials are sent once", async () => {
    const action = vi.fn(async (): Promise<FormState> => ({}));
    const user = userEvent.setup();
    render(<LoginForm action={action} wait={ready} />);
    await fillAndSubmit(user);
    await vi.waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const sent = (action.mock.calls[0] as unknown as [unknown, FormData])[1];
    expect(sent.get("identifier")).toBe("parent.demo@isbree.test");
  });

  it("API waking up: a clear waiting state, then ONE automatic sign-in, without clicking again", async () => {
    let wake!: () => void;
    const wait = vi.fn(
      ({ onWaiting }: { onWaiting?: () => void } = {}) =>
        new Promise<Readiness>((resolve) => {
          onWaiting?.();
          wake = () => resolve("ready");
        }),
    );
    const action = vi.fn(async (): Promise<FormState> => ({}));
    const user = userEvent.setup();
    render(<LoginForm action={action} wait={wait} />);
    await fillAndSubmit(user);
    expect(await screen.findByText(/Le premier démarrage peut prendre un moment/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connexion…" })).toBeDisabled(); // no concurrent attempt
    expect(action).not.toHaveBeenCalled(); // no credentials sent while the API sleeps
    wake();
    await vi.waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    expect(wait).toHaveBeenCalledTimes(1);
  });

  it("API still down after the delay: says so, keeps the fields, offers to retry, sends nothing", async () => {
    const action = vi.fn(async (): Promise<FormState> => ({}));
    const user = userEvent.setup();
    render(<LoginForm action={action} wait={async () => "timeout"} />);
    await fillAndSubmit(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("Le serveur ne répond pas actuellement");
    expect(screen.getByLabelText("Identifiant")).toHaveValue("parent.demo@isbree.test");
    expect(screen.getByLabelText("Mot de passe")).toHaveValue("un-mot-de-passe");
    expect(screen.getByRole("button", { name: "Réessayer" })).toBeEnabled();
    expect(action).not.toHaveBeenCalled();
  });

  it("a server error after waking is reported as such, not as a start-up", async () => {
    const action = vi.fn(async (): Promise<FormState> => ({ error: "Le service est momentanément indisponible. Réessayez dans quelques instants." }));
    const user = userEvent.setup();
    render(<LoginForm action={action} wait={ready} />);
    await fillAndSubmit(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("momentanément indisponible");
    expect(screen.queryByText(/premier démarrage/)).not.toBeInTheDocument();
  });

  it("shows Django's refusal without hinting whether the account exists", async () => {
    const action = vi.fn(async (): Promise<FormState> => ({ identifier: "x@y.test", error: "Identifiant ou mot de passe incorrect." }));
    const user = userEvent.setup();
    render(<LoginForm action={action} wait={ready} />);
    await user.type(screen.getByLabelText("Identifiant"), "x@y.test");
    await user.type(screen.getByLabelText("Mot de passe"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Identifiant ou mot de passe incorrect.");
    expect(screen.getByLabelText("Identifiant")).toHaveValue("x@y.test");
    expect(screen.getByLabelText("Mot de passe")).toHaveAttribute("autocomplete", "current-password");
  });
});

describe("activation", () => {
  it("reads the code from the URL fragment only", () => {
    expect(readCodeFromHash("#code=AbC-123")).toBe("AbC-123");
    expect(readCodeFromHash("#x=1&code=Z9")).toBe("Z9");
    expect(readCodeFromHash("")).toBe("");
  });

  it("checks the link, removes it from the address bar, then sets the password", async () => {
    window.history.replaceState(null, "", "/activation#code=CODE-42");
    const check = vi.fn(
      async (): Promise<ActivationState> => ({ step: "password", code: "CODE-42", firstName: "Mireille", login: "m@f.test", expiresAt: "" }),
    );
    const complete = vi.fn(async (): Promise<ActivationState> => ({ step: "done", login: "m@f.test" }));
    const user = userEvent.setup();
    render(<ActivationForm actions={{ check, complete }} />);
    expect(await screen.findByRole("heading", { name: "Bonjour Mireille" })).toBeInTheDocument();
    expect((check.mock.calls[0] as unknown as [unknown, FormData])[1].get("code")).toBe("CODE-42");
    expect(window.location.hash).toBe(""); // the code no longer sits in the address bar / history
    await user.type(screen.getByLabelText("Nouveau mot de passe"), "Un-Mot-De-Passe-2026");
    await user.type(screen.getByLabelText("Confirmer le mot de passe"), "Un-Mot-De-Passe-2026");
    await user.click(screen.getByRole("button", { name: "Activer mon compte" }));
    expect(await screen.findByRole("heading", { name: "Votre compte est activé" })).toBeInTheDocument();
  });

  it("explains an invalid or expired link", async () => {
    window.history.replaceState(null, "", "/activation#code=OLD");
    const check = vi.fn(async (): Promise<ActivationState> => ({ step: "code", error: "Ce lien d'activation n'est pas valable." }));
    render(<ActivationForm actions={{ check, complete: vi.fn() }} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("n'est pas valable");
  });
});

describe("mobile applications", () => {
  it("offers a download only for a published file, never a fake link", () => {
    render(
      <Apps
        apps={[
          { app: "PARENT", label: "Application Parent", release: null },
          // An application without any published file (official or demonstration build).
          { app: "LIBRARY" as "PARENT", label: "Application Bibliothèque", release: null },
          {
            app: "TEACHER",
            label: "Application Enseignant",
            release: {
              id: "0670a608-9fda-47e2-8f78-453fc6492e5d",
              app: "TEACHER",
              label: "Application Enseignant",
              package: "cm.schoolmanaging.school_teacher",
              version_name: "1.0.0",
              version_code: 1,
              release_notes: "",
              min_android: "",
              size: 2_000_000,
              sha256: "ab".repeat(32),
              published_at: null,
            },
          },
        ]}
      />,
    );
    const links = screen.getAllByRole("link", { name: /Télécharger/ });
    expect(links).toHaveLength(2);
    // Parent: no official release, the published debug build of the GitHub Release (lib/mobile-apps.json).
    expect(links[0]).toHaveAttribute(
      "href",
      "https://github.com/NG-offischield/school-managing/releases/download/demo-apk-2026-10-17/isbree-demo-parent-arm64-v8a-debug.apk",
    );
    expect(screen.getByText(/signé avec une clé de débogage/)).toHaveTextContent("Le fichier est public");
    // Teacher: an official release served by the portal itself.
    expect(links[1]).toHaveAttribute("href", "/applications/0670a608-9fda-47e2-8f78-453fc6492e5d/telecharger");
    expect(screen.getByText(/pas encore disponible/)).toBeInTheDocument();
    expect(screen.queryByText(/iOS|App Store/)).toBeNull();
  });
});
