// Pure derivation functions: everything a stakeholder number or an on-map marker needs, computed
// from the canonical bundle. Nothing here mutates its inputs or touches the network/DOM — see
// docs/data-model.md and ARCHITECTURE.md §8 ("Totals are always derived").

import type {
  Feature,
  Geometry,
  Position,
} from 'geojson';
import type {
  Route,
  Section,
  SegmentFeature,
  Stats,
  Status,
} from './types.ts';
import { SEGMENT_STATUSES } from './types.ts';

/** Resolves a route's segment ids to the actual segment features, in route order. Ids the bundle
 * doesn't have (a stale reference, or a fixture missing a segment) are silently skipped rather than
 * thrown — the map should still render what it can. */
export function routeSegments(
  route: Route,
  segments: SegmentFeature[],
): SegmentFeature[] {
  const byId = new Map(segments.map((s) => [s.properties.id, s]));
  const result: SegmentFeature[] = [];
  for (const id of route.segments) {
    const feature = byId.get(id);
    if (feature) result.push(feature);
  }
  return result;
}

export type RouteStats = Stats & {
  hab_km: number;
  segments_by_status: Record<Status, number>;
};

/** Sums segment stats into route totals — length, ascent/descent, hike-a-bike km, and a count of
 * segments per status (so the UI can show "12 confirmed / 4 concept" progress). Unpaved percentage
 * is length-weighted, not a plain average of segments. */
export function routeStats(segments: SegmentFeature[]): RouteStats {
  const segments_by_status = Object.fromEntries(
    SEGMENT_STATUSES.map((s) => [s, 0]),
  ) as Record<Status, number>;

  let length_km = 0;
  let ascent_m = 0;
  let descent_m = 0;
  let hab_km = 0;
  let unpavedLengthSum = 0;
  let min_elev_m: number | undefined;
  let max_elev_m: number | undefined;

  for (const feature of segments) {
    const props = feature.properties;
    segments_by_status[props.status] += 1;
    hab_km += props.est_hab_km ?? 0;

    const stats = props.stats;
    if (!stats) continue;
    const segLength = stats.length_km ?? 0;
    length_km += segLength;
    ascent_m += stats.ascent_m ?? 0;
    descent_m += stats.descent_m ?? 0;
    unpavedLengthSum += (stats.unpaved_pct ?? 0) * segLength;
    if (stats.min_elev_m !== undefined) {
      min_elev_m = min_elev_m === undefined ? stats.min_elev_m : Math.min(min_elev_m, stats.min_elev_m);
    }
    if (stats.max_elev_m !== undefined) {
      max_elev_m = max_elev_m === undefined ? stats.max_elev_m : Math.max(max_elev_m, stats.max_elev_m);
    }
  }

  return {
    length_km: round(length_km, 1),
    ascent_m: round(ascent_m, 0),
    descent_m: round(descent_m, 0),
    min_elev_m,
    max_elev_m,
    unpaved_pct: length_km > 0 ? round(unpavedLengthSum / length_km, 1) : 0,
    hab_km: round(hab_km, 1),
    segments_by_status,
  };
}

function round(n: number, decimals: number): number {
  const f = 10 ** decimals;
  return Math.round(n * f) / f;
}

/**
 * Finds which narrative section a segment falls under, by locating the segment's position in the
 * route's node chain and matching it against each section's [from_node, to_node) span. Returns
 * undefined if the route doesn't contain the segment, or no section's span covers it (e.g. a
 * fixture with incomplete sections).
 */
export function sectionForSegment(
  segmentId: string,
  route: Route,
  sections: Section[],
  segments: SegmentFeature[],
): Section | undefined {
  const segIndex = route.segments.indexOf(segmentId);
  if (segIndex === -1) return undefined;

  const byId = new Map(segments.map((s) => [s.properties.id, s]));
  // Node visited at the start of each chain position; chain[N] is the final to_node.
  const chain: string[] = [];
  for (const id of route.segments) {
    const feature = byId.get(id);
    if (!feature) return undefined; // chain has a gap; can't safely locate anything past it
    chain.push(feature.properties.from_node);
  }
  const lastFeature = byId.get(route.segments[route.segments.length - 1] ?? '');
  if (lastFeature) chain.push(lastFeature.properties.to_node);

  const ordered = [...sections].sort((a, b) => a.order - b.order);
  for (const section of ordered) {
    const startIdx = chain.indexOf(section.from_node);
    const endIdx = chain.indexOf(section.to_node);
    if (startIdx === -1 || endIdx === -1) continue;
    if (segIndex >= startIdx && segIndex < endIdx) return section;
  }
  return undefined;
}

/**
 * Resolves the ordered slice of a route's (already-resolved) segments that fall inside one
 * section's `[from_node, to_node)` span, by the same node-chain logic as `sectionForSegment` run
 * in the other direction. Returns `[]` rather than throwing when the route has a gap or the
 * section's anchors aren't both on this route's chain (e.g. a route that skips a section).
 */
export function segmentsInSection(
  section: Section,
  route: Route,
  segments: SegmentFeature[],
): SegmentFeature[] {
  const ordered = routeSegments(route, segments);
  if (ordered.length !== route.segments.length) return []; // a gap upstream; chain isn't trustworthy

  const chain: string[] = ordered.map((f) => f.properties.from_node);
  const last = ordered[ordered.length - 1];
  if (last) chain.push(last.properties.to_node);

  const startIdx = chain.indexOf(section.from_node);
  const endIdx = chain.indexOf(section.to_node);
  if (startIdx === -1 || endIdx === -1 || endIdx <= startIdx) return [];
  return ordered.slice(startIdx, endIdx);
}

