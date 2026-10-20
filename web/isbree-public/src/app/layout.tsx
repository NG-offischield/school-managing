import type { Metadata, Viewport } from "next";
import { Fraunces, Source_Sans_3 } from "next/font/google";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { config } from "@/lib/config";

import "./globals.css";

const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"], display: "swap" });
const sourceSans = Source_Sans_3({ variable: "--font-source", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(config.publicUrl),
  title: { default: "ISBREE — Établissement scolaire à Yaoundé", template: "%s · ISBREE" },
  description:
    "ISBREE, établissement scolaire à Etoug-Ebe, Yaoundé : présentation, formations, vie scolaire, actualités et préinscription en ligne.",
  applicationName: "ISBREE",
  openGraph: { type: "website", locale: "fr_CM", siteName: "ISBREE" },
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
        <SiteHeader />
        <main id="contenu" tabIndex={-1} className="flex-1 focus:outline-none">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
