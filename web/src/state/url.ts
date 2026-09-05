// Two-way sync between the store and `location.hash`, per ARCHITECTURE.md §7.1:
//   #mode=scout&route=r-traverse&sel=s-ruteng-reo-a&c=120.47,-8.61&z=11&base=topo&layers=network,pois
//
// The pure parse/serialize functions below have no DOM dependency and are unit tested directly.
// `bindUrlSync` is the only part that touches `window`/`location`; it wires those pure functions
// to real hash reads/writes, debounced so rapid map panning doesn't spam history.

import {
  BASEMAPS,
  LAYER_KEYS,
  MODES,
  selectionFromId,
  type AppState,
  type BasemapId,
  type LayerVisibility,
  type Mode,
  type Selection,
  type Store,
} from './store.ts';

/** Map viewport as tracked in the URL. Not part of `AppState` — the map owns it directly. */
export interface Viewport {
  center: [number, number]; // [lon, lat]
  zoom: number;
}

export const DEFAULT_VIEWPORT: Viewport = { center: [121.4, -8.6], zoom: 8 };

/** Everything the hash can carry, all optional: a fragment may set any subset of these. */
export interface HashState {
  mode?: Mode;
  routeId?: string;
  selection?: Selection;
  center?: [number, number];
  zoom?: number;
  basemap?: BasemapId;
  layers?: LayerVisibility;
}

function isMode(value: string): value is Mode {
  return (MODES as readonly string[]).includes(value);
}

function isBasemap(value: string): value is BasemapId {
  return (BASEMAPS as readonly string[]).includes(value);
}

/** Parses a `location.hash` string (with or without the leading `#`) into a partial HashState. */
export function parseHash(hash: string): HashState {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash;
  const params = new URLSearchParams(raw);
  const result: HashState = {};

  const mode = params.get('mode');
  if (mode && isMode(mode)) result.mode = mode;

  const route = params.get('route');
  if (route) result.routeId = route;

  const sel = params.get('sel');
  if (sel) {
    const selection = selectionFromId(sel);
    if (selection) result.selection = selection;
  }

  const c = params.get('c');
  if (c) {
    const parts = c.split(',');
    if (parts.length === 2) {
      const lon = Number(parts[0]);
      const lat = Number(parts[1]);
      if (Number.isFinite(lon) && Number.isFinite(lat)) result.center = [lon, lat];
    }
  }

  const z = params.get('z');
  if (z) {
    const zoom = Number(z);
    if (Number.isFinite(zoom)) result.zoom = zoom;
  }

  const base = params.get('base');
  if (base && isBasemap(base)) result.basemap = base;

  const layers = params.get('layers');
  if (layers !== null) {
    const on = new Set(layers.split(',').filter(Boolean));
    const visibility = {} as LayerVisibility;
    for (const key of LAYER_KEYS) visibility[key] = on.has(key);
    result.layers = visibility;
  }

  return result;
}

/** Serializes a HashState back into a `#`-prefixed hash string, param order per §7.1. */
export function serializeHash(state: HashState): string {
  const params = new URLSearchParams();

  if (state.mode) params.set('mode', state.mode);
  if (state.routeId) params.set('route', state.routeId);
  if (state.selection) params.set('sel', state.selection.id);
  if (state.center) {
    const [lon, lat] = state.center;
    params.set('c', `${round(lon, 5)},${round(lat, 5)}`);
  }
  if (state.zoom !== undefined) params.set('z', String(round(state.zoom, 2)));
  if (state.basemap) params.set('base', state.basemap);
  if (state.layers) {
    const on = LAYER_KEYS.filter((key) => state.layers![key]);
    params.set('layers', on.join(','));
  }

  const query = params.toString();
  return query ? `#${query}` : '';
}

function round(n: number, decimals: number): number {
  const f = 10 ** decimals;
  return Math.round(n * f) / f;
}

// --- DOM wiring ----------------------------------------------------------------------------

export interface UrlSyncHandle {
  /** Call whenever the map's own viewport changes (e.g. on `moveend`); debounced into the hash. */
  notifyViewportChange(viewport: Viewport): void;
  /** Removes the hashchange listener. */
  destroy(): void;
}

/**
 * Reads the current `location.hash` once, synchronously, before any subscriptions are set up.
 * Use this at boot to seed the store and the map's initial viewport.
 */
export function readInitialHashState(): HashState {
  if (typeof location === 'undefined') return {};
  return parseHash(location.hash);
}

/**
 * Wires a store to `location.hash` two-way, debounced. Returns a handle for the map to report its
 * own viewport changes (since center/zoom live on the map, not in the AppState store).
 */
export function bindUrlSync(
  store: Store<AppState>,
  getViewport: () => Viewport,
  onExternalChange: (partial: Partial<AppState>, viewport: Viewport | null) => void,
  debounceMs = 300,
): UrlSyncHandle {
  let lastWritten = typeof location !== 'undefined' ? location.hash : '';
  let timer: ReturnType<typeof setTimeout> | undefined;

  function writeNow(): void {
    const app = store.getState();
    const next = serializeHash({
      mode: app.mode,
      routeId: app.routeId ?? undefined,
      selection: app.selection ?? undefined,
      center: getViewport().center,
      zoom: getViewport().zoom,
      basemap: app.basemap,
      layers: app.layers,
    });
    if (next === lastWritten) return;
    lastWritten = next;
    if (typeof history !== 'undefined' && typeof location !== 'undefined') {
      history.replaceState(null, '', next ? next : location.pathname + location.search);
    }
  }

  function scheduleWrite(): void {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(writeNow, debounceMs);
  }

  const unsubscribe = store.subscribe(() => scheduleWrite());

  function onHashChange(): void {
    if (typeof location === 'undefined') return;
    if (location.hash === lastWritten) return; // our own write echoing back
    lastWritten = location.hash;
    const parsed = parseHash(location.hash);
    const { center, zoom, ...appPartial } = parsed;
    onExternalChange(appPartial, center && zoom !== undefined ? { center, zoom } : null);
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('hashchange', onHashChange);
  }

  return {
    notifyViewportChange() {
      scheduleWrite();
    },
    destroy() {
      unsubscribe();
      if (timer !== undefined) clearTimeout(timer);
      if (typeof window !== 'undefined') {
        window.removeEventListener('hashchange', onHashChange);
      }
    },
  };
}
