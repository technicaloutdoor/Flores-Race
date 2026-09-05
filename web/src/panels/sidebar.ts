// Left panel: route variant selector, headline stats, status progress bar, the ordered section
// list with stories, and the status/POI-category legend (ARCHITECTURE.md §7.3, BRIEF panel 1).

import { SEGMENT_STATUSES, STATUS_META, POI_CATEGORY_META, type Status } from '../data/types.ts';
import type { Section, SegmentFeature } from '../data/types.ts';
import { routeStats, segmentsInSection, bboxOf, isConceptSketchOnly } from '../data/derive.ts';
import { formatApproxKm, formatApproxM, formatKm, formatM, formatPct } from '../lib/format.ts';
import { renderMarkdown } from '../lib/markdown.ts';
import { sectionGpx, routeGpx, downloadGpx } from '../lib/gpx.ts';
import { flyToBbox, flyToPoint } from '../map/fit.ts';
import { categoryInitials } from '../map/layers.ts';
import {
  el,
  emptyState,
  habBadge,
  loadingState,
  priorityBadge,
  statTile,
  themeChip,
} from './ui.ts';
import type { PanelContext } from './context.ts';

/** Which section's story is expanded. Module-level so it survives the full-rebuild re-renders that
 * every store change triggers (the same pattern main.ts uses for the mobile tab bar). */
let expandedSectionId: string | null = null;

export function render(container: HTMLElement, ctx: PanelContext): void {
  container.replaceChildren();

  if (!ctx.bundleLoaded) {
    container.appendChild(el('h2', undefined, 'Route'));
    container.appendChild(loadingState('Loading route bundle…'));
    return;
  }

  // ARCHITECTURE.md §7.3: public mode's left panel is "sections only" — no variant selector, no
  // stats/progress bar, no legend (those are internal planning detail, not the public teaser).
  if (ctx.state.mode === 'public') {
    container.appendChild(el('h2', undefined, 'Sections'));
    renderSectionList(container, undefined, [], ctx);
    return;
  }

  container.appendChild(el('h2', undefined, 'Route'));
  const routes = ctx.routeStore.getRoutes().filter((r) => r.audience.includes(ctx.state.mode));
  if (routes.length === 0) {
    container.appendChild(emptyState('No route variants published for this mode yet.'));
  }

  const routeSelect = el('select');
  routeSelect.id = 'route-select';
  routeSelect.setAttribute('aria-label', 'Route variant');
  routeSelect.appendChild(new Option('(no route)', ''));
  for (const r of routes) routeSelect.appendChild(new Option(r.name, r.id));
  routeSelect.value = ctx.state.routeId ?? '';
  routeSelect.addEventListener('change', () => ctx.actions.setRoute(routeSelect.value || null));
  container.appendChild(routeSelect);

  const route = ctx.state.routeId ? ctx.routeStore.getRoute(ctx.state.routeId) : undefined;
  if (route?.tagline) container.appendChild(el('p', 'tagline', route.tagline));

  const resolvedSegments: SegmentFeature[] = route
    ? route.segments.map((id) => ctx.getSegment(id)).filter((s): s is SegmentFeature => Boolean(s))
    : [];

  if (route) {
    container.appendChild(renderStatsTiles(resolvedSegments));
    container.appendChild(renderStatusProgress(resolvedSegments));

    const gpxRow = el('div', 'button-row');
    const gpxButton = el('button', 'btn', 'Export route GPX');
    gpxButton.type = 'button';
    gpxButton.disabled = resolvedSegments.length === 0;
    gpxButton.addEventListener('click', () => {
      downloadGpx(`${route.id}.gpx`, routeGpx(route, resolvedSegments));
    });
    gpxRow.appendChild(gpxButton);
    container.appendChild(gpxRow);
  } else {
    container.appendChild(emptyState('Select a route variant to see its stats and progress.'));
  }

  container.appendChild(el('h2', undefined, 'Sections'));
  renderSectionList(container, route, resolvedSegments, ctx);

  container.appendChild(renderLegend());
}

