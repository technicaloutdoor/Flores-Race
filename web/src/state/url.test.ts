import { describe, expect, it } from 'vitest';
import { parseHash, serializeHash } from './url.ts';

describe('parseHash', () => {
  it('parses every field from the ARCHITECTURE.md §7.1 example', () => {
    const hash =
      '#mode=scout&route=r-traverse&sel=s-ruteng-reo-a&c=120.47,-8.61&z=11&base=topo&layers=network,pois';
    const parsed = parseHash(hash);

    expect(parsed.mode).toBe('scout');
    expect(parsed.routeId).toBe('r-traverse');
    expect(parsed.selection).toEqual({ type: 'segment', id: 's-ruteng-reo-a' });
    expect(parsed.center).toEqual([120.47, -8.61]);
    expect(parsed.zoom).toBe(11);
    expect(parsed.basemap).toBe('topo');
    expect(parsed.layers).toMatchObject({ network: true, pois: true, segments: false });
  });

  it('ignores unknown/invalid values instead of throwing', () => {
    const parsed = parseHash('#mode=bogus&z=not-a-number&c=1,2,3&sel=x-unknown-prefix');
    expect(parsed.mode).toBeUndefined();
    expect(parsed.zoom).toBeUndefined();
    expect(parsed.center).toBeUndefined();
    expect(parsed.selection).toBeUndefined();
  });

  it('returns an empty object for an empty hash', () => {
    expect(parseHash('')).toEqual({});
    expect(parseHash('#')).toEqual({});
  });
});

describe('serializeHash', () => {
  it('round-trips through parseHash', () => {
    const original = {
      mode: 'stakeholder' as const,
      routeId: 'r-traverse',
      selection: { type: 'poi' as const, id: 'p-kelimutu' },
      center: [121.4, -8.6] as [number, number],
      zoom: 8,
      basemap: 'osm' as const,
      layers: {
        network: false,
        segments: true,
        pois: true,
        nodes: false,
        regencies: true,
        hillshade: false,
        terrain3d: false,
      },
    };

    const hash = serializeHash(original);
    const reparsed = parseHash(hash);

    expect(reparsed).toEqual(original);
  });

  it('omits null/undefined fields rather than writing empty params', () => {
    const hash = serializeHash({ mode: 'public' });
    expect(hash).toBe('#mode=public');
  });
});
