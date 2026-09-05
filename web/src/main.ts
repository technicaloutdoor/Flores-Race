// App shell: header controls, three content panels, and the map. This step wires the store, URL
// sync, data loading and map layers together; the panels themselves (route list, inspector,
// elevation profile) are filled in by the next step — for now they show simple placeholders that
// prove the wiring works. See ARCHITECTURE.md §7.

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
} from './state/store.ts';
import { readInitialHashState, bindUrlSync, DEFAULT_VIEWPORT, type Viewport } from './state/url.ts';
import { createMap } from './map/map.ts';
import { setBasemap } from './map/basemaps.ts';
import { setHillshadeVisible, setTerrain3D } from './map/terrain.ts';
import { MapLayers } from './map/layers.ts';
import { StaticFileStore } from './data/store.ts';
import { routeSegments, routeStats } from './data/derive.ts';
import { STATUS_META } from './data/types.ts';

// Status colours live in one place (data/types.ts); expose them as CSS variables so style.css
// never hardcodes a colour that could drift out of sync.
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
header.appendChild(labeledField('Mode', modeSelect));

const routeSelect = document.createElement('select');
routeSelect.appendChild(new Option('(no route)', ''));
header.appendChild(labeledField('Route', routeSelect));

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
for (const key of LAYER_KEYS) {
  const label = document.createElement('label');
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = DEFAULT_LAYERS[key];
  label.append(checkbox, document.createTextNode(LAYER_LABELS[key]));
  layerToggles.appendChild(label);
  layerCheckboxes.set(key, checkbox);
}
header.appendChild(layerToggles);

header.appendChild(Object.assign(document.createElement('div'), { className: 'header-spacer' }));

const shareButton = document.createElement('button');
shareButton.type = 'button';
shareButton.className = 'btn';
shareButton.textContent = 'Copy share link';
header.appendChild(shareButton);

const gpxButton = document.createElement('button');
gpxButton.type = 'button';
gpxButton.className = 'btn btn-accent';
gpxButton.textContent = 'Export GPX';
gpxButton.disabled = true;
gpxButton.title = 'GPX export lands in a later step';
header.appendChild(gpxButton);

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

const initialHash = readInitialHashState();
store.patch({
  mode: initialHash.mode ?? store.getState().mode,
  routeId: initialHash.routeId ?? store.getState().routeId,
  selection: initialHash.selection ?? store.getState().selection,
  basemap: initialHash.basemap ?? store.getState().basemap,
  layers: initialHash.layers ?? store.getState().layers,
});
const initialViewport: Viewport = {
  center: initialHash.center ?? DEFAULT_VIEWPORT.center,
  zoom: initialHash.zoom ?? DEFAULT_VIEWPORT.zoom,
};

/** Reflects store state onto the header controls. Needed both after the initial hash parse (the
 * controls above were built with hardcoded defaults) and on every later store change. */
function syncControls(state: AppState): void {
  if (modeSelect.value !== state.mode) modeSelect.value = state.mode;
  if (basemapSelect.value !== state.basemap) basemapSelect.value = state.basemap;
  if (routeSelect.value !== (state.routeId ?? '')) routeSelect.value = state.routeId ?? '';
  for (const [key, checkbox] of layerCheckboxes) checkbox.checked = state.layers[key];
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
});

map.on('moveend', () => urlHandle?.notifyViewportChange(floresMap.getViewport()));

function applyLayerState(layers: LayerVisibility): void {
  mapLayers?.applyVisibility(layers);
  setHillshadeVisible(map, layers.hillshade);
  setTerrain3D(map, layers.terrain3d);
}

// --- Panel rendering (placeholders — the next step replaces these) ---------------------------

function renderLeftPanel(): void {
  const state = store.getState();
  const routes = routeStore.getRoutes();
  panelLeft.replaceChildren();
  const h = document.createElement('h2');
  h.textContent = 'Routes & sections';
  const p = document.createElement('p');
  p.textContent = routes.length
    ? `${routes.length} route variant(s) loaded. Full section list and story arrive in the next step.`
    : 'Loading route bundle…';
  panelLeft.append(h, p);
  if (state.mode === 'public') {
    const note = document.createElement('p');
    note.textContent = 'Public mode: showing sections only.';
    panelLeft.appendChild(note);
  }
}

