import catalogue from "./mobile-apps.json";

/**
 * Demonstration builds of the four Android apps, published as assets of a
 * GitHub Release of the project (free, durable, outside the Git history).
 *
 * Honest by construction:
 * - an entry exists only once its APK was built, launched on an emulator and
 *   uploaded (mobile-apps.json is written from the real files: size, SHA-256);
 * - these are DEBUG builds signed with the Android debug key: installable for a
 *   demonstration, not official releases (the API keeps refusing debug-signed
 *   APKs for its own "official release" downloads);
 * - GitHub Release assets are PUBLIC: the portal only shows each person the
 *   app of their role, it never claims the file is confidential.
 */
export type DemoApk = {
  app: string;
  label: string;
  purpose: string;
  package: string;
  versionName: string;
  fileName: string;
  size: number;
  sha256: string;
  url: string;
};

type Catalogue = { release: string; repository: string; builtOn: string; apps: Omit<DemoApk, "url">[] };

const data = catalogue as Catalogue;

export function demoApk(app: string): DemoApk | null {
  const entry = data.apps.find((a) => a.app === app);
  if (!entry || !data.release) return null;
  return {
    ...entry,
    url: `https://github.com/${data.repository}/releases/download/${data.release}/${entry.fileName}`,
  };
}

export const demoBuildDate = data.builtOn;
