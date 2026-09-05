import type {
  Feature,
  FeatureCollection,
  Point,
  LineString,
} from 'geojson';

// Shared enumerations
export type Confidence = 'verified' | 'approximate' | 'unverified';
export const CONFIDENCE_VALUES = [
  'verified',
  'approximate',
  'unverified',
] as const;

export type Status =
  | 'concept'
  | 'desk-checked'
  | 'scouted-go'
  | 'scouted-no-go'
  | 'needs-recheck'
  | 'confirmed';
export const SEGMENT_STATUSES = [
  'concept',
  'desk-checked',
  'scouted-go',
  'scouted-no-go',
  'needs-recheck',
  'confirmed',
] as const;

export type GeometrySource =
  | 'concept-sketch'
  | 'overture-route'
  | 'gpx-field'
  | 'manual-trace';
export const GEOMETRY_SOURCES = [
  'concept-sketch',
  'overture-route',
  'gpx-field',
  'manual-trace',
] as const;

export type Character =
  | 'paved'
  | 'gravel'
  | 'dirt'
  | 'singletrack'
  | 'hab'
  | 'mixed'
  | 'unknown';
export const CHARACTERS = [
  'paved',
  'gravel',
  'dirt',
  'singletrack',
  'hab',
  'mixed',
  'unknown',
] as const;

export type Theme =
  | 'volcano'
  | 'highland'
  | 'coast'
  | 'culture'
  | 'forest'
  | 'savanna'
  | 'history';
export const THEMES = [
  'volcano',
  'highland',
  'coast',
  'culture',
  'forest',
  'savanna',
  'history',
] as const;

export type POICategory =
  | 'volcano'
  | 'crater-lake'
  | 'lake'
  | 'traditional-village'
  | 'beach'
  | 'hot-spring'
  | 'waterfall'
  | 'cave'
  | 'heritage'
  | 'viewpoint'
  | 'market'
  | 'port'
  | 'airport'
  | 'national-park'
  | 'weaving'
  | 'religious'
  | 'hazard'
  | 'forest'
  | 'savanna'
  | 'rice-terrace'
  | 'other';
export const POI_CATEGORIES = [
  'volcano',
  'crater-lake',
  'lake',
  'traditional-village',
  'beach',
  'hot-spring',
  'waterfall',
  'cave',
  'heritage',
  'viewpoint',
  'market',
  'port',
  'airport',
  'national-park',
  'weaving',
  'religious',
  'hazard',
  'forest',
  'savanna',
  'rice-terrace',
  'other',
] as const;

export type NodeKind =
  | 'start'
  | 'finish'
  | 'checkpoint'
  | 'town'
  | 'village'
  | 'junction'
  | 'trailhead'
  | 'port'
  | 'airport';
export const NODE_KINDS = [
  'start',
  'finish',
  'checkpoint',
  'town',
  'village',
  'junction',
  'trailhead',
  'port',
  'airport',
] as const;

export type ResupplyLevel = 'none' | 'minimal' | 'basic' | 'full';
export const RESUPPLY_LEVELS = [
  'none',
  'minimal',
  'basic',
  'full',
] as const;

export type WaterAvailability = 'none' | 'unreliable' | 'reliable';
export const WATER_AVAILABILITIES = [
  'none',
  'unreliable',
  'reliable',
] as const;

export type SleepOption = 'none' | 'homestay' | 'guesthouse' | 'hotel';
export const SLEEP_OPTIONS = [
  'none',
  'homestay',
  'guesthouse',
  'hotel',
] as const;

export type RaceRelevance =
  | 'anchor'
  | 'highlight'
  | 'resupply'
  | 'hazard'
  | 'context';
export const RACE_RELEVANCES = [
  'anchor',
  'highlight',
  'resupply',
  'hazard',
  'context',
] as const;

export type POIAccess = 'road' | 'track' | 'trail' | 'boat' | 'unknown';
export const POI_ACCESSES = [
  'road',
  'track',
  'trail',
  'boat',
  'unknown',
] as const;

export type ScoutingVerdict = 'go' | 'no-go' | 'partial';
export const SCOUTING_VERDICTS = [
  'go',
  'no-go',
  'partial',
] as const;

export type RouteStatus = 'concept' | 'in-scouting' | 'confirmed';
export const ROUTE_STATUSES = [
  'concept',
  'in-scouting',
  'confirmed',
] as const;

export type HabExpectation = 'low' | 'medium' | 'high';
export const HAB_EXPECTATIONS = [
  'low',
  'medium',
  'high',
] as const;