function renderRightPanel(): void {
  const state = store.getState();
  panelRight.replaceChildren();
  const h = document.createElement('h2');
  h.textContent = 'Selection';
  panelRight.appendChild(h);
  const p = document.createElement('p');
  if (!state.selection) {
    p.textContent = 'Nothing selected. Click a segment, node or POI on the map.';
  } else {
    const { type, id } = state.selection;
    p.textContent = `${type}: ${id}`;
    if (type === 'segment') {
      const segment = routeStore.getSegment(id);
      if (segment) {
        const meta = STATUS_META[segment.properties.status];
        const dot = document.createElement('span');
        dot.className = 'status-dot';
        dot.style.background = meta.color;
        const line = document.createElement('p');
        line.append(dot, document.createTextNode(`${segment.properties.name} — ${meta.label}`));
        panelRight.appendChild(p);
        panelRight.appendChild(line);
        return;
      }
    } else if (type === 'node') {
      const node = routeStore.getNode(id);
      if (node) p.textContent += ` — ${node.properties.name}`;
    } else if (type === 'poi') {
      const poi = routeStore.getPoi(id);
      if (poi) p.textContent += ` — ${poi.properties.name}`;
    }
  }
  panelRight.appendChild(p);
}

function renderBottomPanel(): void {
  const state = store.getState();
  panelBottom.replaceChildren();
  const h = document.createElement('h2');
  h.textContent = 'Elevation & progress';
  panelBottom.appendChild(h);
  const p = document.createElement('p');
  const route = state.routeId ? routeStore.getRoute(state.routeId) : undefined;
  if (!route) {
    p.textContent = 'Select a route to see its profile and stats (full elevation chart arrives next).';
  } else {
    const segmentFeatures = route.segments
      .map((id) => routeStore.getSegment(id))
      .filter((s): s is NonNullable<typeof s> => Boolean(s));
    const segments = routeSegments(route, segmentFeatures);
    const stats = routeStats(segments);
    p.textContent = `${route.name}: ${stats.length_km ?? 0} km, +${stats.ascent_m ?? 0} m, ${stats.hab_km} km hike-a-bike.`;
  }
  panelBottom.appendChild(p);
}

function renderPanels(): void {
  renderLeftPanel();
  renderRightPanel();
  renderBottomPanel();
}

// --- Bundle loading --------------------------------------------------------------------------

routeStore
  .loadAll()
  .then((bundle) => {
    floresMap.setAttribution(bundle.meta.attribution);
    routeSelect.replaceChildren(new Option('(no route)', ''));
    for (const route of bundle.routes) {
      routeSelect.appendChild(new Option(route.name, route.id));
    }
    if (store.getState().routeId) routeSelect.value = store.getState().routeId!;

    function drawData(): void {
      if (!mapLayers) return;
      mapLayers.addRegencies(bundle.regencies);
      mapLayers.addSegments(bundle.segments);
      mapLayers.addNodes(bundle.nodes);
      mapLayers.addPois(bundle.pois);
      applyLayerState(store.getState().layers);
      updateRouteMembership();
      mapLayers.setSelection(store.getState().selection);
    }

    if (mapLayers) drawData();
    else map.once('load', drawData);

    renderPanels();
  })
  .catch((err: unknown) => {
    console.error('Failed to load data bundle', err);
    panelLeft.textContent = 'Failed to load the data bundle — see console.';
  });

function updateRouteMembership(): void {
  if (!mapLayers) return;
  const state = store.getState();
  const route = state.routeId ? routeStore.getRoute(state.routeId) : undefined;
  const ids = new Set(route?.segments ?? []);
  mapLayers.setRouteMembership(ids);
}

// --- Wire header controls to the store --------------------------------------------------------

modeSelect.addEventListener('change', () => store.patch({ mode: modeSelect.value as Mode }));
routeSelect.addEventListener('change', () =>
  store.patch({ routeId: routeSelect.value || null }),
);
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

// --- Store subscription: the single place that reconciles UI + map to state --------------------

store.subscribe((state, previous) => {
  syncControls(state);

  if (state.basemap !== previous.basemap) setBasemap(map, state.basemap);
  if (state.layers !== previous.layers) {
    applyLayerState(state.layers);
    if (state.layers.network && !previous.layers.network) void ensureNetworkLoaded();
  }
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