function renderSectionList(
  container: HTMLElement,
  route: ReturnType<PanelContext['routeStore']['getRoute']>,
  resolvedSegments: SegmentFeature[],
  ctx: PanelContext,
): void {
  const sections = ctx.routeStore
    .getSections()
    .filter((s) => ctx.state.mode !== 'public' || s.public)
    .sort((a, b) => a.order - b.order);

  if (sections.length === 0) {
    container.appendChild(emptyState('No narrative sections published yet.'));
    return;
  }
  const list = el('div', 'section-list');
  for (const section of sections) {
    list.appendChild(renderSectionRow(section, route, resolvedSegments, ctx, container));
  }
  container.appendChild(list);
}

/** Share of the route/section's length that is still `concept` or `desk-checked` -- i.e. not yet
 * checked against the ground by anyone. Used to decide whether the headline numbers should read
 * as a desk estimate rather than a measured fact (ARCHITECTURE.md principle 3). */
function unscoutedKmFraction(segments: SegmentFeature[]): number {
  let total = 0;
  let unscouted = 0;
  for (const f of segments) {
    const km = f.properties.stats?.length_km ?? 0;
    total += km;
    if (f.properties.status === 'concept' || f.properties.status === 'desk-checked') unscouted += km;
  }
  return total > 0 ? unscouted / total : 1;
}

// A guessed climb is worse than none: sketched corridors are hand-drawn, never routed over the
// track network or traced in the field, so a DEM-sampled ascent along one is climbing the corridor
// was never actually shown to follow. Shown as the Ascent tile's tooltip (below) and folded into
// the concept note when that note is already on screen.
const ASCENT_SKETCH_TOOLTIP =
  'Climbing is only computed for network-routed or traced geometry; sketched corridors cross terrain freely';

function renderStatsTiles(segments: SegmentFeature[]): HTMLElement {
  const stats = routeStats(segments);
  // Most of the course starts life as a hand-sketched/computed `concept` corridor sampled once
  // against the DEM -- not a fact anyone has ridden or walked. Showing "1132.1 km" with the same
  // one-decimal confidence as a GPS-measured track overstates it; round coarser and mark it as an
  // estimate instead, until enough of the route has actually been scouted.
  const isDeskEstimate = unscoutedKmFraction(segments) >= 0.5;
  // A route that is *entirely* sketched corridors has no real elevation-following geometry to
  // climb along at all -- showing any ascent number, even rounded as an estimate, would present a
  // guess as a fact. A route that mixes sketched and network-routed/traced segments keeps its
  // number (it's a real, if partial, measurement).
  const sketchOnly = isConceptSketchOnly(segments);
  const grid = el('div', 'stat-grid');
  grid.classList.toggle('stat-grid-desk-estimate', isDeskEstimate);
  grid.append(
    statTile('Total', isDeskEstimate ? formatApproxKm(stats.length_km) : formatKm(stats.length_km)),
    sketchOnly
      ? statTile('Ascent', 'n/a', ASCENT_SKETCH_TOOLTIP)
      : statTile('Ascent', isDeskEstimate ? formatApproxM(stats.ascent_m) : formatM(stats.ascent_m)),
    statTile('Hike-a-bike', formatKm(stats.hab_km)),
    statTile('Unpaved', formatPct(stats.unpaved_pct)),
  );
  const wrap = el('div', 'stat-tiles-wrap');
  // Placed above the tiles, not just as a small caption below them: this is also the app's one
  // always-visible statement that the selected route is still a "concept" -- a starting
  // hypothesis, per docs/route-concept.md's own opening framing -- not only a note about number
  // precision. A first-time viewer shouldn't have to learn the legend's dash/colour conventions
  // to know that.
  if (isDeskEstimate) {
    let note =
      'Concept course — a starting hypothesis, not yet scouted. Numbers below are desk estimates and will tighten as segments are checked in the field.';
    if (sketchOnly) {
      note +=
        ' Every segment here is a hand-sketched corridor rather than a routed or traced line, so ascent is not shown — sketched corridors cross terrain freely and climbing can only be computed for network-routed or traced geometry.';
    }
    wrap.appendChild(el('p', 'stat-desk-estimate-note', note));
  }
  wrap.appendChild(grid);
  return wrap;
}

