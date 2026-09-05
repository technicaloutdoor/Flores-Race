// App shell: header controls (mode, basemap, layers, search, story, share), the map, and the three
// content panels (sidebar / inspector / profile). See ARCHITECTURE.md §7.

import './style.css';
import type { Map as MapLibreMap } from 'maplibre-gl';
import {
  store,
  MODES,
  BASEMAPS,
  LAYER_KEYS,
  DEFAULT_LAYERS,
  type AppState,
  type Mode,
  type BasemapId,
  type LayerVisibility,
  type Selection,
} from './state/store.ts';
import { readInitialHashState, bindUrlSync, DEFAULT_VIEWPORT, type Viewport } from './state/url.ts';
import { createMap } from './map/map.ts';
import { setBasemap } from './map/basemaps.ts';
import { setHillshadeVisible, setTerrain3D } from './map/terrain.ts';
import { MapLayers } from './map/layers.ts';
import { flyToBbox, flyToPoint } from './map/fit.ts';
import { StaticFileStore, type Bundle } from './data/store.ts';
import { bboxOf } from './data/derive.ts';
import { STATUS_META, type SegmentFeature, type SegmentsGeoJSON } from './data/types.ts';
import { visibleNodes, visiblePois, visibleSegments } from './data/visibility.ts';
import { applyOverlayToSegment, overlayStore } from './state/overlay.ts';
import { buildSearchIndex, searchItems, type SearchItem } from './lib/search.ts';
import * as sidebar from './panels/sidebar.ts';
import * as inspector from './panels/inspector.ts';
import * as profile from './panels/profile.ts';
import { createPlayButton, isStoryAvailable } from './panels/story.ts';
import type { PanelContext } from './panels/context.ts';

for (const [status, meta] of Object.entries(STATUS_META)) {
  document.documentElement.style.setProperty(`--status-${status}`, meta.color);
}

const app = document.querySelector<HTMLDivElement>('#app');
if (!app) throw new Error('#app root element is missing from index.html');

// --- Header -------------------------------------------------------------------------------

const header = document.createElement('header');
header.className = 'app-header';

const title = document.createElement('h1');
title.textContent = 'Flores Race Planner';
header.appendChild(title);

function labeledField(labelText: string, control: HTMLElement): HTMLDivElement {
  const wrap = document.createElement('div');
  wrap.className = 'field-group';
  const label = document.createElement('label');
  label.textContent = labelText;
  const id = `field-${labelText.toLowerCase().replace(/\s+/g, '-')}`;
  label.htmlFor = id;
  control.id = id;
  wrap.append(label, control);
  return wrap;
}

const modeSelect = document.createElement('select');
for (const mode of MODES) {
  const opt = document.createElement('option');
  opt.value = mode;
  opt.textContent = mode[0]!.toUpperCase() + mode.slice(1);
  modeSelect.appendChild(opt);
}
const modeField = labeledField('Mode', modeSelect);
const modeInfo = document.createElement('span');
modeInfo.className = 'mode-info';
modeInfo.textContent = '?';
modeInfo.tabIndex = 0;
modeInfo.title =
  'Stakeholder: the vision, stats and stories. ' +
  'Scout: everything, plus the track network and the scouting form. ' +
  'Public: a teaser — sections only, no internal detail.';
modeField.appendChild(modeInfo);
header.appendChild(modeField);

const basemapSelect = document.createElement('select');
const BASEMAP_LABELS: Record<BasemapId, string> = {
  topo: 'Topographic',
  satellite: 'Satellite',
  osm: 'OpenStreetMap',
  none: 'None (offline)',
};
for (const id of BASEMAPS) {
  const opt = document.createElement('option');
  opt.value = id;
  opt.textContent = BASEMAP_LABELS[id];
  basemapSelect.appendChild(opt);
}
header.appendChild(labeledField('Basemap', basemapSelect));

