// Small reusable DOM-building helpers shared by the panels (sidebar/inspector/scoutForm/profile) —
// badges, pills, dot meters, chips and the empty/loading/error state blocks every panel needs
// (BRIEF §8). Kept framework-free, matching the rest of web/src.

import {
  CONFIDENCE_META,
  STATUS_META,
  THEME_META,
  type Confidence,
  type Status,
  type Theme,
} from '../data/types.ts';
import { titleCase } from '../lib/format.ts';

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function statusPill(status: Status): HTMLElement {
  const meta = STATUS_META[status];
  const pill = el('span', 'pill');
  const dot = el('span', 'status-dot');
  dot.style.background = meta.color;
  pill.append(dot, document.createTextNode(meta.label));
  pill.title = meta.description;
  return pill;
}

/** Prominent, never-mistake-a-guess-for-a-fact badge (ARCHITECTURE.md §2). */
export function confidenceBadge(confidence: Confidence): HTMLElement {
  const meta = CONFIDENCE_META[confidence];
  const badge = el('span', `badge badge-confidence badge-${confidence}`, meta.label);
  badge.style.setProperty('--badge-color', meta.color);
  badge.title = meta.description;
  return badge;
}

export function themeChip(theme: Theme): HTMLElement {
  const meta = THEME_META[theme];
  const chip = el('span', 'chip', meta.label);
  chip.style.setProperty('--chip-color', meta.color);
  return chip;
}

export function priorityBadge(priority: number): HTMLElement {
  const cls = priority <= 1 ? 'priority-1' : priority === 2 ? 'priority-2' : 'priority-3';
  return el('span', `badge ${cls}`, `Priority ${priority}`);
}

export function habBadge(hab: 'low' | 'medium' | 'high'): HTMLElement {
  return el('span', `badge hab-${hab}`, `${titleCase(hab)} HAB`);
}

/** 5-dot meter for difficulty/remoteness (1-5). Extra dots beyond `max` are never rendered — the
 * data model caps both fields at 5. */
export function dotMeter(value: number, max = 5): HTMLElement {
  const wrap = el('span', 'dot-meter');
  wrap.setAttribute('role', 'img');
  wrap.setAttribute('aria-label', `${value} of ${max}`);
  for (let i = 1; i <= max; i++) {
    wrap.appendChild(el('span', i <= value ? 'dot dot-filled' : 'dot'));
  }
  return wrap;
}

export function localEditBadge(): HTMLElement {
  const badge = el('span', 'badge badge-local', 'Edited locally');
  badge.title = 'Changed in this browser via the scouting form; not yet exported.';
  return badge;
}

/** Renders a list of `sources` (URLs, or free text like "field:2026-07-14" / "map:overture") as
 * clickable links where it's a real URL and plain text otherwise. */
export function sourceList(sources: readonly string[]): HTMLElement {
  const ul = el('ul', 'source-list');
  for (const source of sources) {
    const li = el('li');
    if (/^https?:\/\//i.test(source)) {
      const a = el('a', undefined, source);
      a.href = source;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      li.appendChild(a);
    } else {
      li.textContent = source;
    }
    ul.appendChild(li);
  }
  return ul;
}

export function emptyState(message: string): HTMLElement {
  return el('p', 'state state-empty', message);
}

export function loadingState(message = 'Loading…'): HTMLElement {
  return el('p', 'state state-loading', message);
}

export function errorState(message: string): HTMLElement {
  return el('p', 'state state-error', message);
}

/** A labelled field row, e.g. "Water: reliable". Skips rendering entirely when `value` is empty. */
export function fieldRow(label: string, value: string): HTMLElement | null {
  if (!value) return null;
  const row = el('div', 'field-row');
  row.append(el('span', 'field-label', label), el('span', 'field-value', value));
  return row;
}

/** `title`, when given, becomes the tile's tooltip (e.g. explaining why a value reads 'n/a'). */
export function statTile(label: string, value: string, title?: string): HTMLElement {
  const tile = el('div', 'stat-tile');
  tile.append(el('div', 'stat-value', value), el('div', 'stat-label', label));
  if (title) tile.title = title;
  return tile;
}
