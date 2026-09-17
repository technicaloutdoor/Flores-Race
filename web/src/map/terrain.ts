// Hillshade + optional 3D terrain, both from the AWS terrarium DEM tiles. Per ARCHITECTURE.md
// §7.2: hillshade is the everyday relief cue, 3D terrain is a toggle for stakeholder fly-throughs.

import type { Map as MapLibreMap } from 'maplibre-gl';
import { FIRST_DATA_LAYER_ID } from './layers.ts';

const TERRAIN_SOURCE_ID = 'terrain-dem';
export const HILLSHADE_LAYER_ID = 'hillshade';
const TERRAIN_EXAGGERATION = 1.3;

function ensureTerrainSource(map: MapLibreMap): void {
  if (map.getSource(TERRAIN_SOURCE_ID)) return;
  map.addSource(TERRAIN_SOURCE_ID, {
    type: 'raster-dem',
    tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
    encoding: 'terrarium',
    tileSize: 256,
    maxzoom: 15,
  });
}

export function setHillshadeVisible(map: MapLibreMap, visible: boolean): void {
  ensureTerrainSource(map);
  if (map.getLayer(HILLSHADE_LAYER_ID)) {
    map.setLayoutProperty(HILLSHADE_LAYER_ID, 'visibility', visible ? 'visible' : 'none');
    return;
  }
  const beforeId = map.getLayer(FIRST_DATA_LAYER_ID) ? FIRST_DATA_LAYER_ID : undefined;
  map.addLayer(
    {
      id: HILLSHADE_LAYER_ID,
      type: 'hillshade',
      source: TERRAIN_SOURCE_ID,
      layout: { visibility: visible ? 'visible' : 'none' },
      paint: { 'hillshade-exaggeration': 0.5 },
    },
    beforeId,
  );
}

/** Toggles MapLibre's 3D terrain (pitch the map to see it). */
export function setTerrain3D(map: MapLibreMap, enabled: boolean): void {
  if (!enabled) {
    map.setTerrain(null);
    return;
  }
  ensureTerrainSource(map);
  map.setTerrain({ source: TERRAIN_SOURCE_ID, exaggeration: TERRAIN_EXAGGERATION });
}
