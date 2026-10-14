import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SubmitState } from "@/lib/pre-enrollment";

vi.mock("@/app/admissions/preinscription/actions", () => ({ submitPreEnrollment: vi.fn() }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const { PreEnrollmentForm } = await import("@/app/admissions/preinscription/pre-enrollment-form");

const props = {
  levels: [{ id: "0670a608-9fda-47e2-8f78-453fc6492e5d", code: "6E", name: "6e", cycle: "Collège" }],
  years: [{ id: "32628c4a-a5de-4e17-8776-f2f2160f79ea", name: "2026-2027" }],
  relationships: [{ value: "MOTHER", label: "Mère" }],
  privacyHref: "/informations/confidentialite",
};

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Prénom du responsable"), "Mireille");
  await user.type(screen.getByLabelText("Nom du responsable"), "Atangana");
  await user.type(screen.getByLabelText(/^Téléphone/), "+237 690 00 00 00");
  await user.type(screen.getByLabelText("Adresse e-mail"), "mireille@famille.test");
  await user.selectOptions(screen.getByLabelText("Lien avec l'enfant"), "MOTHER");
  await user.type(screen.getByLabelText("Prénom de l'enfant"), "Paul");
  await user.type(screen.getByLabelText("Nom de l'enfant"), "Atangana");
  await user.selectOptions(screen.getByLabelText("Niveau demandé"), props.levels[0].id);
  await user.selectOptions(screen.getByLabelText("Année scolaire"), props.years[0].id);
}

describe("pre-enrollment form", () => {
  it("blocks an incomplete request in the browser and lists the errors", async () => {
    const action = vi.fn(async (): Promise<SubmitState> => ({ status: "idle" }));
    const user = userEvent.setup();
    render(<PreEnrollmentForm {...props} action={action} />);
    await user.click(screen.getByRole("button", { name: "Envoyer ma demande" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Certains champs sont à corriger.");
    expect(screen.getByLabelText("Prénom du responsable")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("link", { name: /Indiquez une adresse e-mail valide/ })).toHaveAttribute("href", "#guardian_email");
    expect(action).not.toHaveBeenCalled();
  });

  it("sends a valid request and shows the reference given by the school", async () => {
    const action = vi.fn(async (): Promise<SubmitState> => ({ status: "received", reference: "PRE-2026-0001" }));
    const user = userEvent.setup();
    render(<PreEnrollmentForm {...props} action={action} />);
    await fill(user);
    await user.click(screen.getByLabelText(/J'accepte que ces informations/));
    await user.click(screen.getByRole("button", { name: "Envoyer ma demande" }));
    expect(await screen.findByRole("heading", { name: "Votre demande a bien été reçue" })).toBeInTheDocument();
    expect(screen.getByText("PRE-2026-0001")).toBeInTheDocument();
    expect(screen.getByText(/Aucun e-mail automatique/)).toBeInTheDocument(); // no false promise of an e-mail
    const sent = action.mock.calls[0] as unknown as [SubmitState, FormData];
    expect(sent[1].get("guardian_email")).toBe("mireille@famille.test");
    expect(sent[1].get("website")).toBe(""); // the honeypot stays empty for people
  });

  it("shows the server's refusal and keeps what the family typed", async () => {
    const action = vi.fn(
      async (): Promise<SubmitState> => ({
        status: "error",
        values: { guardian_first_name: "Mireille" },
        message: "Trop de demandes ont été envoyées depuis votre connexion. Réessayez dans une heure.",
      }),
    );
    const user = userEvent.setup();
    render(<PreEnrollmentForm {...props} action={action} />);
    await fill(user);
    await user.click(screen.getByLabelText(/J'accepte que ces informations/));
    await user.click(screen.getByRole("button", { name: "Envoyer ma demande" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Trop de demandes");
    expect(screen.getByLabelText("Prénom du responsable")).toHaveValue("Mireille");
  });

  it("hides the honeypot from people and assistive technologies", () => {
    render(<PreEnrollmentForm {...props} action={vi.fn()} />);
    const trap = document.querySelector("input[name=website]") as HTMLInputElement;
    expect(trap).toHaveAttribute("tabindex", "-1");
    expect(trap.closest("[aria-hidden=true]")).not.toBeNull();
  });
});
