import { describe, expect, it } from 'vitest';
import {
  applyOverlayToProps,
  applyOverlayToSegment,
  clearOverlay,
  EMPTY_OVERLAY,
  getSegmentEdit,
  hasEdit,
  overlayToPatch,
  withoutSegment,
  withScoutingEntryAppended,
  withSegmentEdit,
  type OverlayData,
} from './overlay.ts';
import type { SegmentFeature, SegmentProps } from '../data/types.ts';

function props(overrides: Partial<SegmentProps> = {}): SegmentProps {
  return {
    id: 's-a-b',
    name: 'A to B',
    from_node: 'n-a',
    to_node: 'n-b',
    variant: 'A',
    status: 'concept',
    geometry_source: 'concept-sketch',
    character: 'unknown',
    est_hab_km: 0,
    difficulty: 1,
    remoteness: 1,
    sources: [],
    ...overrides,
  };
}

describe('applyOverlayToProps', () => {
  it('returns the original untouched when there is no edit', () => {
    const original = props();
    expect(applyOverlayToProps(original, undefined)).toBe(original);
  });

  it('overrides only the fields the edit sets, leaving the rest as-is', () => {
    const original = props({ status: 'concept', character: 'unknown', difficulty: 1 });
    const merged = applyOverlayToProps(original, { status: 'scouted-go' });
    expect(merged.status).toBe('scouted-go');
    expect(merged.character).toBe('unknown'); // untouched
    expect(merged.difficulty).toBe(1); // untouched
    expect(original.status).toBe('concept'); // original not mutated
  });

  it('concatenates scouting_append after the canonical scouting history rather than replacing it', () => {
    const original = props({
      scouting: [{ date: '2026-01-01', team: 'RC', verdict: 'partial' }],
    });
    const merged = applyOverlayToProps(original, {
      scouting_append: [{ date: '2026-07-14', team: 'MB', verdict: 'go' }],
    });
    expect(merged.scouting).toEqual([
      { date: '2026-01-01', team: 'RC', verdict: 'partial' },
      { date: '2026-07-14', team: 'MB', verdict: 'go' },
    ]);
    expect(original.scouting).toHaveLength(1); // original array not mutated
  });

  it('handles an edit with an empty scouting_append array as a no-op for scouting history', () => {
    const original = props({ scouting: [{ date: '2026-01-01', team: 'RC', verdict: 'go' }] });
    const merged = applyOverlayToProps(original, { scouting_append: [] });
    expect(merged.scouting).toEqual(original.scouting);
  });
});

describe('applyOverlayToSegment', () => {
  it('merges into the feature properties without touching geometry', () => {
    const segment: SegmentFeature = {
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [[120, -8], [120.1, -8.1]] },
      properties: props(),
    };
    const merged = applyOverlayToSegment(segment, { status: 'confirmed' });
    expect(merged.properties.status).toBe('confirmed');
    expect(merged.geometry).toBe(segment.geometry);
    expect(segment.properties.status).toBe('concept'); // original untouched
  });
});

describe('withSegmentEdit / getSegmentEdit / hasEdit', () => {
  it('creates an edit for a segment with no prior edit', () => {
    const overlay = withSegmentEdit(EMPTY_OVERLAY, 's-a-b', { status: 'scouted-go' });
    expect(getSegmentEdit(overlay, 's-a-b')?.status).toBe('scouted-go');
    expect(hasEdit(overlay, 's-a-b')).toBe(true);
    expect(hasEdit(overlay, 's-other')).toBe(false);
  });

  it('merges a second patch on top of the first, keeping earlier fields', () => {
    let overlay = withSegmentEdit(EMPTY_OVERLAY, 's-a-b', { status: 'scouted-go' });
    overlay = withSegmentEdit(overlay, 's-a-b', { difficulty: 4 });
    const edit = getSegmentEdit(overlay, 's-a-b');
    expect(edit?.status).toBe('scouted-go');
    expect(edit?.difficulty).toBe(4);
    expect(edit?.edited_at).toBeDefined();
  });

  it('does not mutate the input overlay (immutable update)', () => {
    const before = EMPTY_OVERLAY;
    withSegmentEdit(before, 's-a-b', { status: 'confirmed' });
    expect(before.segments).toEqual({});
  });
});

