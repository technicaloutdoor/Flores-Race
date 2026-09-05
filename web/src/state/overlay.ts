// Scout-mode edits, kept locally and applied on top of the bundle for display (ARCHITECTURE.md
// §7.4). A scouting edit never touches the fetched bundle in place — it lives in a small overlay
// object, keyed by segment id, mirroring `schemas/scouting-patch.schema.json` closely enough that
// `overlayToPatch` is close to a no-op. The merge functions below are pure and DOM/localStorage-free
// so they're unit-testable in a plain Node environment; `loadOverlay`/`saveOverlay` are the only
// functions that touch `localStorage`, wrapped so a private-browsing tab or a disabled storage API
// degrades to "edits last for this tab session" instead of throwing.

import { createStore, type Store } from './store.ts';
import type {
  Character,
  ScoutingEntry,
  ScoutingPatch,
  SegmentFeature,
  SegmentProps,
  Status,
} from '../data/types.ts';

/** The scouting-owned fields a patch may change (data-model.md "Scouting patch" rules) — geometry
 * and ids are never part of this. */
export interface SegmentOverlayEdit {
  status?: Status;
  character?: Character;
  est_hab_km?: number;
  difficulty?: number;
  remoteness?: number;
  water_points?: string[];
  resupply_notes?: string;
  hazards?: string[];
  cultural_notes?: string;
  open_questions?: string[];
  scouting_append?: ScoutingEntry[];
  /** ISO timestamp of the last local change to this segment; drives the "edited locally" badge. Not
   * part of the exported patch. */
  edited_at?: string;
}

export interface OverlayData {
  version: 1;
  segments: Record<string, SegmentOverlayEdit>;
}

export const EMPTY_OVERLAY: OverlayData = { version: 1, segments: {} };

const STORAGE_KEY = 'flores-race-overlay-v1';
const AUTHOR_KEY = 'flores-race-scout-author';

function getStorage(): Storage | undefined {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : undefined;
  } catch {
    return undefined; // some browsers throw just accessing the property (storage disabled)
  }
}

export function loadOverlay(): OverlayData {
  const storage = getStorage();
  if (!storage) return { version: 1, segments: {} };
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return { version: 1, segments: {} };
    const parsed = JSON.parse(raw) as Partial<OverlayData>;
    if (parsed.version !== 1 || typeof parsed.segments !== 'object' || parsed.segments === null) {
      return { version: 1, segments: {} };
    }
    return { version: 1, segments: parsed.segments };
  } catch {
    return { version: 1, segments: {} };
  }
}

export function saveOverlay(data: OverlayData): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // Storage full or unavailable: edits stay live in the in-memory store for this tab only.
  }
}

export function getAuthor(): string {
  const storage = getStorage();
  try {
    return storage?.getItem(AUTHOR_KEY) ?? '';
  } catch {
    return '';
  }
}

export function setAuthor(name: string): void {
  const storage = getStorage();
  try {
    storage?.setItem(AUTHOR_KEY, name);
  } catch {
    // ignore
  }
}

/** The overlay held live for the running tab. Reads localStorage once at module load and persists
 * every subsequent change back to it — every panel that needs "is there a local edit for this id"
 * or "give me the merged segment" reads through this store, never `localStorage` directly. */
export const overlayStore: Store<OverlayData> = createStore(loadOverlay());
overlayStore.subscribe((state) => saveOverlay(state));

// --- Pure merge/update functions (unit tested directly) --------------------------------------

/** Overlays one segment's local edit onto its canonical properties for display. Fields the edit
 * doesn't mention are left untouched; `scouting_append` entries are concatenated after the
 * canonical history rather than replacing it, so the record stays additive. Never mutates
 * `original`. */
export function applyOverlayToProps(
  original: SegmentProps,
  edit: SegmentOverlayEdit | undefined,
): SegmentProps {
  if (!edit) return original;
  const merged: SegmentProps = { ...original };
  if (edit.status !== undefined) merged.status = edit.status;
  if (edit.character !== undefined) merged.character = edit.character;
  if (edit.est_hab_km !== undefined) merged.est_hab_km = edit.est_hab_km;
  if (edit.difficulty !== undefined) merged.difficulty = edit.difficulty;
  if (edit.remoteness !== undefined) merged.remoteness = edit.remoteness;
  if (edit.water_points !== undefined) merged.water_points = edit.water_points;
  if (edit.resupply_notes !== undefined) merged.resupply_notes = edit.resupply_notes;
  if (edit.hazards !== undefined) merged.hazards = edit.hazards;
  if (edit.cultural_notes !== undefined) merged.cultural_notes = edit.cultural_notes;
  if (edit.open_questions !== undefined) merged.open_questions = edit.open_questions;
  if (edit.scouting_append?.length) {
    merged.scouting = [...(original.scouting ?? []), ...edit.scouting_append];
  }
  return merged;
}

export function applyOverlayToSegment(
  segment: SegmentFeature,
  edit: SegmentOverlayEdit | undefined,
): SegmentFeature {
  if (!edit) return segment;
  return { ...segment, properties: applyOverlayToProps(segment.properties, edit) };
}

export function getSegmentEdit(overlay: OverlayData, id: string): SegmentOverlayEdit | undefined {
  return overlay.segments[id];
}

export function hasEdit(overlay: OverlayData, id: string): boolean {
  return Boolean(overlay.segments[id]);
}

/** Returns a new overlay with `patch` merged into segment `id`'s edit (creating it if absent) and
 * `edited_at` refreshed. Does not touch `scouting_append` — use `withScoutingEntryAppended` for that,
 * so a form-field save never accidentally drops previously appended entries. */
export function withSegmentEdit(
  overlay: OverlayData,
  id: string,
  patch: Partial<Omit<SegmentOverlayEdit, 'scouting_append' | 'edited_at'>>,
): OverlayData {
  const existing = overlay.segments[id] ?? {};
  const next: SegmentOverlayEdit = { ...existing, ...patch, edited_at: new Date().toISOString() };
  return { ...overlay, segments: { ...overlay.segments, [id]: next } };
}

export function withScoutingEntryAppended(
  overlay: OverlayData,
  id: string,
  entry: ScoutingEntry,
): OverlayData {
  const existing = overlay.segments[id] ?? {};
  const next: SegmentOverlayEdit = {
    ...existing,
    scouting_append: [...(existing.scouting_append ?? []), entry],
    edited_at: new Date().toISOString(),
  };
  return { ...overlay, segments: { ...overlay.segments, [id]: next } };
}

/** Discards local edits for one segment. */
export function withoutSegment(overlay: OverlayData, id: string): OverlayData {
  const { [id]: _removed, ...rest } = overlay.segments;
  return { ...overlay, segments: rest };
}

/** Discards every local edit. */
export function clearOverlay(): OverlayData {
  return { version: 1, segments: {} };
}

/** Builds the exported patch (`schemas/scouting-patch.schema.json`): drops the UI-only `edited_at`
 * field and any segment entry left with no actual field set (e.g. one touched then reverted). */
export function overlayToPatch(overlay: OverlayData, author: string): ScoutingPatch {
  const segments: NonNullable<ScoutingPatch['segments']> = {};
  for (const [id, edit] of Object.entries(overlay.segments)) {
    const { edited_at: _editedAt, ...rest } = edit;
    if (Object.keys(rest).length === 0) continue;
    segments[id] = rest;
  }
  return {
    version: 1,
    created: new Date().toISOString(),
    author,
    segments,
  };
}
