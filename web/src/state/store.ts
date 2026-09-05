// Tiny typed reactive store: get / set / patch / subscribe. No framework, no magic.
//
// A `Store<T>` holds one immutable value of type T. Callers replace it wholesale (`set`) or
// shallow-merge a partial update (`patch`); every change notifies subscribers with the new and
// previous state. Consumers unsubscribe by calling the function `subscribe` returns.

export type Listener<T> = (state: T, previous: T) => void;
export type Unsubscribe = () => void;

export interface Store<T> {
  getState(): T;
  set(next: T): void;
  patch(partial: Partial<T>): void;
  subscribe(listener: Listener<T>): Unsubscribe;
}

/** Creates a store holding `initial`. `T` should be a plain, shallow-comparable object. */
export function createStore<T extends object>(initial: T): Store<T> {
  let state = initial;
  const listeners = new Set<Listener<T>>();

  return {
    getState() {
      return state;
    },
    set(next) {
      const previous = state;
      if (next === previous) return;
      state = next;
      for (const listener of listeners) listener(state, previous);
    },
    patch(partial) {
      const previous = state;
      const next = { ...previous, ...partial };
      state = next;
      for (const listener of listeners) listener(state, previous);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

// --- Application state -------------------------------------------------------------------

/** Who is looking at the app; drives which panels and layers show by default. */
export type Mode = 'stakeholder' | 'scout' | 'public';
export const MODES: readonly Mode[] = ['stakeholder', 'scout', 'public'];

/** Raster basemap choice. 'none' is a blank warm-paper ground for offline/sandbox use. */
export type BasemapId = 'topo' | 'satellite' | 'osm' | 'none';
export const BASEMAPS: readonly BasemapId[] = ['topo', 'satellite', 'osm', 'none'];

/** What kind of feature a selection id refers to; also the map layer it was clicked on. */
export type SelectionType = 'segment' | 'poi' | 'node';

export interface Selection {
  type: SelectionType;
  id: string;
}

/** Visibility of each togglable map layer. Independent of `mode`; mode only sets the initial mix. */
export interface LayerVisibility {
  network: boolean;
  segments: boolean;
  pois: boolean;
  nodes: boolean;
  regencies: boolean;
  hillshade: boolean;
  terrain3d: boolean;
}

export const LAYER_KEYS: readonly (keyof LayerVisibility)[] = [
  'network',
  'segments',
  'pois',
  'nodes',
  'regencies',
  'hillshade',
  'terrain3d',
];

export const DEFAULT_LAYERS: LayerVisibility = {
  network: false,
  segments: true,
  pois: true,
  nodes: true,
  regencies: true,
  hillshade: false,
  terrain3d: false,
};

export interface AppState {
  mode: Mode;
  routeId: string | null;
  selection: Selection | null;
  basemap: BasemapId;
  layers: LayerVisibility;
  /** Id of the feature currently hovered on the map, or null. Not persisted to the URL. */
  hoverId: string | null;
}

export const INITIAL_APP_STATE: AppState = {
  mode: 'stakeholder',
  routeId: null,
  selection: null,
  basemap: 'topo',
  layers: DEFAULT_LAYERS,
  hoverId: null,
};

/** The single app-wide store. Import this; do not create a second one. */
export const store: Store<AppState> = createStore(INITIAL_APP_STATE);

/** Infers a selection's feature type from its id prefix (`s-`, `p-`, `n-`). */
export function selectionTypeFromId(id: string): SelectionType | null {
  if (id.startsWith('s-')) return 'segment';
  if (id.startsWith('p-')) return 'poi';
  if (id.startsWith('n-')) return 'node';
  return null;
}

export function selectionFromId(id: string): Selection | null {
  const type = selectionTypeFromId(id);
  return type ? { type, id } : null;
}
