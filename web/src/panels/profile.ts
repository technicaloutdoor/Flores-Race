// Bottom panel: hand-drawn SVG elevation profile (ARCHITECTURE.md §7.1 "no charting dependency",
// §7.3 panel 3). Shows the selected segment's own profile, or the selected route's concatenated
// profile with section boundaries and per-segment status colouring. Hovering shows a km/elevation
// readout and moves a small marker on the map (map/layers.ts `setHoverMarker`).

import { STATUS_META, type SegmentFeature, type Route } from '../data/types.ts';
import { coordAtKm, segmentsInSection } from '../data/derive.ts';
import { formatKm, formatM } from '../lib/format.ts';
import { el, emptyState, errorState } from './ui.ts';
import type { PanelContext } from './context.ts';

const SVG_NS = 'http://www.w3.org/2000/svg';
const VB_W = 1000;
const VB_H = 220;
const PAD_L = 46;
const PAD_R = 14;
const PAD_T = 16;
const PAD_B = 28;

interface Band {
  startKm: number;
  endKm: number;
  color: string;
}

interface Boundary {
  km: number;
  label: string;
}

export function render(container: HTMLElement, ctx: PanelContext): void {
  container.replaceChildren();

  // Public mode never shows a single segment's own profile — its name and status would leak detail
  // the inspector already withholds ("Segment and node detail is not shown in public mode."); fall
  // through to the coarse whole-route profile instead, same as when nothing is selected.
  const selection = ctx.state.selection;
  if (selection?.type === 'segment' && ctx.state.mode !== 'public') {
    const segment = ctx.getSegment(selection.id);
    if (!segment) {
      container.appendChild(el('h2', undefined, 'Profile'));
      container.appendChild(errorState(`Segment "${selection.id}" was not found in the loaded bundle.`));
      return;
    }
    renderSegmentProfile(container, ctx, segment);
    return;
  }

  const route = ctx.state.routeId ? ctx.routeStore.getRoute(ctx.state.routeId) : undefined;
  container.appendChild(el('h2', undefined, route ? `Profile — ${route.name}` : 'Profile'));
  if (!route) {
    container.appendChild(emptyState('Select a route or a segment to see its elevation profile.'));
    return;
  }
  renderRouteProfile(container, ctx, route);
}

function renderSegmentProfile(container: HTMLElement, ctx: PanelContext, segment: SegmentFeature): void {
  container.appendChild(el('h2', undefined, `Profile — ${segment.properties.name}`));
  const profile = ctx.routeStore.getProfile(segment.properties.id);
  if (!profile || profile.length === 0) {
    container.appendChild(emptyState('Profile not computed yet for this segment.'));
    return;
  }
  const color = STATUS_META[segment.properties.status].color;
  const bands: Band[] = [{ startKm: profile[0]![0], endKm: profile[profile.length - 1]![0], color }];
  container.appendChild(drawProfileSvg(ctx, profile, bands, [], [segment]));
}

function renderRouteProfile(container: HTMLElement, ctx: PanelContext, route: Route): void {
  const profile = ctx.routeStore.getProfile(route.id);
  if (!profile || profile.length === 0) {
    container.appendChild(emptyState('Profile not computed yet for this route.'));
    return;
  }

  const resolved = route.segments
    .map((id) => ctx.getSegment(id))
    .filter((s): s is SegmentFeature => Boolean(s));

  const bands: Band[] = [];
  let cumulative = 0;
  for (const seg of resolved) {
    const length = seg.properties.stats?.length_km ?? 0;
    const color = ctx.state.mode === 'public' ? 'var(--color-accent)' : STATUS_META[seg.properties.status].color;
    bands.push({ startKm: cumulative, endKm: cumulative + length, color });
    cumulative += length;
  }

  const boundaries: Boundary[] = [];
  if (ctx.state.mode !== 'public') {
    const sections = ctx.routeStore
      .getSections()
      .sort((a, b) => a.order - b.order);
    for (const section of sections) {
      const segsInSection = segmentsInSection(section, route, resolved);
      if (segsInSection.length === 0) continue;
      const startIdx = resolved.findIndex((s) => s.properties.id === segsInSection[0]!.properties.id);
      if (startIdx <= 0) continue; // the route's own start isn't a "boundary" worth marking
      const km = bands[startIdx]?.startKm ?? 0;
      boundaries.push({ km, label: String(section.order).padStart(2, '0') });
    }
  }

  container.appendChild(drawProfileSvg(ctx, profile, bands, boundaries, resolved));
}

function nearestElevation(profile: ReadonlyArray<[number, number]>, km: number): [number, number] {
  // profile km values are monotonic non-decreasing; a linear scan is fine at this size (hundreds of
  // points), and keeps this file free of a binary-search helper for one call site.
  let best = profile[0]!;
  let bestDiff = Math.abs(best[0] - km);
  for (const point of profile) {
    const diff = Math.abs(point[0] - km);
    if (diff < bestDiff) {
      best = point;
      bestDiff = diff;
    }
  }
  return best;
}

function svgEl<K extends keyof SVGElementTagNameMap>(tag: K): SVGElementTagNameMap[K] {
  return document.createElementNS(SVG_NS, tag) as SVGElementTagNameMap[K];
}

