// The one place that knows what `public` mode hides. ARCHITECTURE.md §9 / BRIEF §6: "public mode
// hides non-public features (filter at load) ... network layer, sources and open_questions." Only
// `public` mode filters by each feature's own `public` flag; stakeholder and scout modes show
// everything (the flag is an opt-in for the *public site*, not a general visibility control) —
// see docs/data-model.md. Routes are filtered differently, by their `audience` list, in every mode.

import type { Bundle } from './store.ts';
import type {
  NodeFeature,
  POIFeature,
  Route,
  Section,
  SegmentFeature,
} from './types.ts';
import type { Mode } from '../state/store.ts';

export function visibleNodes(bundle: Bundle, mode: Mode): NodeFeature[] {
  return mode === 'public' ? bundle.nodes.features.filter((f) => f.properties.public) : bundle.nodes.features;
}

export function visiblePois(bundle: Bundle, mode: Mode): POIFeature[] {
  return mode === 'public' ? bundle.pois.features.filter((f) => f.properties.public) : bundle.pois.features;
}

export function visibleSegments(bundle: Bundle, mode: Mode): SegmentFeature[] {
  return mode === 'public'
    ? bundle.segments.features.filter((f) => f.properties.public)
    : bundle.segments.features;
}

export function visibleSections(bundle: Bundle, mode: Mode): Section[] {
  return mode === 'public' ? bundle.sections.filter((s) => s.public) : bundle.sections;
}

/** Every mode filters the route list by `audience` — it's what the field is for (data-model.md). */
export function visibleRoutes(bundle: Bundle, mode: Mode): Route[] {
  return bundle.routes.filter((r) => r.audience.includes(mode));
}
