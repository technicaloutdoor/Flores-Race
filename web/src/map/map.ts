// Creates the MapLibre map: empty style (sources/layers come from basemaps.ts, terrain.ts and
// layers.ts), fixed island-ish extent, and an attribution control whose text is filled in once
// meta.json has loaded. See ARCHITECTURE.md §7.1-7.2.

import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { DEFAULT_VIEWPORT, type Viewport } from '../state/url.ts';

/** Flores main island, roughly — see BRIEF "Geographic frame". */
export const ISLAND_BBOX: [number, number, number, number] = [119.7, -9.0, 123.1, -8.0];

/** A bit larger than the island so panning near the edges still feels natural. */
const BOUNDS_PADDING_DEG = 1.0;
export const MAX_BOUNDS: [[number, number], [number, number]] = [
  [ISLAND_BBOX[0] - BOUNDS_PADDING_DEG, ISLAND_BBOX[1] - BOUNDS_PADDING_DEG],
  [ISLAND_BBOX[2] + BOUNDS_PADDING_DEG, ISLAND_BBOX[3] + BOUNDS_PADDING_DEG],
];

/** MapLibre demo glyphs. Reachable from a real browser; blocked in this build sandbox — that is
 * expected (see BRIEF "Sandbox network reality"), not a bug. Labels simply won't render here. */
const GLYPHS_URL = 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf';

export interface CreateMapOptions {
  container: HTMLElement | string;
  viewport?: Viewport;
}

export interface FloresMap {
  map: MapLibreMap;
  /** Replaces the attribution control's text (called once meta.json's `attribution` is known). */
  setAttribution(strings: string[]): void;
  getViewport(): Viewport;
}

export function createMap(options: CreateMapOptions): FloresMap {
  const viewport = options.viewport ?? DEFAULT_VIEWPORT;

  const map = new maplibregl.Map({
    container: options.container,
    style: {
      version: 8,
      glyphs: GLYPHS_URL,
      sources: {},
      layers: [],
    },
    center: viewport.center,
    zoom: viewport.zoom,
    minZoom: 6,
    maxZoom: 18,
    maxBounds: MAX_BOUNDS,
    attributionControl: false,
  });

  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-right');

  let attributionControl: maplibregl.AttributionControl | undefined;

  function setAttribution(strings: string[]): void {
    if (attributionControl) map.removeControl(attributionControl);
    attributionControl = new maplibregl.AttributionControl({
      compact: true,
      customAttribution: strings,
    });
    map.addControl(attributionControl);
  }

  // Seed with an empty control immediately so the (required) control exists before meta.json loads.
  setAttribution([]);

  function getViewport(): Viewport {
    const center = map.getCenter();
    return { center: [center.lng, center.lat], zoom: map.getZoom() };
  }

  return { map, setAttribution, getViewport };
}