const layerToggles = document.createElement('div');
layerToggles.className = 'layer-toggles';
const LAYER_LABELS: Record<keyof LayerVisibility, string> = {
  network: 'Network',
  segments: 'Segments',
  pois: 'POIs',
  nodes: 'Nodes',
  regencies: 'Regencies',
  hillshade: 'Hillshade',
  terrain3d: '3D terrain',
};
const layerCheckboxes = new Map<keyof LayerVisibility, HTMLInputElement>();
const layerLabels = new Map<keyof LayerVisibility, HTMLLabelElement>();
for (const key of LAYER_KEYS) {
  const label = document.createElement('label');
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = DEFAULT_LAYERS[key];
  label.append(checkbox, document.createTextNode(LAYER_LABELS[key]));
  layerToggles.appendChild(label);
  layerCheckboxes.set(key, checkbox);
  layerLabels.set(key, label);
}
header.appendChild(layerToggles);

// --- Header search box (nodes + POIs + segments by name; keyboard navigable) -----------------

const searchWrap = document.createElement('div');
searchWrap.className = 'search-wrap';
const searchInput = document.createElement('input');
searchInput.type = 'search';
searchInput.placeholder = 'Search…';
searchInput.setAttribute('aria-label', 'Search nodes, POIs and segments by name');
searchInput.setAttribute('role', 'combobox');
searchInput.setAttribute('aria-expanded', 'false');
const searchResults = document.createElement('ul');
searchResults.className = 'search-results';
searchResults.hidden = true;
searchWrap.append(searchInput, searchResults);
header.appendChild(searchWrap);

let fullSearchIndex: SearchItem[] = [];
let currentSearchResults: SearchItem[] = [];
let searchActiveIndex = -1;

function closeSearch(): void {
  searchResults.hidden = true;
  searchResults.replaceChildren();
  searchInput.setAttribute('aria-expanded', 'false');
  currentSearchResults = [];
  searchActiveIndex = -1;
}

function renderSearchResults(): void {
  searchResults.replaceChildren();
  searchResults.hidden = currentSearchResults.length === 0;
  searchInput.setAttribute('aria-expanded', String(currentSearchResults.length > 0));
  currentSearchResults.forEach((item, i) => {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.className = i === searchActiveIndex ? 'active' : '';
    li.setAttribute('aria-selected', String(i === searchActiveIndex));
    const label = document.createElement('span');
    label.textContent = item.label;
    const meta = document.createElement('span');
    meta.className = 'search-result-meta';
    meta.textContent = item.meta;
    li.append(label, meta);
    li.addEventListener('mousedown', (e) => {
      e.preventDefault(); // keep focus in the input so a later Escape still works
      selectSearchResult(item);
    });
    searchResults.appendChild(li);
  });
}

function coordForSearchItem(item: SearchItem): [number, number] | null {
  if (item.type === 'node') return (routeStore.getNode(item.id)?.geometry.coordinates as [number, number]) ?? null;
  if (item.type === 'poi') return (routeStore.getPoi(item.id)?.geometry.coordinates as [number, number]) ?? null;
  return null;
}

function selectSearchResult(item: SearchItem): void {
  store.patch({ selection: { type: item.type, id: item.id } });
  const coord = coordForSearchItem(item);
  if (coord) {
    flyToPoint(map, coord, { zoom: 13 });
  } else {
    const segment = resolvedSegmentsById.get(item.id);
    if (segment) flyToBbox(map, bboxOf([segment]), { padding: 80 });
  }
  searchInput.value = '';
  closeSearch();
}

searchInput.addEventListener('input', () => {
  const mode = store.getState().mode;
  const pool = mode === 'public' ? fullSearchIndex.filter((i) => i.public) : fullSearchIndex;
  currentSearchResults = searchItems(pool, searchInput.value);
  searchActiveIndex = currentSearchResults.length ? 0 : -1;
  renderSearchResults();
});
searchInput.addEventListener('keydown', (e) => {
  if (currentSearchResults.length === 0) return;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    searchActiveIndex = Math.min(searchActiveIndex + 1, currentSearchResults.length - 1);
    renderSearchResults();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    searchActiveIndex = Math.max(searchActiveIndex - 1, 0);
    renderSearchResults();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    const item = currentSearchResults[searchActiveIndex];
    if (item) selectSearchResult(item);
  } else if (e.key === 'Escape') {
    closeSearch();
  }
});
searchInput.addEventListener('blur', () => setTimeout(closeSearch, 150));

