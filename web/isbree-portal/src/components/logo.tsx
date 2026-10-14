/**
 * PROVISIONAL ISBREE monogram, designed for this first version of the site
 * (not an official emblem: to be replaced by the school's own logo).
 *
 * An arch — the school's open door and a shelter — frames a rising sun
 * (ochre: openness, the future) and a young shoot whose stem draws the "I" of
 * ISBREE (green: growth), springing from an open book (ivory: knowledge).
 */
export function LogoMark({ className = "h-11 w-11", title }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      <path d="M6 60V30C6 15.6 17.6 4 32 4s26 11.6 26 26v30z" fill="#10294a" />
      <path d="M11 60V30.5C11 18.9 20.4 9.5 32 9.5S53 18.9 53 30.5V60" fill="none" stroke="#d9a441" strokeWidth="1.6" />
      <circle cx="32" cy="29" r="10" fill="#d9a441" />
      <path d="M32 47V24" stroke="#faf6ee" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M32 33c-1-6.2-5.4-9.6-11.4-9.4.4 6.1 4.8 9.7 11.4 9.4z" fill="#3f8a63" />
      <path d="M32 28.5c1-5.4 4.9-8.4 10.2-8.2-.4 5.4-4.3 8.5-10.2 8.2z" fill="#3f8a63" />
      <path d="M12 49.5c6.8-2.6 13.5-2.4 20 1.3 6.5-3.7 13.2-3.9 20-1.3V56c-6.8-2.6-13.5-2.4-20 1.3-6.5-3.7-13.2-3.9-20-1.3z" fill="#faf6ee" />
      <path d="M32 50.8v6.5" stroke="#10294a" strokeWidth="1.2" />
    </svg>
  );
}

export function Logo({ inverted = false }: { inverted?: boolean }) {
  return (
    <span className="flex items-center gap-3">
      <LogoMark />
      <span className="flex flex-col leading-none">
        <span className={`font-serif text-2xl font-semibold tracking-wide ${inverted ? "text-paper" : "text-ink"}`}>
          ISBREE
        </span>
        <span className={`mt-1 whitespace-nowrap text-[0.7rem] font-semibold uppercase tracking-[0.18em] ${inverted ? "text-sand" : "text-muted"}`}>
          Yaoundé · Etoug-Ebe
        </span>
      </span>
    </span>
  );
}
