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

export const EM_DASH = DASH;