header.appendChild(Object.assign(document.createElement('div'), { className: 'header-spacer' }));

// `panelContext` is declared (as a hoisted `function`) further down this file, but is only ever
// *called* later, from this button's click handler — by then the whole module has finished
// initialising, so the forward reference is safe.
const storyButton = createPlayButton(() => panelContext());
header.appendChild(storyButton);

const shareButton = document.createElement('button');
shareButton.type = 'button';
shareButton.className = 'btn';
shareButton.textContent = 'Copy share link';
header.appendChild(shareButton);

app.appendChild(header);

// --- Map + panels ---------------------------------------------------------------------------

const mapContainer = document.createElement('div');
mapContainer.id = 'map';
app.appendChild(mapContainer);

const panelLeft = document.createElement('div');
panelLeft.id = 'panel-left';
panelLeft.className = 'panel';
app.appendChild(panelLeft);

const panelRight = document.createElement('div');
panelRight.id = 'panel-right';
panelRight.className = 'panel';
app.appendChild(panelRight);

const panelBottom = document.createElement('div');
panelBottom.id = 'panel-bottom';
panelBottom.className = 'panel';
app.appendChild(panelBottom);

// Narrow-viewport bottom sheet: the same three panels, tabbed instead of side-by-side (CSS moves
// them into one grid area below 800px; here we just show one at a time and track which).
const sheetTabs = document.createElement('div');
sheetTabs.className = 'sheet-tabs';
sheetTabs.setAttribute('role', 'tablist');
const TABS: Array<{ id: string; label: string; panel: HTMLElement }> = [
  { id: 'routes', label: 'Routes', panel: panelLeft },
  { id: 'selection', label: 'Selection', panel: panelRight },
  { id: 'profile', label: 'Profile', panel: panelBottom },
];
let activeTab = TABS[0]!.id;

function renderTabs(): void {
  const isCompact = window.matchMedia('(max-width: 800px)').matches;
  sheetTabs.replaceChildren();
  for (const tab of TABS) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = tab.label;
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-selected', String(tab.id === activeTab));
    button.addEventListener('click', () => {
      activeTab = tab.id;
      renderTabs();
    });
    sheetTabs.appendChild(button);
  }
  for (const tab of TABS) {
    tab.panel.hidden = isCompact && tab.id !== activeTab;
  }
}
app.appendChild(sheetTabs);
renderTabs();
window.matchMedia('(max-width: 800px)').addEventListener('change', renderTabs);

// --- Data store + map ------------------------------------------------------------------------

const routeStore = new StaticFileStore();
let bundle: Bundle | undefined;

/** Resolves at zoom > 10 network default (BRIEF §6: "scout mode defaults network on above zoom 10")
 * and forces the network layer off in public mode (it's hidden there, not just off by default). */
function defaultLayersForMode(mode: Mode, zoom: number): LayerVisibility {
  const layers: LayerVisibility = { ...DEFAULT_LAYERS };
  if (mode === 'scout') layers.network = zoom > 10;
  if (mode === 'public') layers.network = false;
  return layers;
}

const initialHash = readInitialHashState();
const initialViewport: Viewport = {
  center: initialHash.center ?? DEFAULT_VIEWPORT.center,
  zoom: initialHash.zoom ?? DEFAULT_VIEWPORT.zoom,
};
const initialMode = initialHash.mode ?? store.getState().mode;
store.patch({
  mode: initialMode,
  routeId: initialHash.routeId ?? store.getState().routeId,
  selection: initialHash.selection ?? store.getState().selection,
  basemap: initialHash.basemap ?? (initialMode === 'scout' ? 'topo' : store.getState().basemap),
  layers: initialHash.layers ?? defaultLayersForMode(initialMode, initialViewport.zoom),
});

