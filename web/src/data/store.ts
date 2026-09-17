// Data access: everything the app reads goes through the `RouteStore` interface. Today there is
// one implementation, `StaticFileStore`, which fetches the generated bundle under
// `web/public/data/`. See ARCHITECTURE.md §7.4 — a future live-collaboration backend would slot in
// behind this same interface without touching the map or panels.

import type { FeatureCollection, LineString, MultiPolygon, Polygon } from 'geojson';
import type {
  NodeFeature,
  NodesGeoJSON,
  POIFeature,
  POIsGeoJSON,
  Route,
  RoutesJSON,
  Section,
  SectionsJSON,
  SegmentFeature,
  SegmentsGeoJSON,
} from './types.ts';

/** `profiles.json`: distance/elevation samples keyed by segment id or route id. */
export type ProfilesJSON = Record<string, Array<[number, number]>>;

export interface RegencyProps {
  id: string;
  name: string;
  local_name?: string;
  area_km2?: number;
}
export type RegenciesGeoJSON = FeatureCollection<Polygon | MultiPolygon, RegencyProps>;

export interface MetaSource {
  name: string;
  url?: string;
  license: string;
}

export interface MetaJSON {
  build_time: string;
  overture_release?: string;
  git_commit?: string;
  sources: MetaSource[];
  counts?: Record<string, number>;
  /** Attribution strings for MapLibre's attribution control, in display order. */
  attribution: string[];
}

/** Reduced properties `build_web_data.py` keeps on network edges — see data-model.md. */
export interface NetworkProps {
  class?: string;
  surface?: string;
  name?: string;
  remoteness?: number;
}
export type NetworkGeoJSON = FeatureCollection<LineString, NetworkProps>;

export interface NetworkResult {
  data: NetworkGeoJSON | null;
  /** Set when `data` is null: why the layer is disabled, for display in the UI (not a console-only error). */
  note?: string;
}

export interface Bundle {
  nodes: NodesGeoJSON;
  pois: POIsGeoJSON;
  segments: SegmentsGeoJSON;
  sections: SectionsJSON;
  routes: RoutesJSON;
  profiles: ProfilesJSON;
  regencies: RegenciesGeoJSON;
  meta: MetaJSON;
}

export interface RouteStore {
  /** Fetches and caches the whole bundle (everything except the lazy network layer). */
  loadAll(): Promise<Bundle>;
  /** Fetches (and caches) `network.geojson.gz`, decompressed with the native `DecompressionStream`.
   * Resolves to `{ data: null, note }` rather than rejecting when the file is missing (404) or the
   * browser lacks `DecompressionStream`, so callers can disable the layer gracefully. */
  loadNetwork(): Promise<NetworkResult>;

  getRoutes(): Route[];
  getRoute(id: string): Route | undefined;
  getSections(): Section[];
  getSection(id: string): Section | undefined;
  getSegment(id: string): SegmentFeature | undefined;
  getNode(id: string): NodeFeature | undefined;
  getPoi(id: string): POIFeature | undefined;
  getMeta(): MetaJSON | undefined;
  getProfile(id: string): Array<[number, number]> | undefined;
}

/** `RouteStore` backed by static files under `<BASE_URL>data/`, per ARCHITECTURE.md §7.4. */
export class StaticFileStore implements RouteStore {
  private readonly base: string;
  private bundle: Bundle | undefined;
  private network: NetworkResult | undefined;

  private routesById = new Map<string, Route>();
  private sectionsById = new Map<string, Section>();
  private segmentsById = new Map<string, SegmentFeature>();
  private nodesById = new Map<string, NodeFeature>();
  private poisById = new Map<string, POIFeature>();

  constructor(baseUrl: string = import.meta.env.BASE_URL) {
    this.base = `${baseUrl.replace(/\/?$/, '/')}data/`;
  }

