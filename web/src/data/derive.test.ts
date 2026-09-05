import { describe, expect, it } from 'vitest';
import {
  bboxOf,
  cumulativeKmMarkers,
  haversineKm,
  routeSegments,
  routeStats,
  sectionForSegment,
  segmentsInSection,
  siblingVariants,
} from './derive.ts';
import type { Route, Section, SegmentFeature } from './types.ts';

function segment(
  id: string,
  from: string,
  to: string,
  coords: [number, number][],
  overrides: Partial<SegmentFeature['properties']> = {},
): SegmentFeature {
  return {
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: coords },
    properties: {
      id,
      name: id,
      from_node: from,
      to_node: to,
      variant: 'A',
      status: 'concept',
      geometry_source: 'concept-sketch',
      character: 'unknown',
      est_hab_km: 0,
      difficulty: 1,
      remoteness: 1,
      sources: [],
      ...overrides,
    },
  };
}

const segA = segment('s-a-b', 'n-a', 'n-b', [
  [120, -8],
  [120.1, -8.05],
], { status: 'confirmed', est_hab_km: 2, stats: { length_km: 10, ascent_m: 100, descent_m: 20, min_elev_m: 0, max_elev_m: 100, unpaved_pct: 50 } });

const segB = segment('s-b-c', 'n-b', 'n-c', [
  [120.1, -8.05],
  [120.2, -8.1],
], { status: 'concept', est_hab_km: 1, stats: { length_km: 10, ascent_m: 50, descent_m: 50, min_elev_m: 50, max_elev_m: 150, unpaved_pct: 100 } });

const route: Route = {
  id: 'r-test',
  name: 'Test route',
  audience: ['scout'],
  anchors: ['n-a', 'n-b', 'n-c'],
  segments: ['s-a-b', 's-b-c'],
  status: 'concept',
  target_km_range: [15, 25],
};

const sections: Section[] = [
  {
    id: 'sec-01-first',
    order: 1,
    title: 'First half',
    from_node: 'n-a',
    to_node: 'n-b',
    theme: ['highland'],
    story: '...',
    highlight_pois: [],
    target_km: [5, 15],
    hab_expected: 'low',
    scouting_priority: 1,
    open_questions: [],
  },
  {
    id: 'sec-02-second',
    order: 2,
    title: 'Second half',
    from_node: 'n-b',
    to_node: 'n-c',
    theme: ['coast'],
    story: '...',
    highlight_pois: [],
    target_km: [5, 15],
    hab_expected: 'low',
    scouting_priority: 1,
    open_questions: [],
  },
];

describe('routeSegments', () => {
  it('resolves route segment ids to features, in order, skipping missing ones', () => {
    const resolved = routeSegments(route, [segB, segA]); // deliberately out of order
    expect(resolved.map((f) => f.properties.id)).toEqual(['s-a-b', 's-b-c']);
  });

  it('skips ids the bundle does not have rather than throwing', () => {
    const resolved = routeSegments(route, [segA]);
    expect(resolved.map((f) => f.properties.id)).toEqual(['s-a-b']);
  });
});

describe('routeStats', () => {
  it('sums length/ascent/descent/hab_km and counts segments by status', () => {
    const stats = routeStats([segA, segB]);
    expect(stats.length_km).toBe(20);
    expect(stats.ascent_m).toBe(150);
    expect(stats.descent_m).toBe(70);
    expect(stats.hab_km).toBe(3);
    expect(stats.segments_by_status.confirmed).toBe(1);
    expect(stats.segments_by_status.concept).toBe(1);
    expect(stats.segments_by_status['scouted-go']).toBe(0);
  });

  it('weights unpaved_pct by segment length, not a plain average', () => {
    const stats = routeStats([segA, segB]); // both 10km, 50% and 100% -> 75%
    expect(stats.unpaved_pct).toBe(75);
  });
});

describe('sectionForSegment', () => {
  it('finds the section whose node span contains the segment', () => {
    const section = sectionForSegment('s-b-c', route, sections, [segA, segB]);
    expect(section?.id).toBe('sec-02-second');
  });

  it('returns undefined for a segment not in the route', () => {
    expect(sectionForSegment('s-nope', route, sections, [segA, segB])).toBeUndefined();
  });
});

describe('cumulativeKmMarkers', () => {
  it('places a marker every `everyKm` along the concatenated line', () => {
    // ~111 km per degree of latitude at the equator; two 1-degree-of-latitude segments ~= 222 km.
    const long1 = segment('s-long-1', 'n-x', 'n-y', [
      [0, 0],
      [0, -1],
    ]);
    const long2 = segment('s-long-2', 'n-y', 'n-z', [
      [0, -1],
      [0, -2],
    ]);
    const markers = cumulativeKmMarkers([long1, long2], 100);
    expect(markers.length).toBeGreaterThanOrEqual(2);
    expect(markers[0]!.km).toBe(100);
    expect(markers[1]!.km).toBe(200);
  });

  it('returns no markers when the route is shorter than the interval', () => {
    expect(cumulativeKmMarkers([segA], 100)).toEqual([]);
  });
});

describe('bboxOf', () => {
  it('computes [minLon, minLat, maxLon, maxLat] across mixed geometry types', () => {
    const bbox = bboxOf([segA, segB]);
    expect(bbox).toEqual([120, -8.1, 120.2, -8]);
  });
});

describe('haversineKm', () => {
  it('is ~111 km per degree of latitude at the equator', () => {
    expect(haversineKm([0, 0], [0, 1])).toBeCloseTo(111.19, 1);
  });

  it('is zero for identical points', () => {
    expect(haversineKm([120.47, -8.61], [120.47, -8.61])).toBe(0);
  });
});

describe('segmentsInSection', () => {
  it('returns the ordered slice of a route whose chain falls inside the section span', () => {
    const section: Section = sections[1]!; // n-b -> n-c
    expect(segmentsInSection(section, route, [segA, segB]).map((f) => f.properties.id)).toEqual([
      's-b-c',
    ]);
  });

  it('returns every matching segment, not just the first, for a multi-segment span', () => {
    const wholeRouteSection: Section = { ...sections[0]!, from_node: 'n-a', to_node: 'n-c' };
    expect(
      segmentsInSection(wholeRouteSection, route, [segA, segB]).map((f) => f.properties.id),
    ).toEqual(['s-a-b', 's-b-c']);
  });

  it('returns [] when the route has a gap (a referenced segment is missing)', () => {
    expect(segmentsInSection(sections[0]!, route, [segA])).toEqual([]);
  });

  it('returns [] when the section anchors are not both on the chain', () => {
    const elsewhere: Section = { ...sections[0]!, from_node: 'n-a', to_node: 'n-nowhere' };
    expect(segmentsInSection(elsewhere, route, [segA, segB])).toEqual([]);
  });
});

describe('siblingVariants', () => {
  it('finds other variants sharing the same from_node/to_node, excluding itself', () => {
    const segAVariantB = segment('s-a-b-b', 'n-a', 'n-b', [
      [120, -8],
      [120.05, -8.02],
    ], { variant: 'B' });
    const siblings = siblingVariants(segA, [segA, segAVariantB, segB]);
    expect(siblings.map((f) => f.properties.id)).toEqual(['s-a-b-b']);
  });

  it('returns [] when no other variant shares the pair', () => {
    expect(siblingVariants(segA, [segA, segB])).toEqual([]);
  });
});