export type Audience = 'stakeholder' | 'scout' | 'public';
export const AUDIENCES = [
  'stakeholder',
  'scout',
  'public',
] as const;

// Derived statistics
export interface Stats {
  length_km?: number;
  ascent_m?: number;
  descent_m?: number;
  min_elev_m?: number;
  max_elev_m?: number;
  unpaved_pct?: number;
  profile_ref?: string;
  hab_km?: number;
  segments_by_status?: Record<Status, number>;
}

// Scouting entry
export interface ScoutingEntry {
  date: string; // YYYY-MM-DD
  team: string;
  verdict: ScoutingVerdict;
  notes?: string;
  gpx?: string;
  photos?: string[];
}

// Node
export interface NodeProps {
  id: string; // n-*
  name: string;
  local_name?: string;
  kind: NodeKind;
  resupply: ResupplyLevel;
  water: WaterAvailability;
  sleep: SleepOption;
  notes?: string;
  confidence: Confidence;
  sources: string[];
  public?: boolean;
  elevation_m?: number;
}

export type NodeFeature = Feature<Point, NodeProps>;
export type NodesGeoJSON = FeatureCollection<Point, NodeProps>;

// POI
export interface POIProps {
  id: string; // p-*
  name: string;
  local_name?: string;
  category: POICategory;
  summary: string;
  story?: string;
  race_relevance: RaceRelevance;
  access: POIAccess;
  hike_a_bike?: boolean;
  cultural_protocol?: string;
  elevation_m?: number;
  hazard_level?: string;
  confidence: Confidence;
  sources: string[];
  public?: boolean;
  image?: string;
  image_credit?: string;
}

export type POIFeature = Feature<Point, POIProps>;
export type POIsGeoJSON = FeatureCollection<Point, POIProps>;

// Segment
export interface SegmentProps {
  id: string; // s-*
  name: string;
  from_node: string; // n-*
  to_node: string; // n-*
  variant: string; // A-Z
  status: Status;
  geometry_source: GeometrySource;
  character: Character;
  est_hab_km: number;
  difficulty: number; // 1-5
  remoteness: number; // 1-5
  direction_note?: string;
  water_points?: string[];
  resupply_notes?: string;
  hazards?: string[];
  cultural_notes?: string;
  open_questions?: string[];
  scouting?: ScoutingEntry[];
  stats?: Stats;
  surface_mix?: Record<string, number>;
  class_mix?: Record<string, number>;
  route_profile?: 'remote' | 'rideable' | 'direct';
  public?: boolean;
  sources: string[];
}

export type SegmentFeature = Feature<LineString, SegmentProps>;
export type SegmentsGeoJSON = FeatureCollection<LineString, SegmentProps>;

// Section
export interface Section {
  id: string; // sec-NN-*
  order: number;
  title: string;
  subtitle?: string;
  from_node: string; // n-*
  to_node: string; // n-*
  theme: Theme[];
  story: string; // markdown
  highlight_pois: string[]; // p-*
  target_km: [number, number]; // [min, max]
  hab_expected: HabExpectation;
  scouting_priority: number; // 1-3
  open_questions: string[];
  public?: boolean;
}

export type SectionsJSON = Section[];

// Route
export interface Route {
  id: string; // r-*
  name: string;
  tagline?: string;
  description?: string;
  audience: Audience[];
  anchors: string[]; // n-*
  segments: string[]; // s-*
  status: RouteStatus;
  target_km_range: [number, number]; // [min, max]
  time_limit_days?: number;
  notes?: string;
  stats?: Stats;
}

export type RoutesJSON = Route[];

// Scouting patch
export interface ScoutingPatch {
  version: 1;
  created: string; // ISO 8601 timestamp
  author: string;
  segments?: Record<
    string,
    {
      status?: Status;
      character?: Character;
      est_hab_km?: number;
      difficulty?: number;
      remoteness?: number;
      water_points?: string[];
      resupply_notes?: string;
      hazards?: string[];
      cultural_notes?: string;
      open_questions?: string[];
      scouting_append?: ScoutingEntry[];
    }
  >;
  nodes?: Record<
    string,
    {
      resupply?: ResupplyLevel;
      water?: WaterAvailability;
      sleep?: SleepOption;
      notes?: string;
    }
  >;
  new_pois?: Feature<Point>[];
}

// Metadata for UI
export interface StatusMeta {
  label: string;
  description: string;
  color: string;
}