  async loadAll(): Promise<Bundle> {
    if (this.bundle) return this.bundle;

    const [nodes, pois, segments, sections, routes, profiles, regencies, meta] = await Promise.all([
      this.fetchJson<NodesGeoJSON>('nodes.geojson'),
      this.fetchJson<POIsGeoJSON>('pois.geojson'),
      this.fetchJson<SegmentsGeoJSON>('segments.geojson'),
      this.fetchJson<SectionsJSON>('sections.json'),
      this.fetchJson<RoutesJSON>('routes.json'),
      this.fetchJson<ProfilesJSON>('profiles.json'),
      this.fetchJson<RegenciesGeoJSON>('regencies.geojson'),
      this.fetchJson<MetaJSON>('meta.json'),
    ]);

    const bundle: Bundle = { nodes, pois, segments, sections, routes, profiles, regencies, meta };
    this.bundle = bundle;
    this.index(bundle);
    return bundle;
  }

  async loadNetwork(): Promise<NetworkResult> {
    if (this.network) return this.network;

    const url = `${this.base}network.geojson.gz`;
    let response: Response;
    try {
      response = await fetch(url);
    } catch {
      this.network = { data: null, note: 'Network layer unavailable: the request failed.' };
      return this.network;
    }

    if (!response.ok || !response.body) {
      this.network = {
        data: null,
        note:
          response.status === 404
            ? 'Network layer disabled: network.geojson.gz has not been built by the pipeline yet.'
            : `Network layer disabled: HTTP ${response.status} loading network.geojson.gz.`,
      };
      return this.network;
    }

    // A dev server's SPA fallback (e.g. `vite preview` for a path with no matching static file)
    // can answer a missing file with HTTP 200 and an HTML page instead of a real 404 — GitHub
    // Pages (the actual deploy target) does not do this, but check the gzip magic bytes anyway so
    // the "not built yet" message is accurate in both places instead of a confusing decode error.
    const head = new Uint8Array(await response.clone().arrayBuffer());
    if (head[0] !== 0x1f || head[1] !== 0x8b) {
      this.network = {
        data: null,
        note: 'Network layer disabled: network.geojson.gz has not been built by the pipeline yet.',
      };
      return this.network;
    }

    if (typeof DecompressionStream === 'undefined') {
      this.network = {
        data: null,
        note: 'Network layer disabled: this browser has no DecompressionStream support.',
      };
      return this.network;
    }

    try {
      const decompressed = response.body.pipeThrough(new DecompressionStream('gzip'));
      const text = await new Response(decompressed).text();
      const data = JSON.parse(text) as NetworkGeoJSON;
      this.network = { data };
    } catch {
      this.network = { data: null, note: 'Network layer disabled: failed to decompress or parse.' };
    }
    return this.network;
  }

  getRoutes(): Route[] {
    return this.bundle?.routes ?? [];
  }
  getRoute(id: string): Route | undefined {
    return this.routesById.get(id);
  }
  getSections(): Section[] {
    return this.bundle?.sections ?? [];
  }
  getSection(id: string): Section | undefined {
    return this.sectionsById.get(id);
  }
  getSegment(id: string): SegmentFeature | undefined {
    return this.segmentsById.get(id);
  }
  getNode(id: string): NodeFeature | undefined {
    return this.nodesById.get(id);
  }
  getPoi(id: string): POIFeature | undefined {
    return this.poisById.get(id);
  }
  getMeta(): MetaJSON | undefined {
    return this.bundle?.meta;
  }
  getProfile(id: string): Array<[number, number]> | undefined {
    return this.bundle?.profiles[id];
  }

  private index(bundle: Bundle): void {
    this.routesById = new Map(bundle.routes.map((r) => [r.id, r]));
    this.sectionsById = new Map(bundle.sections.map((s) => [s.id, s]));
    this.segmentsById = new Map(bundle.segments.features.map((f) => [f.properties.id, f]));
    this.nodesById = new Map(bundle.nodes.features.map((f) => [f.properties.id, f]));
    this.poisById = new Map(bundle.pois.features.map((f) => [f.properties.id, f]));
  }

  private async fetchJson<T>(name: string): Promise<T> {
    const response = await fetch(this.base + name);
    if (!response.ok) {
      throw new Error(`Failed to load ${name}: HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  }
}
