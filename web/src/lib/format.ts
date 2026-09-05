// Small display-formatting helpers shared by the panels. Kept separate from derive.ts (which
// computes numbers) so this file only ever turns a value into a string — no domain logic.

/** `hab-expected` / `character` / enum-ish kebab strings into a readable label: 'scouted-go' -> 'Scouted Go'. */
export function titleCase(value: string): string {
  return value
    .replace(/[-_]+/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((word) => word[0]!.toUpperCase() + word.slice(1))
    .join(' ');
}

const DASH = '—'; // em dash, used consistently for "no value" across panels

export function formatKm(value: number | undefined, decimals = 1): string {
  if (value === undefined || !Number.isFinite(value)) return DASH;
  return `${value.toFixed(decimals)} km`;
}

export function formatM(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) return DASH;
  return `${Math.round(value)} m`;
}

export function formatPct(value: number | undefined, decimals = 0): string {
  if (value === undefined || !Number.isFinite(value)) return DASH;
  return `${value.toFixed(decimals)}%`;
}

export function formatList(values: readonly string[] | undefined): string {
  return values && values.length ? values.join(', ') : DASH;
}

/** `1234` -> `'1,234'`; used for whole-number stat tiles. */
export function formatInt(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) return DASH;
  return Math.round(value).toLocaleString('en-US');
}

/** Rounds to the nearest `roundTo` and prefixes `~`, for a headline number built entirely (or
 * mostly) from unscouted `concept`/`desk-checked` segments (ARCHITECTURE.md principle 3: "the UI
 * never presents a guess as a fact"). `formatKm`'s one-decimal precision reads as measured; this
 * is for the same value when it is still a desk estimate. */
export function formatApproxKm(value: number | undefined, roundTo = 10): string {
  if (value === undefined || !Number.isFinite(value)) return DASH;
  const rounded = Math.round(value / roundTo) * roundTo;
  return `~${rounded.toLocaleString('en-US')} km`;
}

/** Same rounding-and-tilde treatment as `formatApproxKm`, for a metres value (e.g. ascent). */
export function formatApproxM(value: number | undefined, roundTo = 100): string {
  if (value === undefined || !Number.isFinite(value)) return DASH;
  const rounded = Math.round(value / roundTo) * roundTo;
  return `~${rounded.toLocaleString('en-US')} m`;
}

export const EM_DASH = DASH;