/** Alternative candidates for the same `from_node`/`to_node` pair — the variants a scout compares
 * against each other (ARCHITECTURE.md: "Alternatives for the same pair share from_node/to_node and
 * differ in variant."). Excludes the segment itself. */
export function siblingVariants(
  segment: SegmentFeature,
  allSegments: SegmentFeature[],
): SegmentFeature[] {
  const { id, from_node, to_node } = segment.properties;
  return allSegments.filter(
    (s) =>
      s.properties.id !== id &&
      s.properties.from_node === from_node &&
      s.properties.to_node === to_node,
  );
}

export interface KmMarker {
  km: number;
  coord: [number, number];
}

/** Haversine great-circle distance in kilometres between two [lon, lat] points. Exported for
 * lib/gpx.ts, which needs the same measurement for an imported track's length. */
export function haversineKm(a: Position, b: Position): number {
  const R = 6371;
  const [lon1, lat1] = a;
  const [lon2, lat2] = b;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad((lat2 ?? 0) - (lat1 ?? 0));
  const dLon = toRad((lon2 ?? 0) - (lon1 ?? 0));
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1 ?? 0)) * Math.cos(toRad(lat2 ?? 0)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}

/**
 * Walks the concatenated geometry of a route's ordered segments and returns a marker every
 * `everyKm` kilometres (default 100), each with the cumulative distance and the coordinate at that
 * point (linearly interpolated between the two nearest vertices). Distance is measured along the
 * actual line, not geodesic-shortcut between segment endpoints.
 */
export function cumulativeKmMarkers(
  segments: SegmentFeature[],
  everyKm = 100,
): KmMarker[] {
  if (everyKm <= 0) return [];
  const markers: KmMarker[] = [];
  let cumulativeKm = 0;
  let nextMark = everyKm;

  for (const feature of segments) {
    const coords = feature.geometry.coordinates;
    for (let i = 0; i < coords.length - 1; i++) {
      const a = coords[i];
      const b = coords[i + 1];
      if (!a || !b) continue;
      const segKm = haversineKm(a, b);
      if (segKm === 0) continue;
      while (nextMark <= cumulativeKm + segKm) {
        const t = (nextMark - cumulativeKm) / segKm;
        const lon = a[0] + (b[0] - a[0]) * t;
        const lat = a[1] + (b[1] - a[1]) * t;
        markers.push({ km: round(nextMark, 0), coord: [lon, lat] });
        nextMark += everyKm;
      }
      cumulativeKm += segKm;
    }
  }
  return markers;
}

/**
 * Interpolated [lon, lat] at `km` along the concatenated geometry of `segments` (same walk as
 * `cumulativeKmMarkers`, generalised to one arbitrary target distance). Used by the elevation
 * profile panel to move a marker on the map as the mouse moves along the chart. Clamps to the
 * route's start/end for an out-of-range km rather than returning undefined, since a hover position
 * derived from the same profile array should never actually land outside it except by a rounding
 * hair; returns undefined only for an empty/zero-length input.
 */
export function coordAtKm(segments: SegmentFeature[], km: number): [number, number] | undefined {
  let cumulativeKm = 0;
  let lastCoord: Position | undefined;

  for (const feature of segments) {
    const coords = feature.geometry.coordinates;
    for (let i = 0; i < coords.length - 1; i++) {
      const a = coords[i];
      const b = coords[i + 1];
      if (!a || !b) continue;
      const segKm = haversineKm(a, b);
      lastCoord = b;
      if (segKm === 0) continue;
      if (km <= cumulativeKm + segKm) {
        const t = Math.max(0, (km - cumulativeKm) / segKm);
        return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      }
      cumulativeKm += segKm;
    }
  }
  return lastCoord ? [lastCoord[0], lastCoord[1]] : undefined;
}

export type BBox = [number, number, number, number]; // [minLon, minLat, maxLon, maxLat]

function eachPosition(geometry: Geometry, visit: (p: Position) => void): void {
  switch (geometry.type) {
    case 'Point':
      visit(geometry.coordinates);
      return;
    case 'MultiPoint':
    case 'LineString':
      geometry.coordinates.forEach(visit);
      return;
    case 'MultiLineString':
    case 'Polygon':
      geometry.coordinates.forEach((ring) => ring.forEach(visit));
      return;
    case 'MultiPolygon':
      geometry.coordinates.forEach((poly) => poly.forEach((ring) => ring.forEach(visit)));
      return;
    case 'GeometryCollection':
      geometry.geometries.forEach((g) => eachPosition(g, visit));
      return;
  }
}

/** Bounding box `[minLon, minLat, maxLon, maxLat]` over any set of GeoJSON features. */
export function bboxOf(features: Feature[]): BBox {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;

  for (const feature of features) {
    if (!feature.geometry) continue;
    eachPosition(feature.geometry, ([lon, lat]) => {
      if (lon === undefined || lat === undefined) return;
      if (lon < minLon) minLon = lon;
      if (lat < minLat) minLat = lat;
      if (lon > maxLon) maxLon = lon;
      if (lat > maxLat) maxLat = lat;
    });
  }

  return [minLon, minLat, maxLon, maxLat];
}
