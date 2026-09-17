// Pure search index for the header search box (ARCHITECTURE.md §7.3: "Header: ... search box").
// Kept dependency-free and DOM-free so it's easy to reason about; the header wires it to an
// `<input>` and a results list.

import type { Bundle } from '../data/store.ts';
import type { SelectionType } from '../state/store.ts';

export interface SearchItem {
  type: SelectionType;
  id: string;
  /** Display label, e.g. "Ruteng → Reo via Liang Bua". */
  label: string;
  /** Small secondary text, e.g. the node kind or segment status, shown dimmed next to the label. */
  meta: string;
  /** The underlying feature's own `public` flag — lets the header filter results in public mode
   * without the search index needing to know about modes itself (data/visibility.ts owns that). */
  public: boolean;
}

/** Builds the flat, searchable index once per bundle load: every node, POI and segment name. */
export function buildSearchIndex(bundle: Bundle): SearchItem[] {
  const items: SearchItem[] = [];
  for (const f of bundle.nodes.features) {
    items.push({
      type: 'node',
      id: f.properties.id,
      label: f.properties.name,
      meta: f.properties.kind,
      public: f.properties.public ?? false,
    });
  }
  for (const f of bundle.pois.features) {
    items.push({
      type: 'poi',
      id: f.properties.id,
      label: f.properties.name,
      meta: f.properties.category,
      public: f.properties.public ?? false,
    });
  }
  for (const f of bundle.segments.features) {
    items.push({
      type: 'segment',
      id: f.properties.id,
      label: f.properties.name,
      meta: f.properties.status,
      public: f.properties.public ?? false,
    });
  }
  return items;
}

/** Case-insensitive substring match against the label, ranking a prefix match above a mid-string
 * match, and otherwise preserving index order. Empty query returns []  (no "everything" dump). */
export function searchItems(items: readonly SearchItem[], query: string, limit = 8): SearchItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const scored: { item: SearchItem; score: number }[] = [];
  for (const item of items) {
    const label = item.label.toLowerCase();
    const idx = label.indexOf(q);
    if (idx === -1) continue;
    scored.push({ item, score: idx === 0 ? 0 : 1 });
  }
  scored.sort((a, b) => a.score - b.score);
  return scored.slice(0, limit).map((s) => s.item);
}