export const STATUS_META: Record<Status, StatusMeta> = {
  concept: {
    label: 'Concept',
    description: 'Proposed route',
    color: '#9aa0a6',
  },
  'desk-checked': {
    label: 'Desk-checked',
    description: 'Verified on maps',
    color: '#e0a100',
  },
  'scouted-go': {
    label: 'Scouted Go',
    description: 'Verified in field',
    color: '#2e9e5b',
  },
  'scouted-no-go': {
    label: 'Scouted No-Go',
    description: 'Not passable',
    color: '#c0392b',
  },
  'needs-recheck': {
    label: 'Needs Recheck',
    description: 'Conditions changed',
    color: '#e67e22',
  },
  confirmed: {
    label: 'Confirmed',
    description: 'Final route',
    color: '#1b7f4a',
  },
};

export interface POICategoryMeta {
  label: string;
  icon: string; // icon key, no emoji
}

// `icon` doubles as the source string for `categoryInitials()` (map/layers.ts): it splits on '-'
// and keeps the first letter of each part, so every value here must stay distinct *after* that
// transform, not just as a string — "village" and "viewpoint" both reduce to "V" even though the
// words differ. Hyphenate a category's icon key (e.g. "trad-village") when the plain word would
// collide with another category's initial(s); a stakeholder needs a hazard marker to look
// different from a heritage marker on the map.
export const POI_CATEGORY_META: Record<POICategory, POICategoryMeta> = {
  volcano: { label: 'Volcano', icon: 'volcano' },
  'crater-lake': { label: 'Crater Lake', icon: 'crater-lake' },
  lake: { label: 'Lake', icon: 'lake' },
  'traditional-village': { label: 'Traditional Village', icon: 'trad-village' },
  beach: { label: 'Beach', icon: 'beach' },
  'hot-spring': { label: 'Hot Spring', icon: 'hot-spring' },
  waterfall: { label: 'Waterfall', icon: 'water-fall' },
  cave: { label: 'Cave', icon: 'cave' },
  heritage: { label: 'Heritage', icon: 'cultural-heritage' },
  viewpoint: { label: 'Viewpoint', icon: 'view-point' },
  market: { label: 'Market', icon: 'market' },
  port: { label: 'Port', icon: 'port' },
  airport: { label: 'Airport', icon: 'airport' },
  'national-park': { label: 'National Park', icon: 'national-park' },
  weaving: { label: 'Weaving', icon: 'weaving' },
  religious: { label: 'Religious Site', icon: 'religious' },
  hazard: { label: 'Hazard', icon: 'hazard' },
  forest: { label: 'Forest', icon: 'forest' },
  savanna: { label: 'Savanna', icon: 'savanna' },
  'rice-terrace': { label: 'Rice Terrace', icon: 'rice-terrace' },
  other: { label: 'Other', icon: 'other' },
};

export interface ConfidenceMeta {
  label: string;
  description: string;
  color: string;
}

/** A stakeholder must never mistake a guess for a fact (ARCHITECTURE.md §2) — every panel that
 * shows a POI, node or segment shows this badge prominently, never just in a tooltip. */
export const CONFIDENCE_META: Record<Confidence, ConfidenceMeta> = {
  verified: {
    label: 'Verified',
    description: 'Checked against two independent sources or a field GPS fix.',
    color: '#2e9e5b',
  },
  approximate: {
    label: 'Approximate',
    description: 'One source, or a well-known place located by hand within ~1 km.',
    color: '#e0a100',
  },
  unverified: {
    label: 'Unverified',
    description: 'From memory or a single weak source — must be checked.',
    color: '#c0392b',
  },
};

export interface ThemeMeta {
  label: string;
  color: string;
}

export const THEME_META: Record<Theme, ThemeMeta> = {
  volcano: { label: 'Volcano', color: '#c0392b' },
  highland: { label: 'Highland', color: '#6b8f47' },
  coast: { label: 'Coast', color: '#2f7f95' },
  culture: { label: 'Culture', color: '#b07d3f' },
  forest: { label: 'Forest', color: '#3f7d4a' },
  savanna: { label: 'Savanna', color: '#c9a45c' },
  history: { label: 'History', color: '#8a6d3b' },
};

export interface HabExpectationMeta {
  label: string;
  color: string;
}

export const HAB_EXPECTATION_META: Record<HabExpectation, HabExpectationMeta> = {
  low: { label: 'Low HAB', color: '#2e9e5b' },
  medium: { label: 'Medium HAB', color: '#e0a100' },
  high: { label: 'High HAB', color: '#c0392b' },
};
