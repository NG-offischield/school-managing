import { describe, expect, it } from "vitest";

import { clientIp } from "@/lib/client-ip";
import { formatPhone, telHref } from "@/lib/format";
import { parseMarkup } from "@/lib/markup";
import { plausibleBirthDate, validate } from "@/lib/pre-enrollment";

const LEVEL = "0670a608-9fda-47e2-8f78-453fc6492e5d";
const YEAR = "32628c4a-a5de-4e17-8776-f2f2160f79ea";

const valid = {
  guardian_first_name: "Mireille",
  guardian_last_name: "Atangana",
  guardian_phone: "+237 690 00 00 00",
  guardian_email: "mireille@famille.test",
  relationship: "MOTHER",
  child_first_name: "Paul",
  child_last_name: "Atangana",
  child_birth_date: "",
  requested_level: LEVEL,
  requested_year: YEAR,
  previous_school: "",
  comment: "",
};

describe("page markup", () => {
  it("reads headings, lists and paragraphs, never HTML", () => {
    const blocks = parseMarkup("## Titre\nUn paragraphe\nsur deux lignes.\n\n- un\n- deux\n\n<script>alert(1)</script>");
    expect(blocks).toEqual([
      { type: "heading", text: "Titre" },
      { type: "paragraph", text: "Un paragraphe sur deux lignes." },
      { type: "list", items: ["un", "deux"] },
      { type: "paragraph", text: "<script>alert(1)</script>" }, // plain text, escaped by React
    ]);
  });
});

describe("pre-enrollment validation (same rules as Django)", () => {
  it("accepts a complete request", () => {
    expect(validate(valid, true).ok).toBe(true);
  });

  it("names every invalid field", () => {
    const result = validate(
      { ...valid, guardian_email: "pas-un-email", guardian_phone: "<script>", comment: "x".repeat(1001), requested_level: "" },
      false,
    );
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(Object.keys(result.errors).sort()).toEqual(
        ["comment", "consent", "guardian_email", "guardian_phone", "requested_level"].sort(),
      );
    }
  });

  it("refuses implausible birth dates", () => {
    const today = new Date("2026-10-14T12:00:00Z");
    expect(plausibleBirthDate("", today)).toBe(true);
    expect(plausibleBirthDate("2015-03-02", today)).toBe(true);
    expect(plausibleBirthDate("1950-01-01", today)).toBe(false);
    expect(plausibleBirthDate("2030-01-01", today)).toBe(false);
    expect(plausibleBirthDate("02/03/2015", today)).toBe(false);
  });
});

describe("client address forwarded to Django", () => {
  it("trusts only the entry added by our own proxy", () => {
    expect(clientIp("203.0.113.9", 1)).toBe("203.0.113.9");
    // A visitor-supplied value on the left is ignored with one trusted hop.
    expect(clientIp("1.2.3.4, 198.51.100.7", 1)).toBe("198.51.100.7");
    expect(clientIp("1.2.3.4, 198.51.100.7, 10.0.0.2", 2)).toBe("198.51.100.7");
    expect(clientIp("::ffff:127.0.0.1", 1)).toBe("127.0.0.1");
    expect(clientIp("not-an-ip", 1)).toBe("");
    expect(clientIp(null, 1)).toBe("");
  });
});

describe("phone formatting", () => {
  it("formats Cameroon numbers and builds tel: links", () => {
    expect(formatPhone("+237698686729")).toBe("+237 698 686 729");
    expect(telHref("+237 698 686 729")).toBe("tel:+237698686729");
  });
});
