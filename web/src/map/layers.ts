// GeoJSON sources and layers for our own data: regencies, the track network, candidate segments,
// nodes and POIs, plus the cumulative-km markers. Styling follows ARCHITECTURE.md §7.2 (bottom to
// top) and the STATUS_META / POI_CATEGORY_META tables in data/types.ts so colours stay in one place.
//
// Icons are drawn on a <canvas> and registered with `map.addImage` — no icon font, no sprite sheet
// to build. `text-font` still references the demo glyphs ('Open Sans Semibold'); those PBFs are
// blocked in this build sandbox (see BRIEF, and map.ts's GLYPHS_URL comment) — not a bug to chase.
// MapLibre's local-glyph fallback still draws the labels here, just with a substituted font.

import type {
  FeatureCollection,
  LineString,
  Point,
} from 'geojson';
import type { GeoJSONSource, Map as MapLibreMap, MapGeoJSONFeature } from 'maplibre-gl';
import { POI_CATEGORY_META, STATUS_META, type POICategory } from '../data/types.ts';
import type { NodesGeoJSON, POIsGeoJSON, SegmentsGeoJSON } from '../data/types.ts';
import type { NetworkGeoJSON, RegenciesGeoJSON } from '../data/store.ts';
import type { KmMarker } from '../data/derive.ts';
import { selectionTypeFromId, type LayerVisibility, type Selection } from '../state/store.ts';

/** MapLibre's style-spec types model every paint/layout expression as a big literal union; hand
 * building expressions dynamically (one `match` arm per status/category, from data we don't know
 * at compile time) isn't worth fighting that union for. This alias documents the escape hatch. */
type MapLibreExpr = any; // eslint-disable-line @typescript-eslint/no-explicit-any

const SOURCE = {
  regencies: 'src-regencies',
  network: 'src-network',
  segments: 'src-segments',
  nodes: 'src-nodes',
  pois: 'src-pois',
  kmMarkers: 'src-km-markers',
  gpxImport: 'src-gpx-import',
  hoverMarker: 'src-hover-marker',
} as const;

const LAYER = {
  regenciesFill: 'regencies-fill',
  regenciesLine: 'regencies-line',
  network: 'network-line',
  segmentsCasing: 'segments-casing',
  segmentsCompare: 'segments-compare',
  segmentsSolid: 'segments-line-solid',
  segmentsDashed: 'segments-line-dashed',
  nodesHighlight: 'nodes-highlight',
  nodesIcon: 'nodes-icon',
  nodesLabel: 'nodes-label',
  poisHighlight: 'pois-highlight',
  poisHazardRing: 'pois-hazard-ring',
  poisIcon: 'pois-icon',
  poisLabel: 'pois-label',
  kmMarkers: 'km-markers',
  gpxImport: 'gpx-import-line',
  hoverMarker: 'hover-marker',
} as const;

/** The first data layer added, above the basemap. `basemaps.ts` and `terrain.ts` insert their own
 * raster layers just below this one so the draw order stays basemap → terrain → our data. */
export const FIRST_DATA_LAYER_ID = LAYER.regenciesFill;

const INTERACTIVE_LAYERS = [
  LAYER.segmentsSolid,
  LAYER.segmentsDashed,
  LAYER.nodesIcon,
  LAYER.poisIcon,
] as const;

/** Circle paint for the highlight drawn under a node/POI icon. `feature-state` only works in
 * `paint` properties (not `layout`), which is why this is a separate circle layer rather than a
 * data-driven `icon-size`. */
function selectionHighlightPaint(): Record<string, unknown> {
  return {
    'circle-radius': [
      'case',
      ['boolean', ['feature-state', 'selected'], false],
      13,
      ['boolean', ['feature-state', 'hover'], false],
      10,
      0,
    ] as MapLibreExpr,
    'circle-color': '#e8632b',
    'circle-opacity': 0.3,
  };
}

/** Colour for the hazard ring drawn under any POI with a `hazard_level` (an active volcano, an
 * exclusion zone, etc.) -- see `HAZARD_RING_FILTER`. Kept separate from `POI_CATEGORY_META`'s
 * per-category colours: a POI's category (`volcano`, `crater-lake`, ...) drives its icon glyph,
 * but hazard severity is a different, cross-cutting concern that must stay visible regardless of
 * which category a POI author happened to pick (docs/route-concept.md's Lewotobi entry is
 * category `volcano`, not `hazard`, and must look just as urgent as one that is). */
