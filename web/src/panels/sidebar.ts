// Left panel: route variant selector, headline stats, status progress bar, the ordered section
// list with stories, and the status/POI-category legend (ARCHITECTURE.md §7.3, BRIEF panel 1).

import { SEGMENT_STATUSES, STATUS_META, POI_CATEGORY_META, type Status } from '../data/types.ts';
import type { Section, SegmentFeature } from '../data/types.ts';
import { routeStats, segmentsInSection, bboxOf } from '../data/derive.ts';
import { formatKm, formatM, formatPct } from '../lib/format.ts';
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

function renderStatsTiles(segments: SegmentFeature[]): HTMLElement {
  const stats = routeStats(segments);
  const grid = el('div', 'stat-grid');
  grid.append(
    statTile('Total', formatKm(stats.length_km)),
    statTile('Ascent', formatM(stats.ascent_m)),
    statTile('Hike-a-bike', formatKm(stats.hab_km)),
    statTile('Unpaved', formatPct(stats.unpaved_pct)),
  );
  return grid;
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
  header.addEventListener('click', () => {
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
  wrap.appendChild(poiGroup);

  return wrap;
}
