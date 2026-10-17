import type { Metadata, Viewport } from "next";
import { Fraunces, Source_Sans_3 } from "next/font/google";

import { config } from "@/lib/config";

import "./globals.css";

const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"], display: "swap" });
const sourceSans = Source_Sans_3({ variable: "--font-source", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: { default: "Espace ISBREE", template: "%s · Espace ISBREE" },
  description: "Espace personnel des familles et des équipes d'ISBREE.",
  // A private space: never indexed (also sent as an X-Robots-Tag header).
  robots: { index: false, follow: false, nocache: true },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = { themeColor: "#10294a", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="fr" className={`${fraunces.variable} ${sourceSans.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <a
          href="#contenu"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-full focus:bg-ink focus:px-5 focus:py-3 focus:text-paper"
        >
          Aller au contenu
        </a>
        {config.demoMode ? (
          <div className="border-b border-line bg-sand/70 text-ink" role="note">
            <p className="container-page py-1.5 text-center text-xs">
              Espace de démonstration : les comptes et les éléments marqués « Démo » sont fictifs.
            </p>
          </div>
        ) : null}
        {children}
      </body>
    </html>
  );
}