const HAZARD_RING_COLOR = '#c0392b';

/** Matches any POI carrying a non-empty `hazard_level`, independent of its `category`. */
const HAZARD_RING_FILTER: MapLibreExpr = ['all', ['has', 'hazard_level'], ['!=', ['get', 'hazard_level'], '']];

function statusColorExpression(): unknown[] {
  const expr: unknown[] = ['match', ['get', 'status']];
  for (const [status, meta] of Object.entries(STATUS_META)) {
    expr.push(status, meta.color);
  }
  expr.push('#9aa0a6'); // fallback
  return expr;
}

// --- Canvas-drawn icons ---------------------------------------------------------------------

/** One or two letters standing in for a POI category's icon (no icon font/sprite sheet — see file
 * header). Exported so the sidebar legend can draw the same swatch the map uses. */
export function categoryInitials(iconKey: string): string {
  const letters = iconKey
    .split('-')
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
  return letters.slice(0, 2) || '?';
}

function drawCircleGlyph(label: string, fill: string): ImageData {
  const size = 24;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return new ImageData(size, size);

  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2 - 1.5, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.strokeStyle = '#241a12';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  ctx.fillStyle = '#fbf4e6';
  ctx.font = `700 ${Math.round(size * 0.4)}px Inter, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, size / 2, size / 2 + 1);

  return ctx.getImageData(0, 0, size, size);
}

function drawDiamondGlyph(fill: string): ImageData {
  const size = 22;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return new ImageData(size, size);

  ctx.save();
  ctx.translate(size / 2, size / 2);
  ctx.rotate(Math.PI / 4);
  const half = size / 2 - 3;
  ctx.fillStyle = fill;
  ctx.strokeStyle = '#241a12';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.rect(-half, -half, half * 2, half * 2);
  ctx.fill();
  ctx.stroke();
  ctx.restore();

  return ctx.getImageData(0, 0, size, size);
}

const NODE_ICON_ID = 'icon-node-diamond';
function poiIconId(category: POICategory): string {
  return `icon-poi-${category}`;
}

function ensureImage(map: MapLibreMap, id: string, draw: () => ImageData): void {
  if (map.hasImage(id)) return;
  map.addImage(id, draw());
}

function markersToGeoJSON(markers: KmMarker[]): FeatureCollection<Point, { km: number }> {
  return {
    type: 'FeatureCollection',
    features: markers.map((m) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: m.coord },
      properties: { km: m.km },
    })),
  };
}

/** Owns every source/layer we draw on top of the basemap, and the selection/hover feature-state
 * that styling reacts to. One instance per map. */
export class MapLayers {
  private allSegmentIds: string[] = [];

  constructor(private readonly map: MapLibreMap) {}

  addRegencies(data: RegenciesGeoJSON): void {
    const existing = this.map.getSource(SOURCE.regencies);
    if (existing && 'setData' in existing) {
      (existing as GeoJSONSource).setData(data);
      return;
    }
    this.map.addSource(SOURCE.regencies, { type: 'geojson', data });
    this.map.addLayer({
      id: LAYER.regenciesFill,
      type: 'fill',
      source: SOURCE.regencies,
      paint: { 'fill-color': '#c9a45c', 'fill-opacity': 0.16 },
    });
    this.map.addLayer({
      id: LAYER.regenciesLine,
      type: 'line',
      source: SOURCE.regencies,
      paint: { 'line-color': '#8a6d3b', 'line-width': 1, 'line-opacity': 0.55 },
    });
  }

  setNetwork(data: NetworkGeoJSON | null): void {
    if (!data) return;
    const existing = this.map.getSource(SOURCE.network);
    if (existing && 'setData' in existing) {
      (existing as GeoJSONSource).setData(data);
      return;
    }
    this.map.addSource(SOURCE.network, { type: 'geojson', data });
    this.map.addLayer(
      {
        id: LAYER.network,
        type: 'line',
        source: SOURCE.network,
        minzoom: 9,
        paint: {
          'line-color': [
            'match',
            ['get', 'surface'],
            'paved',
            '#9a8f7e',
            '#a97c50',
          ] as MapLibreExpr,
          'line-width': 1,
          'line-opacity': 0.55,
        },
      },
      this.map.getLayer(LAYER.segmentsCasing) ? LAYER.segmentsCasing : undefined,
    );
  }

  addSegments(data: SegmentsGeoJSON): void {
    this.allSegmentIds = data.features.map((f) => f.properties.id);
    const existing = this.map.getSource(SOURCE.segments);
    if (existing && 'setData' in existing) {
      (existing as GeoJSONSource).setData(data);
      return;
    }
    this.map.addSource(SOURCE.segments, { type: 'geojson', data, promoteId: 'id' });

    // A wide, translucent casing shown only under the selected segment.
    this.map.addLayer({
      id: LAYER.segmentsCasing,
      type: 'line',
      source: SOURCE.segments,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#e8632b',
        'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 11, 0],
        'line-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 0.3, 0],
      },
    });

    const widthExpr = ['case', ['boolean', ['feature-state', 'inRoute'], true], 4, 2];
    const opacityExpr = ['case', ['boolean', ['feature-state', 'inRoute'], true], 1, 0.4];

    this.map.addLayer({
      id: LAYER.segmentsSolid,
      type: 'line',
      source: SOURCE.segments,
      filter: ['!=', ['get', 'status'], 'concept'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': statusColorExpression() as MapLibreExpr,
        'line-width': widthExpr as MapLibreExpr,
        'line-opacity': opacityExpr as MapLibreExpr,
      },
    });
    this.map.addLayer({
      id: LAYER.segmentsDashed,
      type: 'line',
      source: SOURCE.segments,
      filter: ['==', ['get', 'status'], 'concept'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': statusColorExpression() as MapLibreExpr,
        'line-width': widthExpr as MapLibreExpr,
        'line-opacity': opacityExpr as MapLibreExpr,
        'line-dasharray': [2, 1.6],
      },
    });

    // Sibling-variant "compare" highlight (inspector: scout mode). A separate casing so it can
    // coexist with the orange selection casing without either one overriding the other's colour.
    this.map.addLayer(
      {
        id: LAYER.segmentsCompare,
        type: 'line',
        source: SOURCE.segments,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': '#39c2d1',
          'line-width': ['case', ['boolean', ['feature-state', 'compare'], false], 8, 0],
          'line-opacity': ['case', ['boolean', ['feature-state', 'compare'], false], 0.55, 0],
        },
      },
      LAYER.segmentsSolid,
    );
  }

  addNodes(data: NodesGeoJSON): void {
    ensureImage(this.map, NODE_ICON_ID, () => drawDiamondGlyph('#e8632b'));
    const existing = this.map.getSource(SOURCE.nodes);
    if (existing && 'setData' in existing) {
      (existing as GeoJSONSource).setData(data);
      return;
    }
    this.map.addSource(SOURCE.nodes, { type: 'geojson', data, promoteId: 'id' });
    // A circle drawn under the icon, sized by feature-state — `icon-size` is a layout property and
    // layout properties can't read feature-state, so selection/hover emphasis has to live in paint.
    this.map.addLayer({
      id: LAYER.nodesHighlight,
      type: 'circle',
      source: SOURCE.nodes,
      paint: selectionHighlightPaint(),
    });
    this.map.addLayer({
      id: LAYER.nodesIcon,
      type: 'symbol',
      source: SOURCE.nodes,
      layout: {
        'icon-image': NODE_ICON_ID,
        'icon-size': 1,
        'icon-allow-overlap': true,
      },
    });
    this.map.addLayer({
      id: LAYER.nodesLabel,
      type: 'symbol',
      source: SOURCE.nodes,
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['Open Sans Semibold'],
        'text-size': 11,
        'text-offset': [0, 1.1],
        'text-anchor': 'top',
        'text-optional': true,
      },
      paint: {
        'text-color': '#241a12',
        'text-halo-color': '#f4ecd8',
        'text-halo-width': 1.2,
      },
    });
  }

  addPois(data: POIsGeoJSON): void {
    for (const [category, meta] of Object.entries(POI_CATEGORY_META)) {
      ensureImage(this.map, poiIconId(category as POICategory), () =>
        drawCircleGlyph(categoryInitials(meta.icon), '#4a6b57'),
      );
    }
    const existing = this.map.getSource(SOURCE.pois);
    if (existing && 'setData' in existing) {
      (existing as GeoJSONSource).setData(data);
      return;
    }
    this.map.addSource(SOURCE.pois, { type: 'geojson', data, promoteId: 'id' });
    this.map.addLayer({
      id: LAYER.poisHighlight,
      type: 'circle',
      source: SOURCE.pois,
      paint: selectionHighlightPaint(),
    });
    // A hazard's urgency must read from colour, not from the 1-2 letter icon glyph alone (which
    // looks identical whether the category is 'hazard' or 'volcano') -- see HAZARD_RING_COLOR.
    this.map.addLayer({
      id: LAYER.poisHazardRing,
      type: 'circle',
      source: SOURCE.pois,
      filter: HAZARD_RING_FILTER,
      paint: {
        'circle-radius': 11,
        'circle-color': HAZARD_RING_COLOR,
        'circle-opacity': 0.28,
        'circle-stroke-width': 1.5,
        'circle-stroke-color': HAZARD_RING_COLOR,
        'circle-stroke-opacity': 0.9,
      },
    });
    this.map.addLayer({
      id: LAYER.poisIcon,
      type: 'symbol',
      source: SOURCE.pois,
      layout: {
        'icon-image': ['concat', 'icon-poi-', ['get', 'category']],
        'icon-size': 0.9,
        'icon-allow-overlap': true,
      },
    });
    this.map.addLayer({
      id: LAYER.poisLabel,
      type: 'symbol',
      source: SOURCE.pois,
      minzoom: 9,
      layout: {
        'text-field': ['get', 'name'],
        'text-font': ['Open Sans Semibold'],
        'text-size': 11,
        'text-offset': [0, 1],
        'text-anchor': 'top',
        'text-optional': true,
      },
      paint: {
        'text-color': '#241a12',
        'text-halo-color': '#f4ecd8',
        'text-halo-width': 1.2,
      },
    });
  }

  setKmMarkers(markers: KmMarker[]): void {
    const data = markersToGeoJSON(markers);
    const existing = this.map.getSource(SOURCE.kmMarkers);
    if (existing && 'setData' in existing) {
      (existing as GeoJSONSource).setData(data);
      return;
    }
    this.map.addSource(SOURCE.kmMarkers, { type: 'geojson', data });
    this.map.addLayer({
      id: LAYER.kmMarkers,
      type: 'symbol',
      source: SOURCE.kmMarkers,
      layout: {
        'text-field': ['concat', ['to-string', ['get', 'km']], ' km'],
        'text-font': ['Open Sans Semibold'],
        'text-size': 10,
      },
      paint: {
        'text-color': '#4a3728',
        'text-halo-color': '#f4ecd8',
        'text-halo-width': 1.5,
      },
    });
  }

  applyVisibility(layers: LayerVisibility): void {
    this.setVisible(LAYER.regenciesFill, layers.regencies);
    this.setVisible(LAYER.regenciesLine, layers.regencies);
    this.setVisible(LAYER.network, layers.network);
    this.setVisible(LAYER.segmentsCasing, layers.segments);
    this.setVisible(LAYER.segmentsSolid, layers.segments);
    this.setVisible(LAYER.segmentsDashed, layers.segments);
    this.setVisible(LAYER.kmMarkers, layers.segments);
    this.setVisible(LAYER.nodesHighlight, layers.nodes);
    this.setVisible(LAYER.nodesIcon, layers.nodes);
    this.setVisible(LAYER.nodesLabel, layers.nodes);
    this.setVisible(LAYER.poisHighlight, layers.pois);
    this.setVisible(LAYER.poisHazardRing, layers.pois);
    this.setVisible(LAYER.poisIcon, layers.pois);
    this.setVisible(LAYER.poisLabel, layers.pois);
  }

  /** Marks which segments belong to the currently selected route (styled wider/opaque); all
   * others fade. Call with an empty set to clear (e.g. no route selected). */
  setRouteMembership(routeSegmentIds: ReadonlySet<string>): void {
    for (const id of this.allSegmentIds) {
      this.map.setFeatureState({ source: SOURCE.segments, id }, { inRoute: routeSegmentIds.has(id) });
    }
  }

  private lastSelected: Selection | null = null;

  setSelection(selection: Selection | null): void {
    if (this.lastSelected) {
      this.map.setFeatureState(
        { source: sourceForType(this.lastSelected.type), id: this.lastSelected.id },
        { selected: false },
      );
    }
    if (selection) {
      this.map.setFeatureState(
        { source: sourceForType(selection.type), id: selection.id },
        { selected: true },
      );
    }
    this.lastSelected = selection;
  }

  private lastHovered: { source: string; id: string } | null = null;

  setHover(id: string | null): void {
    if (this.lastHovered) {
      this.map.setFeatureState(
        { source: this.lastHovered.source, id: this.lastHovered.id },
        { hover: false },
      );
      this.lastHovered = null;
    }
    if (id) {
      const type = selectionTypeFromId(id);
      if (type) {
        const source = sourceForType(type);
        this.map.setFeatureState({ source, id }, { hover: true });
        this.lastHovered = { source, id };
      }
    }
  }

  private lastCompared: ReadonlySet<string> = new Set();

  /** Highlights sibling-variant segments the inspector's "compare" toggle picked (a cyan halo, see
   * `LAYER.segmentsCompare`). Pass an empty set to clear. */
  setCompare(ids: ReadonlySet<string>): void {
    for (const id of this.lastCompared) {
      if (!ids.has(id)) this.map.setFeatureState({ source: SOURCE.segments, id }, { compare: false });
    }
    for (const id of ids) {
      this.map.setFeatureState({ source: SOURCE.segments, id }, { compare: true });
    }
    this.lastCompared = ids;
  }

  /** Draws an imported GPX track (scout mode, lib/gpx.ts `parseGpxTrack`) as a magenta line for
   * visual comparison against the candidate segments. `null` removes it. */
  setImportedGpx(points: [number, number][] | null): void {
    const data: FeatureCollection<LineString, Record<string, never>> = {
      type: 'FeatureCollection',
      features: points && points.length >= 2
        ? [{ type: 'Feature', geometry: { type: 'LineString', coordinates: points }, properties: {} }]
        : [],
    };
    const existing = this.map.getSource(SOURCE.gpxImport);
    if (existing && 'setData' in existing) {
      (existing as GeoJSONSource).setData(data);
      return;
    }
    this.map.addSource(SOURCE.gpxImport, { type: 'geojson', data });
    this.map.addLayer({
      id: LAYER.gpxImport,
      type: 'line',
      source: SOURCE.gpxImport,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#e83bd0',
        'line-width': 3,
        'line-dasharray': [1, 1],
      },
    });
  }

  clearImportedGpx(): void {
    this.setImportedGpx(null);
  }

  /** A small circle that follows the mouse position on the elevation profile (bottom panel), so a
   * scout can see where a km/elevation reading on the chart sits on the map. `null` hides it. */
  setHoverMarker(coord: [number, number] | null): void {
    const data: FeatureCollection<Point, Record<string, never>> = {
      type: 'FeatureCollection',
      features: coord ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: coord }, properties: {} }] : [],
    };
    const existing = this.map.getSource(SOURCE.hoverMarker);
    if (existing && 'setData' in existing) {
      (existing as GeoJSONSource).setData(data);
      return;
    }
    this.map.addSource(SOURCE.hoverMarker, { type: 'geojson', data });
    this.map.addLayer({
      id: LAYER.hoverMarker,
      type: 'circle',
      source: SOURCE.hoverMarker,
      paint: {
        'circle-radius': 6,
        'circle-color': '#f4ecd8',
        'circle-stroke-color': '#e8632b',
        'circle-stroke-width': 2,
      },
    });
  }

  private setVisible(layerId: string, visible: boolean): void {
    if (!this.map.getLayer(layerId)) return;
    this.map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
  }

  /** Hover cursor + click-to-select, using `queryRenderedFeatures` rather than per-layer
   * `map.on(type, layerId, ...)` listeners so this works the same across MapLibre versions. */
  bindInteractions(handlers: {
    onHover: (id: string | null) => void;
    onSelect: (selection: Selection | null) => void;
  }): void {
    this.map.on('mousemove', (e) => {
      const features = this.map.queryRenderedFeatures(e.point, { layers: [...INTERACTIVE_LAYERS] });
      const top = features[0] as MapGeoJSONFeature | undefined;
      const id = (top?.properties?.['id'] as string | undefined) ?? null;
      this.map.getCanvas().style.cursor = id ? 'pointer' : '';
      handlers.onHover(id);
    });
    this.map.on('mouseout', () => handlers.onHover(null));
    this.map.on('click', (e) => {
      const features = this.map.queryRenderedFeatures(e.point, { layers: [...INTERACTIVE_LAYERS] });
      const top = features[0] as MapGeoJSONFeature | undefined;
      const id = top?.properties?.['id'] as string | undefined;
      if (!id) {
        handlers.onSelect(null);
        return;
      }
      const type = selectionTypeFromId(id);
      handlers.onSelect(type ? { type, id } : null);
    });
  }
}

function sourceForType(type: Selection['type']): string {
  switch (type) {
    case 'segment':
      return SOURCE.segments;
    case 'node':
      return SOURCE.nodes;
    case 'poi':
      return SOURCE.pois;
  }
}
