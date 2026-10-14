"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { NAVIGATION } from "./navigation";

function isCurrent(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Main navigation: a link bar on large screens, a disclosure menu on small ones. */
export function MainNav({ portalUrl }: { portalUrl: string }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Close the menu after a navigation.
  const [lastPath, setLastPath] = useState(pathname);
  if (lastPath !== pathname) {
    setLastPath(pathname);
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <nav aria-label="Navigation principale" className="flex items-center gap-2">
      <ul className="hidden items-center gap-0.5 xl:flex">
        {NAVIGATION.map((item) => {
          const current = isCurrent(pathname, item.href);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={current ? "page" : undefined}
                className={`whitespace-nowrap rounded-full px-3 py-2 text-[0.95rem] font-semibold transition-colors hover:bg-sand ${
                  current ? "bg-sand text-ink" : "text-ink-soft"
                }`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
      <a href={portalUrl} className="btn btn-primary hidden !min-h-10 !py-2 text-sm whitespace-nowrap sm:inline-flex">
        Espace ISBREE
      </a>
      <button
        ref={buttonRef}
        type="button"
        className="btn btn-secondary !min-h-11 !px-4 xl:hidden"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true" className="text-lg leading-none">
          {open ? "✕" : "☰"}
        </span>
        Menu
      </button>
      <div
        id={menuId}
        hidden={!open}
        className="absolute inset-x-0 top-full z-40 border-b border-line bg-paper shadow-lg xl:hidden"
      >
        <ul className="container-page grid gap-1 py-4 sm:grid-cols-2">
          {NAVIGATION.map((item) => {
            const current = isCurrent(pathname, item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={current ? "page" : undefined}
                  className={`flex min-h-12 items-center rounded-xl px-4 font-semibold hover:bg-sand ${current ? "bg-sand" : ""}`}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
          <li className="sm:col-span-2">
            <a href={portalUrl} className="btn btn-primary mt-2 w-full">
              Espace ISBREE
            </a>
          </li>
        </ul>
      </div>
    </nav>
  );
}