/** Reflects store state onto the header controls. Needed both after the initial hash parse (the
 * controls above were built with hardcoded defaults) and on every later store change. */
function syncControls(state: AppState): void {
  if (modeSelect.value !== state.mode) modeSelect.value = state.mode;
  if (basemapSelect.value !== state.basemap) basemapSelect.value = state.basemap;
  for (const [key, checkbox] of layerCheckboxes) checkbox.checked = state.layers[key];
  const networkLabel = layerLabels.get('network');
  if (networkLabel) networkLabel.hidden = state.mode === 'public';

  storyButton.hidden = !isStoryAvailable(state.mode);
}
syncControls(store.getState());

let urlHandle: ReturnType<typeof bindUrlSync> | undefined;

const floresMap = createMap({ container: mapContainer, viewport: initialViewport });
const map: MapLibreMap = floresMap.map;

window.__mapIdle = new Promise<void>((resolve) => {
  map.once('idle', () => resolve());
});

let mapLayers: MapLayers | undefined;
const networkNote = document.createElement('div');
networkNote.id = 'network-note';
networkNote.hidden = true;

function showNetworkNote(note: string): void {
  networkNote.textContent = note;
  networkNote.hidden = false;
}

async function ensureNetworkLoaded(): Promise<void> {
  const result = await routeStore.loadNetwork();
  mapLayers?.setNetwork(result.data);
  if (result.note) showNetworkNote(result.note);
  else networkNote.hidden = true;
}

map.on('load', () => {
  mapContainer.appendChild(networkNote);
  setBasemap(map, store.getState().basemap);
  mapLayers = new MapLayers(map);
  mapLayers.bindInteractions({
    onHover: (id) => {
      store.patch({ hoverId: id });
      mapLayers?.setHover(id);
    },
    onSelect: (selection) => store.patch({ selection }),
  });
  applyLayerState(store.getState().layers);
  if (store.getState().layers.network) void ensureNetworkLoaded();
  if (bundle) drawData();
});

map.on('moveend', () => urlHandle?.notifyViewportChange(floresMap.getViewport()));

function applyLayerState(layers: LayerVisibility): void {
  mapLayers?.applyVisibility(layers);
  setHillshadeVisible(map, layers.hillshade);
  setTerrain3D(map, layers.terrain3d);
}

// --- Segment overlay resolution (state/overlay.ts applied on top of the bundle) ---------------

let resolvedSegmentsById = new Map<string, SegmentFeature>();

function recomputeResolvedSegments(): void {
  if (!bundle) return;
  const overlay = overlayStore.getState();
  resolvedSegmentsById = new Map(
    bundle.segments.features.map((f) => [
      f.properties.id,
      applyOverlayToSegment(f, overlay.segments[f.properties.id]),
    ]),
  );
}

function panelContext(): PanelContext {
  return {
    state: store.getState(),
    routeStore,
    bundleLoaded: Boolean(bundle),
    map,
    mapLayers,
    actions: {
      select: (selection: Selection | null) => store.patch({ selection }),
      setRoute: (routeId: string | null) => store.patch({ routeId }),
      setLayer: (key, value) => store.patch({ layers: { ...store.getState().layers, [key]: value } }),
    },
    getSegment: (id) => resolvedSegmentsById.get(id),
    getAllSegments: () => [...resolvedSegmentsById.values()],
  };
}

// --- Panel rendering -------------------------------------------------------------------------

function renderPanels(): void {
  const ctx = panelContext();
  sidebar.render(panelLeft, ctx);
  inspector.render(panelRight, ctx);
  profile.render(panelBottom, ctx);
}

// --- Map data (segments/nodes/pois filtered for the current mode, overlay-applied) ------------

