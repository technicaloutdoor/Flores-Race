// Raster basemap sources. Free public tile services, no API keys, per ARCHITECTURE.md §7.2 and
// ADR-0003. 'none' shows a blank warm-paper background instead (with the regencies polygon, from
// layers.ts, filled sand/ochre so the island still reads without any tiles) — this is what the
// screenshot tool and this build sandbox use, since tile servers are blocked outbound here.

import type { Map as MapLibreMap } from 'maplibre-gl';
import type { BasemapId } from '../state/store.ts';
import { FIRST_DATA_LAYER_ID } from './layers.ts';

interface RasterBasemapDef {
  sourceId: string;
  layerId: string;
  tiles: string[];
  tileSize: number;
  maxzoom: number;
  attribution: string;
}

const TOPO: RasterBasemapDef = {
  sourceId: 'basemap-topo',
  layerId: 'basemap-topo-layer',
  tiles: [
    'https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
    'https://b.tile.opentopomap.org/{z}/{x}/{y}.png',
    'https://c.tile.opentopomap.org/{z}/{x}/{y}.png',
  ],
  tileSize: 256,
  maxzoom: 17,
  attribution: 'Map data: © OpenTopoMap (CC-BY-SA), © OpenStreetMap contributors',
};

const SATELLITE: RasterBasemapDef = {
  sourceId: 'basemap-satellite',
  layerId: 'basemap-satellite-layer',
  tiles: [
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  ],
  tileSize: 256,
  maxzoom: 18,
  attribution: 'Esri, Maxar, Earthstar Geographics',
};

const OSM: RasterBasemapDef = {
  sourceId: 'basemap-osm',
  layerId: 'basemap-osm-layer',
  tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
  tileSize: 256,
  maxzoom: 19,
  attribution: '© OpenStreetMap contributors',
};

const RASTER_BASEMAPS: Record<Exclude<BasemapId, 'none'>, RasterBasemapDef> = {
  topo: TOPO,
  satellite: SATELLITE,
  osm: OSM,
};

const BACKGROUND_LAYER_ID = 'basemap-none-background';

function ensureBackgroundLayer(map: MapLibreMap): void {
  if (map.getLayer(BACKGROUND_LAYER_ID)) return;
  map.addLayer({
    id: BACKGROUND_LAYER_ID,
    type: 'background',
    paint: { 'background-color': '#f4ecd8' }, // warm paper
  });
}

/** Switches the active raster basemap (or shows the blank background for 'none'). Removing and
 * re-adding the raster source/layer each time keeps this simple; basemap switches are a rare user
 * action, not a hot path worth optimising. */
export function setBasemap(map: MapLibreMap, id: BasemapId): void {
  ensureBackgroundLayer(map);

  for (const def of Object.values(RASTER_BASEMAPS)) {
    if (map.getLayer(def.layerId)) map.removeLayer(def.layerId);
    if (map.getSource(def.sourceId)) map.removeSource(def.sourceId);
  }

  map.setLayoutProperty(BACKGROUND_LAYER_ID, 'visibility', id === 'none' ? 'visible' : 'none');
  if (id === 'none') return;

  const def = RASTER_BASEMAPS[id];
  const beforeId = map.getLayer(FIRST_DATA_LAYER_ID) ? FIRST_DATA_LAYER_ID : undefined;
  map.addSource(def.sourceId, {
    type: 'raster',
    tiles: def.tiles,
    tileSize: def.tileSize,
    maxzoom: def.maxzoom,
    attribution: def.attribution,
  });
  map.addLayer({ id: def.layerId, type: 'raster', source: def.sourceId }, beforeId);
}
