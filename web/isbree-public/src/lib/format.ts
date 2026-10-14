const dateFormat = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "Africa/Douala",
});

export function formatDate(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value.length === 10 ? `${value}T12:00:00Z` : value);
  return Number.isNaN(date.getTime()) ? "" : dateFormat.format(date);
}

/** "+237698686729" -> "+237 698 686 729"; any other number is left unchanged. */
export function formatPhone(phone: string) {
  const match = phone.replace(/[^0-9+]/g, "").match(/^\+237(\d{3})(\d{3})(\d{3})$/);
  return match ? `+237 ${match[1]} ${match[2]} ${match[3]}` : phone;
}

export function telHref(phone: string) {
  return `tel:${phone.replace(/[^0-9+]/g, "")}`;
}
