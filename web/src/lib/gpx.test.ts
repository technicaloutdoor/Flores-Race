import { describe, expect, it } from 'vitest';
import {
  buildGpx,
  gpxTrackLengthKm,
  parseGpxTrack,
  routeGpx,
  sectionGpx,
  segmentGpx,
  segmentToGpxTrack,
} from './gpx.ts';
import type { Route, Section, SegmentFeature } from '../data/types.ts';

function segment(
  id: string,
  overrides: Partial<SegmentFeature['properties']> = {},
  coords: [number, number][] = [
    [120, -8],
    [120.1, -8.05],
  ],
): SegmentFeature {
  return {
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: coords },
    properties: {
      id,
      name: `Segment ${id}`,
      from_node: 'n-a',
      to_node: 'n-b',
      variant: 'A',
      status: 'concept',
      geometry_source: 'concept-sketch',
      character: 'gravel',
      est_hab_km: 0,
      difficulty: 2,
      remoteness: 2,
      sources: [],
      ...overrides,
    },
  };
}

describe('buildGpx', () => {
  it('produces one <trk><trkseg> per input track, with name and desc', () => {
    const xml = buildGpx([
      { name: 'Leg 1', desc: 'status: concept', coordinates: [[120, -8], [120.1, -8.05]] },
      { name: 'Leg 2', desc: 'status: confirmed', coordinates: [[120.1, -8.05], [120.2, -8.1]] },
    ]);
    expect(xml).toContain('<?xml version="1.0" encoding="UTF-8"?>');
    expect(xml).toContain('<gpx version="1.1"');
    expect((xml.match(/<trk>/g) ?? []).length).toBe(2);
    expect((xml.match(/<trkseg>/g) ?? []).length).toBe(2);
    expect(xml).toContain('<name>Leg 1</name>');
    expect(xml).toContain('<desc>status: concept</desc>');
    expect(xml).toContain('<trkpt lat="-8" lon="120"></trkpt>');
  });

  it('escapes XML special characters in name/desc', () => {
    const xml = buildGpx([{ name: 'Ruteng → Reo & "co"', desc: '<no-go>', coordinates: [[120, -8]] }]);
    expect(xml).toContain('&amp;');
    expect(xml).toContain('&lt;no-go&gt;');
    expect(xml).not.toContain('<no-go>');
  });

  it('adds a <metadata><name> when metadataName is given', () => {
    const xml = buildGpx([{ name: 'Leg', desc: '', coordinates: [[120, -8]] }], {
      metadataName: 'Traverse',
    });
    expect(xml).toContain('<metadata><name>Traverse</name></metadata>');
  });

  it('omits <metadata> entirely when metadataName is not given', () => {
    const xml = buildGpx([{ name: 'Leg', desc: '', coordinates: [[120, -8]] }]);
    expect(xml).not.toContain('<metadata>');
  });
});

describe('segmentGpx / routeGpx / sectionGpx', () => {
  const seg = segment('s-a-b', { status: 'scouted-go', character: 'dirt', variant: 'A' });

  it('segmentGpx embeds the status in <desc>', () => {
    const xml = segmentGpx(seg);
    expect(xml).toContain('status: scouted-go');
    expect(xml).toContain('character: dirt');
  });

  it('routeGpx emits one <trk> per segment and names the file after the route', () => {
    const seg2 = segment('s-b-c', { from_node: 'n-b', to_node: 'n-c' });
    const route: Route = {
      id: 'r-test',
      name: 'Test Traverse',
      audience: ['scout'],
      anchors: ['n-a', 'n-b', 'n-c'],
      segments: ['s-a-b', 's-b-c'],
      status: 'concept',
      target_km_range: [10, 20],
    };
    const xml = routeGpx(route, [seg, seg2]);
    expect(xml).toContain('<metadata><name>Test Traverse</name></metadata>');
    expect((xml.match(/<trk>/g) ?? []).length).toBe(2);
  });

  it('sectionGpx names the file after the section title', () => {
    const section: Section = {
      id: 'sec-01-test',
      order: 1,
      title: 'Test Section',
      from_node: 'n-a',
      to_node: 'n-b',
      theme: ['highland'],
      story: '...',
      highlight_pois: [],
      target_km: [5, 15],
      hab_expected: 'low',
      scouting_priority: 1,
      open_questions: [],
    };
    const xml = sectionGpx(section, [seg]);
    expect(xml).toContain('<metadata><name>Test Section</name></metadata>');
  });

  it('segmentToGpxTrack carries the geometry through unchanged', () => {
    const track = segmentToGpxTrack(seg);
    expect(track.coordinates).toEqual(seg.geometry.coordinates);
  });
});

describe('parseGpxTrack', () => {
  it('extracts lat/lon points regardless of attribute order and quote style', () => {
    const xml = `<gpx><trk><trkseg><trkpt lat="-8.6" lon="120.47"></trkpt><trkpt lon='120.5' lat='-8.65' /></trkseg></trk></gpx>`;
    const parsed = parseGpxTrack(xml);
    expect(parsed.points).toEqual([
      [120.47, -8.6],
      [120.5, -8.65],
    ]);
  });

  it('reads the first <name> if present', () => {
    const xml = `<gpx><trk><name>My ride</name><trkseg><trkpt lat="1" lon="2"/></trkseg></trk></gpx>`;
    expect(parseGpxTrack(xml).name).toBe('My ride');
  });

  it('omits name when absent', () => {
    const xml = `<gpx><trk><trkseg><trkpt lat="1" lon="2"/></trkseg></trk></gpx>`;
    expect(parseGpxTrack(xml).name).toBeUndefined();
  });

  it('skips malformed points and returns [] for a file with none', () => {
    const xml = `<gpx><trk><trkseg><trkpt lat="not-a-number" lon="120"/></trkseg></trk></gpx>`;
    expect(parseGpxTrack(xml).points).toEqual([]);
  });

  it('round-trips through buildGpx', () => {
    const original: [number, number][] = [
      [120.47, -8.61],
      [120.5, -8.65],
      [120.6, -8.7],
    ];
    const xml = buildGpx([{ name: 'Round trip', desc: '', coordinates: original }]);
    expect(parseGpxTrack(xml).points).toEqual(original);
  });
});

describe('gpxTrackLengthKm', () => {
  it('sums haversine distance across consecutive points', () => {
    // one degree of latitude at the equator ~= 111.19 km; two such legs ~= 222.4 km
    const km = gpxTrackLengthKm([
      [0, 0],
      [0, -1],
      [0, -2],
    ]);
    expect(km).toBeCloseTo(222.4, 0);
  });

  it('is 0 for fewer than two points', () => {
    expect(gpxTrackLengthKm([])).toBe(0);
    expect(gpxTrackLengthKm([[120, -8]])).toBe(0);
  });
});