function renderStatusProgress(segments: SegmentFeature[]): HTMLElement {
  const wrap = el('div', 'status-progress');
  const kmByStatus = Object.fromEntries(SEGMENT_STATUSES.map((s) => [s, 0])) as Record<
    Status,
    number
  >;
  let total = 0;
  for (const f of segments) {
    const km = f.properties.stats?.length_km ?? 0;
    kmByStatus[f.properties.status] += km;
    total += km;
  }

  const bar = el('div', 'progress-bar');
  if (total > 0) {
    for (const status of SEGMENT_STATUSES) {
      const km = kmByStatus[status];
      if (km <= 0) continue;
      const segment = el('div', 'progress-segment');
      segment.style.width = `${(km / total) * 100}%`;
      segment.style.background = STATUS_META[status].color;
      segment.title = `${STATUS_META[status].label}: ${formatKm(km)}`;
      bar.appendChild(segment);
    }
  }
  wrap.appendChild(bar);

  const legend = el('div', 'progress-legend');
  for (const status of SEGMENT_STATUSES) {
    const km = kmByStatus[status];
    if (km <= 0) continue;
    const row = el('span', 'legend-item');
    const dot = el('span', 'status-dot');
    dot.style.background = STATUS_META[status].color;
    row.append(dot, document.createTextNode(`${STATUS_META[status].label} ${formatKm(km)}`));
    legend.appendChild(row);
  }
  wrap.appendChild(legend);
  return wrap;
}

function renderSectionRow(
  section: Section,
  route: ReturnType<PanelContext['routeStore']['getRoute']>,
  resolvedSegments: SegmentFeature[],
  ctx: PanelContext,
  container: HTMLElement,
): HTMLElement {
  const row = el('div', 'section-row');
  const header = el('div', 'section-header');
  header.append(el('span', 'section-order', String(section.order).padStart(2, '0')));
  const titleWrap = el('div', 'section-title-wrap');
  titleWrap.appendChild(el('div', 'section-title', section.title));
  if (section.subtitle) titleWrap.appendChild(el('div', 'section-subtitle', section.subtitle));
  header.appendChild(titleWrap);
  row.appendChild(header);

  const chips = el('div', 'chip-row');
  for (const theme of section.theme) chips.appendChild(themeChip(theme));
  chips.appendChild(habBadge(section.hab_expected));
  chips.appendChild(priorityBadge(section.scouting_priority));
  row.appendChild(chips);

  const sectionSegments = route ? segmentsInSection(section, route, resolvedSegments) : [];
  const sketchedKm = sectionSegments.reduce((sum, f) => sum + (f.properties.stats?.length_km ?? 0), 0);
  const kmLine = el(
    'div',
    'section-km',
    `Target ${section.target_km[0]}–${section.target_km[1]} km` +
      (route ? ` · sketched ${formatKm(sketchedKm)}` : ''),
  );
  row.appendChild(kmLine);

  const isExpanded = expandedSectionId === section.id;
  header.classList.toggle('expanded', isExpanded);
  // A plain <div> with a click handler is invisible to keyboard and screen-reader users; in
  // `public` mode this section list is the *entire* left-panel content (see the early return
  // above), so without this nobody using a keyboard or a screen reader could open a single
  // section's story. Made a focusable, announced toggle button in place, rather than swapping in
  // a real <button> (which would need its own reset of all the header's flex/typography styling).
  header.tabIndex = 0;
  header.setAttribute('role', 'button');
  header.setAttribute('aria-expanded', String(isExpanded));
  const toggleSection = (): void => {
    expandedSectionId = isExpanded ? null : section.id;
    if (ctx.mapLayers) {
      const target = sectionSegments.length
        ? bboxOf(sectionSegments)
        : bboxOf(
            section.highlight_pois
              .map((id) => ctx.routeStore.getPoi(id))
              .filter((p): p is NonNullable<typeof p> => Boolean(p)),
          );
      flyToBbox(ctx.map, target, { padding: 70, duration: 1200 });
    }
    render(container, ctx);
  };
  header.addEventListener('click', toggleSection);
  header.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault(); // stop Space from scrolling the panel
    toggleSection();
  });

  if (isExpanded) {
    const details = el('div', 'section-details');
    const story = el('div', 'story');
    story.appendChild(renderMarkdown(section.story));
    details.appendChild(story);

    if (section.highlight_pois.length) {
      const poiRow = el('div', 'chip-row');
      for (const poiId of section.highlight_pois) {
        const poi = ctx.routeStore.getPoi(poiId);
        const chip = el('button', 'chip chip-button', poi?.properties.name ?? poiId);
        chip.type = 'button';
        chip.addEventListener('click', (e) => {
          e.stopPropagation();
          ctx.actions.select({ type: 'poi', id: poiId });
          if (poi) flyToPoint(ctx.map, poi.geometry.coordinates as [number, number]);
        });
        poiRow.appendChild(chip);
      }
      details.appendChild(poiRow);
    }

    if (ctx.state.mode !== 'public' && section.open_questions.length) {
      const oq = el('div', 'open-questions');
      oq.appendChild(el('div', 'field-label', 'Open questions'));
      const ul = el('ul');
      for (const q of section.open_questions) ul.appendChild(el('li', undefined, q));
      oq.appendChild(ul);
      details.appendChild(oq);
    }

    if (sectionSegments.length) {
      const btn = el('button', 'btn', 'Export section GPX');
      btn.type = 'button';
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        downloadGpx(`${section.id}.gpx`, sectionGpx(section, sectionSegments));
      });
      details.appendChild(btn);
    }

    row.appendChild(details);
  }

  return row;
}