function segmentsGeoJSONFor(mode: Mode): SegmentsGeoJSON {
  if (!bundle) return { type: 'FeatureCollection', features: [] };
  const features = visibleSegments(bundle, mode).map((f) => resolvedSegmentsById.get(f.properties.id) ?? f);
  return { type: 'FeatureCollection', features };
}

function drawData(): void {
  if (!mapLayers || !bundle) return;
  const mode = store.getState().mode;
  mapLayers.addRegencies(bundle.regencies);
  mapLayers.addSegments(segmentsGeoJSONFor(mode));
  mapLayers.addNodes({ type: 'FeatureCollection', features: visibleNodes(bundle, mode) });
  mapLayers.addPois({ type: 'FeatureCollection', features: visiblePois(bundle, mode) });
  applyLayerState(store.getState().layers);
  updateRouteMembership();
  mapLayers.setSelection(store.getState().selection);
}

function updateRouteMembership(): void {
  if (!mapLayers) return;
  const state = store.getState();
  const route = state.routeId ? routeStore.getRoute(state.routeId) : undefined;
  const ids = new Set(route?.segments ?? []);
  mapLayers.setRouteMembership(ids);
}

// --- Bundle loading --------------------------------------------------------------------------

routeStore
  .loadAll()
  .then((loaded) => {
    bundle = loaded;
    recomputeResolvedSegments();
    fullSearchIndex = buildSearchIndex(loaded);
    floresMap.setAttribution(loaded.meta.attribution);

    if (mapLayers) drawData();
    renderPanels();
  })
  .catch((err: unknown) => {
    console.error('Failed to load data bundle', err);
    panelLeft.replaceChildren();
    const h = document.createElement('h2');
    h.textContent = 'Routes & sections';
    const p = document.createElement('p');
    p.className = 'state state-error';
    p.textContent = 'Failed to load the data bundle — see console.';
    panelLeft.append(h, p);
  });

// --- Wire header controls to the store --------------------------------------------------------

modeSelect.addEventListener('change', () => {
  const mode = modeSelect.value as Mode;
  store.patch({
    mode,
    layers: defaultLayersForMode(mode, map.getZoom()),
    basemap: mode === 'scout' ? 'topo' : store.getState().basemap,
  });
});
basemapSelect.addEventListener('change', () =>
  store.patch({ basemap: basemapSelect.value as BasemapId }),
);
for (const [key, checkbox] of layerCheckboxes) {
  checkbox.addEventListener('change', () => {
    store.patch({ layers: { ...store.getState().layers, [key]: checkbox.checked } });
  });
}

shareButton.addEventListener('click', () => {
  void navigator.clipboard?.writeText(location.href).then(
    () => {
      shareButton.textContent = 'Link copied!';
      setTimeout(() => (shareButton.textContent = 'Copy share link'), 1500);
    },
    () => {
      shareButton.textContent = 'Copy failed';
      setTimeout(() => (shareButton.textContent = 'Copy share link'), 1500);
    },
  );
});

// --- Store subscriptions: the single place that reconciles UI + map to state -------------------

overlayStore.subscribe(() => {
  recomputeResolvedSegments();
  if (mapLayers && bundle) mapLayers.addSegments(segmentsGeoJSONFor(store.getState().mode));
  renderPanels();
});

store.subscribe((state, previous) => {
  syncControls(state);

  if (state.basemap !== previous.basemap) setBasemap(map, state.basemap);
  if (state.layers !== previous.layers) {
    applyLayerState(state.layers);
    if (state.layers.network && !previous.layers.network) void ensureNetworkLoaded();
  }
  if (state.mode !== previous.mode && bundle) drawData(); // mode changes which features are visible
  if (state.routeId !== previous.routeId) updateRouteMembership();
  if (state.selection !== previous.selection) mapLayers?.setSelection(state.selection);

  renderPanels();
});

urlHandle = bindUrlSync(
  store,
  () => floresMap.getViewport(),
  (partial, viewport) => {
    store.patch(partial);
    if (viewport) map.jumpTo({ center: viewport.center, zoom: viewport.zoom });
  },
);

renderPanels();
