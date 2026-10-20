import { ImageResponse } from "next/og";

import { config } from "@/lib/config";

/** Share image of every page (social networks, messaging): built at build time, no external asset. */
export const alt = "ISBREE — Etoug-Ebe, Yaoundé";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          background: "#10294a",
          color: "#faf6ee",
          fontFamily: "serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
          <svg viewBox="0 0 64 64" width="120" height="120">
            <path d="M6 60V30C6 15.6 17.6 4 32 4s26 11.6 26 26v30z" fill="#faf6ee" />
            <circle cx="32" cy="29" r="10" fill="#d9a441" />
            <path d="M32 47V24" stroke="#10294a" strokeWidth="3.2" strokeLinecap="round" />
            <path d="M32 33c-1-6.2-5.4-9.6-11.4-9.4.4 6.1 4.8 9.7 11.4 9.4z" fill="#3f8a63" />
            <path d="M32 28.5c1-5.4 4.9-8.4 10.2-8.2-.4 5.4-4.3 8.5-10.2 8.2z" fill="#3f8a63" />
            <path
              d="M12 49.5c6.8-2.6 13.5-2.4 20 1.3 6.5-3.7 13.2-3.9 20-1.3V56c-6.8-2.6-13.5-2.4-20 1.3-6.5-3.7-13.2-3.9-20-1.3z"
              fill="#2c6a4c"
            />
          </svg>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 84, fontWeight: 700, letterSpacing: 2 }}>ISBREE</div>
            <div style={{ fontSize: 30, color: "#d9a441", letterSpacing: 6 }}>YAOUNDÉ · ETOUG-EBE</div>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ fontSize: 58, lineHeight: 1.15 }}>Apprendre, grandir et s&apos;ouvrir au monde</div>
          <div style={{ fontSize: 30, color: "#e9dfc9" }}>
            {config.demoMode
              ? "Démonstration de la plateforme de gestion scolaire · données fictives"
              : "Formations, vie scolaire, actualités et préinscription en ligne"}
          </div>
        </div>
      </div>
    ),
    size,
  );
}
