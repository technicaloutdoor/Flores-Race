// Small map-camera helpers shared by the sidebar (click a section), story mode (fly section by
// section) and the header search box (fly to a result). Kept out of map/map.ts so those modules
// don't need to import each other.

import type { Map as MapLibreMap } from 'maplibre-gl';
import type { BBox } from '../data/derive.ts';

export interface FlyOptions {
  padding?: number;
  duration?: number;
}

// Flores main island, framed a touch tighter than map/map.ts's `ISLAND_BBOX` (which is padded
// further out for `maxBounds`, so panning near the edges still feels natural) -- this one is only
// for the first-view framing, so the whole island fills the frame rather than mostly open sea.
export const ISLAND_FIT_BOUNDS: [[number, number], [number, number]] = [
  [119.75, -9.0],
  [123.1, -8.05],
];

/**
 * Frames the whole island on first load, when the URL hash didn't already pin a centre/zoom
 * (main.ts checks that before calling this). The side panels sit in their own CSS grid columns
 * outside `#map` (see index.html/style.css), so this padding is just a visual margin, not a dodge
 * around anything overlapping the map canvas.
 */
export function fitIsland(map: MapLibreMap): void {
  map.fitBounds(ISLAND_FIT_BOUNDS, {
    padding: { top: 20, bottom: 20, left: 20, right: 20 },
    animate: false,
  });
}

/** Fits the map to a bbox from `derive.bboxOf`. A degenerate bbox (a single point, or an empty
 * input with `Infinity` sentinels) falls back to `flyTo` so this never throws on an empty
 * selection — callers can pass whatever `bboxOf` gives them without checking first. */
export function flyToBbox(map: MapLibreMap, bbox: BBox, options: FlyOptions = {}): void {
  const [minLon, minLat, maxLon, maxLat] = bbox;
  if (![minLon, minLat, maxLon, maxLat].every(Number.isFinite)) return;

  if (minLon === maxLon && minLat === maxLat) {
    map.flyTo({
      center: [minLon, minLat],
      zoom: Math.max(map.getZoom(), 12),
      duration: options.duration ?? 800,
      essential: true,
    });
    return;
  }

  map.fitBounds(
    [
      [minLon, minLat],
      [maxLon, maxLat],
    ],
    { padding: options.padding ?? 60, duration: options.duration ?? 800, essential: true },
  );
}

export function flyToPoint(
  map: MapLibreMap,
  coord: [number, number],
  options: { zoom?: number; duration?: number } = {},
): void {
  map.flyTo({
    center: coord,
    zoom: Math.max(map.getZoom(), options.zoom ?? 13),
    duration: options.duration ?? 900,
    essential: true,
  });
}