describe('withScoutingEntryAppended', () => {
  it('appends to an empty list', () => {
    const overlay = withScoutingEntryAppended(EMPTY_OVERLAY, 's-a-b', {
      date: '2026-07-14',
      team: 'RC',
      verdict: 'go',
    });
    expect(getSegmentEdit(overlay, 's-a-b')?.scouting_append).toEqual([
      { date: '2026-07-14', team: 'RC', verdict: 'go' },
    ]);
  });

  it('accumulates multiple entries in order', () => {
    let overlay = withScoutingEntryAppended(EMPTY_OVERLAY, 's-a-b', {
      date: '2026-07-14',
      team: 'RC',
      verdict: 'go',
    });
    overlay = withScoutingEntryAppended(overlay, 's-a-b', {
      date: '2026-08-01',
      team: 'MB',
      verdict: 'partial',
    });
    expect(getSegmentEdit(overlay, 's-a-b')?.scouting_append).toHaveLength(2);
    expect(getSegmentEdit(overlay, 's-a-b')?.scouting_append?.[1]?.team).toBe('MB');
  });

  it('preserves other fields already set on that segment', () => {
    let overlay = withSegmentEdit(EMPTY_OVERLAY, 's-a-b', { status: 'scouted-go' });
    overlay = withScoutingEntryAppended(overlay, 's-a-b', {
      date: '2026-07-14',
      team: 'RC',
      verdict: 'go',
    });
    expect(getSegmentEdit(overlay, 's-a-b')?.status).toBe('scouted-go');
  });
});

describe('withoutSegment / clearOverlay', () => {
  it('removes only the targeted segment', () => {
    let overlay = withSegmentEdit(EMPTY_OVERLAY, 's-a-b', { status: 'confirmed' });
    overlay = withSegmentEdit(overlay, 's-c-d', { status: 'needs-recheck' });
    overlay = withoutSegment(overlay, 's-a-b');
    expect(hasEdit(overlay, 's-a-b')).toBe(false);
    expect(hasEdit(overlay, 's-c-d')).toBe(true);
  });

  it('clearOverlay discards everything', () => {
    const overlay: OverlayData = withSegmentEdit(EMPTY_OVERLAY, 's-a-b', { status: 'confirmed' });
    expect(clearOverlay()).toEqual({ version: 1, segments: {} });
    expect(overlay.segments['s-a-b']).toBeDefined(); // clearOverlay doesn't touch its argument (takes none)
  });
});

describe('overlayToPatch', () => {
  it('drops the UI-only edited_at field', () => {
    const overlay = withSegmentEdit(EMPTY_OVERLAY, 's-a-b', { status: 'scouted-go' });
    const patch = overlayToPatch(overlay, 'RC');
    expect(patch.segments?.['s-a-b']).toEqual({ status: 'scouted-go' });
    expect(patch.segments?.['s-a-b']).not.toHaveProperty('edited_at');
  });

  it('sets version, author and an ISO created timestamp', () => {
    const overlay = withSegmentEdit(EMPTY_OVERLAY, 's-a-b', { status: 'confirmed' });
    const patch = overlayToPatch(overlay, 'RC');
    expect(patch.version).toBe(1);
    expect(patch.author).toBe('RC');
    expect(() => new Date(patch.created).toISOString()).not.toThrow();
  });

  it('omits a segment left with no actual field set', () => {
    // withSegmentEdit with an empty patch still stamps edited_at; overlayToPatch should drop it.
    const overlay = withSegmentEdit(EMPTY_OVERLAY, 's-a-b', {});
    const patch = overlayToPatch(overlay, 'RC');
    expect(patch.segments?.['s-a-b']).toBeUndefined();
  });

  it('includes scouting_append entries', () => {
    const overlay = withScoutingEntryAppended(EMPTY_OVERLAY, 's-a-b', {
      date: '2026-07-14',
      team: 'RC',
      verdict: 'go',
    });
    const patch = overlayToPatch(overlay, 'RC');
    expect(patch.segments?.['s-a-b']?.scouting_append).toEqual([
      { date: '2026-07-14', team: 'RC', verdict: 'go' },
    ]);
  });
});