function renderLegend(): HTMLElement {
  const wrap = el('div', 'legend-block');
  wrap.appendChild(el('h2', undefined, 'Legend'));

  const statusGroup = el('div', 'legend-group');
  statusGroup.appendChild(el('div', 'field-label', 'Segment status'));
  for (const status of SEGMENT_STATUSES) {
    const meta = STATUS_META[status];
    const row = el('span', 'legend-item');
    const dot = el('span', 'status-dot');
    dot.style.background = meta.color;
    row.append(dot, document.createTextNode(meta.label));
    row.title = meta.description;
    statusGroup.appendChild(row);
  }
  wrap.appendChild(statusGroup);

  const poiGroup = el('div', 'legend-group');
  poiGroup.appendChild(el('div', 'field-label', 'POI categories'));
  for (const meta of Object.values(POI_CATEGORY_META)) {
    const row = el('span', 'legend-item');
    const swatch = el('span', 'poi-swatch', categoryInitials(meta.icon));
    row.append(swatch, document.createTextNode(meta.label));
    poiGroup.appendChild(row);
  }
  // The hazard ring is a colour, not a category (an active volcano stays category 'volcano') --
  // see map/layers.ts HAZARD_RING_COLOR -- so it needs its own legend row, not one per category.
  const hazardRow = el('span', 'legend-item');
  const hazardSwatch = el('span', 'poi-swatch poi-swatch-hazard');
  hazardRow.append(hazardSwatch, document.createTextNode('Active hazard (see hazard_level)'));
  hazardRow.title = 'Any POI with a hazard_level (e.g. an active volcano) gets a red ring on the map, regardless of its category.';
  poiGroup.appendChild(hazardRow);
  wrap.appendChild(poiGroup);

  // The track network layer (zoom 9+, see map/layers.ts setNetwork): colour is road class
  // (tracks/paths vs formal roads), and line weight/opacity scale with remoteness where the graph
  // build computed it -- a faint line is close to a main road or settlement, a bold one is not.
  const networkGroup = el('div', 'legend-group');
  const networkRow = el('span', 'legend-item');
  const networkSwatch = el('span', 'network-swatch');
  networkRow.append(networkSwatch, document.createTextNode('Network: brighter = more remote'));
  networkRow.title =
    'Track network layer (visible from zoom 9): colour by road class (tracks/paths vs formal roads); line weight and opacity increase with remoteness, where known.';
  networkGroup.appendChild(networkRow);
  wrap.appendChild(networkGroup);

  return wrap;
}