function drawProfileSvg(
  ctx: PanelContext,
  profile: ReadonlyArray<[number, number]>,
  bands: Band[],
  boundaries: Boundary[],
  hoverSegments: SegmentFeature[],
): HTMLElement {
  const wrap = el('div', 'profile-wrap');
  const totalKm = profile[profile.length - 1]![0] || 1;
  let minElev = Infinity;
  let maxElev = -Infinity;
  for (const [, elev] of profile) {
    if (elev < minElev) minElev = elev;
    if (elev > maxElev) maxElev = elev;
  }
  if (!Number.isFinite(minElev)) {
    minElev = 0;
    maxElev = 1;
  }
  if (minElev === maxElev) maxElev = minElev + 1;

  const plotW = VB_W - PAD_L - PAD_R;
  const plotH = VB_H - PAD_T - PAD_B;
  const xForKm = (km: number) => PAD_L + (km / totalKm) * plotW;
  const yForElev = (elev: number) => PAD_T + (1 - (elev - minElev) / (maxElev - minElev)) * plotH;

  const svg = svgEl('svg');
  svg.setAttribute('viewBox', `0 0 ${VB_W} ${VB_H}`);
  svg.setAttribute('class', 'profile-svg');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `Elevation profile, ${formatKm(totalKm)}, ${Math.round(minElev)} to ${Math.round(maxElev)} metres`);

  // Baseline + elevation gridlines (min/mid/max).
  for (const frac of [0, 0.5, 1]) {
    const elev = minElev + (maxElev - minElev) * frac;
    const y = yForElev(elev);
    const line = svgEl('line');
    line.setAttribute('x1', String(PAD_L));
    line.setAttribute('x2', String(VB_W - PAD_R));
    line.setAttribute('y1', String(y));
    line.setAttribute('y2', String(y));
    line.setAttribute('class', 'profile-gridline');
    svg.appendChild(line);
    const label = svgEl('text');
    label.setAttribute('x', String(PAD_L - 6));
    label.setAttribute('y', String(y + 3));
    label.setAttribute('class', 'profile-axis-label');
    label.setAttribute('text-anchor', 'end');
    label.textContent = `${Math.round(elev)}m`;
    svg.appendChild(label);
  }

  // Section boundaries.
  for (const boundary of boundaries) {
    const x = xForKm(boundary.km);
    const line = svgEl('line');
    line.setAttribute('x1', String(x));
    line.setAttribute('x2', String(x));
    line.setAttribute('y1', String(PAD_T));
    line.setAttribute('y2', String(VB_H - PAD_B));
    line.setAttribute('class', 'profile-boundary');
    svg.appendChild(line);
    const label = svgEl('text');
    label.setAttribute('x', String(x));
    label.setAttribute('y', String(PAD_T - 4));
    label.setAttribute('class', 'profile-boundary-label');
    label.setAttribute('text-anchor', 'middle');
    label.textContent = boundary.label;
    svg.appendChild(label);
  }

  // Faint fill under the whole curve, then coloured per-band strokes on top.
  const fillPoints = profile.map(([km, elev]) => `${xForKm(km)},${yForElev(elev)}`);
  const fill = svgEl('path');
  fill.setAttribute(
    'd',
    `M${xForKm(0)},${yForElev(minElev)} L${fillPoints.join(' L')} L${xForKm(totalKm)},${yForElev(minElev)} Z`,
  );
  fill.setAttribute('class', 'profile-fill');
  svg.appendChild(fill);

  for (const band of bands) {
    const points = profile.filter(([km]) => km >= band.startKm - 0.01 && km <= band.endKm + 0.01);
    if (points.length < 2) continue;
    const path = svgEl('path');
    path.setAttribute('d', `M${points.map(([km, elev]) => `${xForKm(km)},${yForElev(elev)}`).join(' L')}`);
    path.setAttribute('class', 'profile-line');
    path.style.stroke = band.color;
    svg.appendChild(path);
  }

  // km axis ticks.
  for (const frac of [0, 0.5, 1]) {
    const km = totalKm * frac;
    const label = svgEl('text');
    label.setAttribute('x', String(xForKm(km)));
    label.setAttribute('y', String(VB_H - PAD_B + 18));
    label.setAttribute('class', 'profile-axis-label');
    label.setAttribute('text-anchor', frac === 0 ? 'start' : frac === 1 ? 'end' : 'middle');
    label.textContent = formatKm(km, 0);
    svg.appendChild(label);
  }

  // Hover: a guide line + dot + readout, and the map marker.
  const hoverLine = svgEl('line');
  hoverLine.setAttribute('class', 'profile-hover-line');
  hoverLine.setAttribute('y1', String(PAD_T));
  hoverLine.setAttribute('y2', String(VB_H - PAD_B));
  hoverLine.style.display = 'none';
  const hoverDot = svgEl('circle');
  hoverDot.setAttribute('class', 'profile-hover-dot');
  hoverDot.setAttribute('r', '4');
  hoverDot.style.display = 'none';
  svg.append(hoverLine, hoverDot);

  const readout = el('div', 'profile-readout');
  readout.hidden = true;

  function onMove(clientX: number): void {
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0) return;
    const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    const km = frac * totalKm;
    const [pointKm, elev] = nearestElevation(profile, km);
    const x = xForKm(pointKm);
    const y = yForElev(elev);
    hoverLine.setAttribute('x1', String(x));
    hoverLine.setAttribute('x2', String(x));
    hoverLine.style.display = '';
    hoverDot.setAttribute('cx', String(x));
    hoverDot.setAttribute('cy', String(y));
    hoverDot.style.display = '';
    readout.hidden = false;
    readout.textContent = `${formatKm(pointKm)} · ${formatM(elev)}`;

    const coord = coordAtKm(hoverSegments, pointKm);
    if (coord) ctx.mapLayers?.setHoverMarker(coord);
  }

  svg.addEventListener('mousemove', (e) => onMove(e.clientX));
  svg.addEventListener('mouseleave', () => {
    hoverLine.style.display = 'none';
    hoverDot.style.display = 'none';
    readout.hidden = true;
    ctx.mapLayers?.setHoverMarker(null);
  });

  wrap.append(svg, readout);
  return wrap;
}
