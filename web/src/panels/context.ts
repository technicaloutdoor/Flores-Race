// The object every panel render function receives. Centralising it here means main.ts (the only
// place that owns the map, the store and the loaded bundle) can hand each panel exactly what it
// needs without the panels importing each other or reaching into main.ts's module scope.

import type { Map as MapLibreMap } from 'maplibre-gl';
import type { RouteStore } from '../data/store.ts';
import type { SegmentFeature } from '../data/types.ts';
import type { AppState, LayerVisibility, Selection } from '../state/store.ts';
import type { MapLayers } from '../map/layers.ts';

export interface PanelActions {
  select(selection: Selection | null): void;
  setRoute(routeId: string | null): void;
  setLayer(key: keyof LayerVisibility, value: boolean): void;
}

export interface PanelContext {
  state: AppState;
  routeStore: RouteStore;
  /** Undefined until the bundle has finished its first load. */
  bundleLoaded: boolean;
  map: MapLibreMap;
  /** Undefined until the map has fired its first 'load' (mirrors main.ts's own `mapLayers`). */
  mapLayers: MapLayers | undefined;
  actions: PanelActions;
  /**
   * A segment's canonical properties merged with any local scouting overlay (state/overlay.ts) for
   * this id — every panel that displays or edits a segment reads through this, never
   * `routeStore.getSegment` directly, so a local edit shows up consistently everywhere (map colour,
   * stats, inspector, GPX export) until it's exported or discarded.
   */
  getSegment(id: string): SegmentFeature | undefined;
  /** Every segment in the bundle, overlay-applied — for sibling-variant lookups and route/section
   * GPX export. */
  getAllSegments(): SegmentFeature[];
}
