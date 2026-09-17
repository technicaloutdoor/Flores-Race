// Right inspector: selected segment / POI / node detail, sibling-variant comparison, GPX
// import/export, and (scout mode) the scouting form + overlay export/discard controls.
// ARCHITECTURE.md §7.3, BRIEF panel 2.

import { siblingVariants } from '../data/derive.ts';
import type { NodeFeature, POIFeature, SegmentFeature } from '../data/types.ts';
import { formatKm, formatList, formatM, formatPct, titleCase } from '../lib/format.ts';
import { renderMarkdown } from '../lib/markdown.ts';
import {
  downloadGpx,
  downloadJson,
  gpxTrackLengthKm,
  parseGpxTrack,
  segmentGpx,
} from '../lib/gpx.ts';
import { flyToBbox } from '../map/fit.ts';
import { bboxOf } from '../data/derive.ts';
import {
  clearOverlay,
  getAuthor,
  hasEdit,
  overlayStore,
  overlayToPatch,
  setAuthor,
} from '../state/overlay.ts';
import {
  confidenceBadge,
  dotMeter,
  el,
  emptyState,
  errorState,
  fieldRow,
  localEditBadge,
  sourceList,
  statusPill,
} from './ui.ts';
import { renderScoutForm } from './scoutForm.ts';
import type { PanelContext } from './context.ts';

/** Sibling segment ids currently toggled "on" for the cyan compare highlight. Reset whenever the
 * inspected segment changes (see `render`). */
let compareIds = new Set<string>();
let lastInspectedSegmentId: string | null = null;

interface ImportedTrack {
  name?: string;
  points: [number, number][];
}
let importedGpx: ImportedTrack | null = null;

export function render(container: HTMLElement, ctx: PanelContext): void {
  container.replaceChildren();
  container.appendChild(el('h2', undefined, 'Inspector'));

  if (!ctx.bundleLoaded) {
    container.appendChild(el('p', 'state state-loading', 'Loading…'));
    return;
  }

  if (ctx.state.mode === 'scout') {
    container.appendChild(renderGpxImport(container, ctx));
    container.appendChild(renderOverlaySummary(container, ctx));
  }

  const selection = ctx.state.selection;
  if (!selection) {
    container.appendChild(emptyState('Nothing selected. Click a segment, node or POI on the map, or use search.'));
    return;
  }

  if (selection.type === 'poi') {
    const poi = ctx.routeStore.getPoi(selection.id);
    if (!poi) {
      container.appendChild(errorState(`POI "${selection.id}" was not found in the loaded bundle.`));
      return;
    }
    container.appendChild(renderPoi(poi, ctx));
    return;
  }

  if (ctx.state.mode === 'public') {
    container.appendChild(emptyState('Segment and node detail is not shown in public mode.'));
    return;
  }

  if (selection.type === 'node') {
    const node = ctx.routeStore.getNode(selection.id);
    if (!node) {
      container.appendChild(errorState(`Node "${selection.id}" was not found in the loaded bundle.`));
      return;
    }
    container.appendChild(renderNode(node));
    return;
  }

  const segment = ctx.getSegment(selection.id);
  if (!segment) {
    container.appendChild(errorState(`Segment "${selection.id}" was not found in the loaded bundle.`));
    return;
  }
  if (segment.properties.id !== lastInspectedSegmentId) {
    compareIds = new Set();
    ctx.mapLayers?.setCompare(compareIds);
    lastInspectedSegmentId = segment.properties.id;
  }
  container.appendChild(renderSegment(segment, ctx));

  if (ctx.state.mode === 'scout') {
    const formHost = el('div', 'scout-form-host');
    renderScoutForm(formHost, segment);
    container.appendChild(formHost);
  }
}

// --- GPX import + overlay summary (scout mode only) -------------------------------------------

function renderGpxImport(container: HTMLElement, ctx: PanelContext): HTMLElement {
  const box = el('div', 'panel-box');
  box.appendChild(el('div', 'field-label', 'Compare a ridden GPX track'));

  if (importedGpx) {
    const info = el(
      'p',
      undefined,
      `${importedGpx.name ?? 'Imported track'} — ${formatKm(gpxTrackLengthKm(importedGpx.points))} (${importedGpx.points.length} points)`,
    );
    const clearButton = el('button', 'btn', 'Clear imported track');
    clearButton.type = 'button';
    clearButton.addEventListener('click', () => {
      importedGpx = null;
      ctx.mapLayers?.clearImportedGpx();
      render(container, ctx);
    });
    box.append(info, clearButton);
  } else {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.gpx,application/gpx+xml';
    const status = el('p', 'state state-error');
    status.hidden = true;
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      if (!file) return;
      file
        .text()
        .then((text) => {
          const parsed = parseGpxTrack(text);
          if (parsed.points.length === 0) {
            status.textContent = 'No track points found in that file.';
            status.hidden = false;
            return;
          }
          importedGpx = parsed;
          ctx.mapLayers?.setImportedGpx(parsed.points);
          flyToBbox(ctx.map, bboxOf([{ type: 'Feature', geometry: { type: 'LineString', coordinates: parsed.points }, properties: {} }]), {
            padding: 60,
            duration: 1000,
          });
          render(container, ctx);
        })
        .catch(() => {
          status.textContent = 'Could not read that file.';
          status.hidden = false;
        });
    });
    box.append(input, status);
  }
  return box;
}

function renderOverlaySummary(container: HTMLElement, ctx: PanelContext): HTMLElement {
  const overlay = overlayStore.getState();
  const editedIds = Object.keys(overlay.segments);

  const box = el('div', 'panel-box');
  box.appendChild(el('div', 'field-label', 'Local scouting edits'));
  box.appendChild(
    el('p', undefined, editedIds.length === 0 ? 'No local edits yet.' : `${editedIds.length} segment(s) edited locally.`),
  );

  const authorInput = document.createElement('input');
  authorInput.type = 'text';
  authorInput.placeholder = 'Your initials (patch author)';
  authorInput.value = getAuthor();
  authorInput.addEventListener('change', () => setAuthor(authorInput.value.trim()));
  box.appendChild(authorInput);

  const row = el('div', 'button-row');
  const exportButton = el('button', 'btn btn-accent', 'Export scouting patch');
  exportButton.type = 'button';
  exportButton.disabled = editedIds.length === 0;
  exportButton.addEventListener('click', () => {
    const patch = overlayToPatch(overlayStore.getState(), getAuthor() || 'unknown');
    downloadJson('scouting-patch.json', patch);
  });

  const discardButton = el('button', 'btn', 'Discard all local edits');
  discardButton.type = 'button';
  discardButton.disabled = editedIds.length === 0;
  discardButton.addEventListener('click', () => {
    if (!confirm(`Discard local edits for ${editedIds.length} segment(s)? This cannot be undone.`)) return;
    overlayStore.set(clearOverlay());
    render(container, ctx);
  });

  row.append(exportButton, discardButton);
  box.appendChild(row);
  return box;
}

// --- POI ---------------------------------------------------------------------------------------

function renderPoi(poi: POIFeature, ctx: PanelContext): HTMLElement {
  const p = poi.properties;
  const box = el('div', 'inspector-detail');
  const title = el('h3', undefined, p.name);
  box.appendChild(title);
  if (p.local_name) box.appendChild(el('p', 'tagline', p.local_name));

  const badges = el('div', 'chip-row');
  badges.append(el('span', 'chip', titleCase(p.category)), confidenceBadge(p.confidence));
  box.appendChild(badges);

  box.appendChild(el('p', undefined, p.summary));

  if (ctx.state.mode === 'public') {
    const rows = [fieldRow('Elevation', p.elevation_m !== undefined ? formatM(p.elevation_m) : ''), fieldRow('Access', titleCase(p.access))];
    for (const r of rows) if (r) box.appendChild(r);
    return box;
  }

  if (p.story) {
    const story = el('div', 'story');
    story.appendChild(renderMarkdown(p.story));
    box.appendChild(story);
  }

  const rows = [
    fieldRow('Elevation', p.elevation_m !== undefined ? formatM(p.elevation_m) : ''),
    fieldRow('Access', titleCase(p.access)),
    fieldRow('Race relevance', titleCase(p.race_relevance)),
    fieldRow('Hike-a-bike', p.hike_a_bike ? 'Yes' : ''),
    fieldRow('Cultural protocol', p.cultural_protocol ?? ''),
  ];
  for (const r of rows) if (r) box.appendChild(r);

  if (p.hazard_level) {
    const hazard = el('p', 'hazard-note', `Hazard: ${p.hazard_level}`);
    box.appendChild(hazard);
  }

  if (p.image) {
    const img = document.createElement('img');
    img.src = p.image;
    img.alt = p.name;
    box.appendChild(img);
    if (p.image_credit) box.appendChild(el('p', 'image-credit', p.image_credit));
  }

  box.appendChild(el('div', 'field-label', 'Sources'));
  box.appendChild(sourceList(p.sources));

  return box;
}

// --- Node ----------------------------------------------------------------------------------

function renderNode(node: NodeFeature): HTMLElement {
  const p = node.properties;
  const box = el('div', 'inspector-detail');
  box.appendChild(el('h3', undefined, p.name));
  if (p.local_name) box.appendChild(el('p', 'tagline', p.local_name));
  box.appendChild(confidenceBadge(p.confidence));

  const rows = [
    fieldRow('Kind', titleCase(p.kind)),
    fieldRow('Resupply', titleCase(p.resupply)),
    fieldRow('Water', titleCase(p.water)),
    fieldRow('Sleep', titleCase(p.sleep)),
    fieldRow('Elevation', p.elevation_m !== undefined ? formatM(p.elevation_m) : ''),
    fieldRow('Notes', p.notes ?? ''),
  ];
  for (const r of rows) if (r) box.appendChild(r);

  box.appendChild(el('div', 'field-label', 'Sources'));
  box.appendChild(sourceList(p.sources));
  return box;
}

// --- Segment -------------------------------------------------------------------------------

function renderSegment(segment: SegmentFeature, ctx: PanelContext): HTMLElement {
  const p = segment.properties;
  const box = el('div', 'inspector-detail');

  const titleRow = el('div', 'chip-row');
  titleRow.appendChild(el('h3', undefined, p.name));
  if (hasEdit(overlayStore.getState(), p.id)) titleRow.appendChild(localEditBadge());
  box.appendChild(titleRow);

  const fromNode = ctx.routeStore.getNode(p.from_node)?.properties.name ?? p.from_node;
  const toNode = ctx.routeStore.getNode(p.to_node)?.properties.name ?? p.to_node;
  box.appendChild(el('p', 'tagline', `${fromNode} → ${toNode} · variant ${p.variant}`));

  const badges = el('div', 'chip-row');
  badges.appendChild(statusPill(p.status));
  box.appendChild(badges);

  const rows = [
    fieldRow('Geometry source', titleCase(p.geometry_source)),
    fieldRow('Character', titleCase(p.character)),
    fieldRow('Est. hike-a-bike', formatKm(p.est_hab_km)),
  ];
  for (const r of rows) if (r) box.appendChild(r);

  const meters = el('div', 'field-row');
  meters.append(el('span', 'field-label', 'Difficulty'), dotMeter(p.difficulty));
  box.appendChild(meters);
  const meters2 = el('div', 'field-row');
  meters2.append(el('span', 'field-label', 'Remoteness'), dotMeter(p.remoteness));
  box.appendChild(meters2);

  if (p.stats) {
    const stats = p.stats;
    box.appendChild(el('div', 'field-label', 'Stats'));
    const statRows = [
      fieldRow('Length', formatKm(stats.length_km)),
      fieldRow('Ascent / descent', `+${formatM(stats.ascent_m)} / -${formatM(stats.descent_m)}`),
      fieldRow('Elevation range', `${formatM(stats.min_elev_m)} – ${formatM(stats.max_elev_m)}`),
      fieldRow('Unpaved', formatPct(stats.unpaved_pct)),
    ];
    for (const r of statRows) if (r) box.appendChild(r);
  }

  const infoRows = [
    fieldRow('Water points', formatList(p.water_points)),
    fieldRow('Resupply notes', p.resupply_notes ?? ''),
    fieldRow('Hazards', formatList(p.hazards)),
    fieldRow('Cultural notes', p.cultural_notes ?? ''),
  ];
  for (const r of infoRows) if (r) box.appendChild(r);

  if (ctx.state.mode !== 'public' && p.open_questions?.length) {
    box.appendChild(el('div', 'field-label', 'Open questions'));
    const ul = el('ul');
    for (const q of p.open_questions) ul.appendChild(el('li', undefined, q));
    box.appendChild(ul);
  }

  box.appendChild(el('div', 'field-label', 'Scouting history'));
  if (p.scouting?.length) {
    const list = el('ul', 'scouting-history');
    for (const entry of p.scouting) {
      const li = el('li');
      li.appendChild(el('span', `verdict verdict-${entry.verdict}`, titleCase(entry.verdict)));
      li.appendChild(document.createTextNode(` ${entry.date} · ${entry.team}`));
      if (entry.notes) li.appendChild(el('div', 'scouting-notes', entry.notes));
      list.appendChild(li);
    }
    box.appendChild(list);
  } else {
    box.appendChild(emptyState('No field verdicts recorded yet.'));
  }

  box.appendChild(el('div', 'field-label', 'Sources'));
  box.appendChild(sourceList(p.sources));

  const siblings = siblingVariants(segment, ctx.getAllSegments());
  if (siblings.length) {
    box.appendChild(el('div', 'field-label', 'Sibling variants'));
    const list = el('ul', 'sibling-list');
    for (const sibling of siblings) {
      const li = el('li');
      const label = el('button', 'link-button', `${sibling.properties.name} (${sibling.properties.variant})`);
      label.type = 'button';
      label.addEventListener('click', () => ctx.actions.select({ type: 'segment', id: sibling.properties.id }));
      li.appendChild(label);
      li.appendChild(statusPill(sibling.properties.status));

      const compareToggle = document.createElement('input');
      compareToggle.type = 'checkbox';
      compareToggle.checked = compareIds.has(sibling.properties.id);
      const compareLabel = el('label', 'compare-toggle');
      compareLabel.append(compareToggle, document.createTextNode(' compare'));
      compareToggle.addEventListener('change', () => {
        if (compareToggle.checked) compareIds.add(sibling.properties.id);
        else compareIds.delete(sibling.properties.id);
        ctx.mapLayers?.setCompare(compareIds);
      });
      li.appendChild(compareLabel);
      list.appendChild(li);
    }
    box.appendChild(list);
  }

  const gpxButton = el('button', 'btn', 'Export segment GPX');
  gpxButton.type = 'button';
  gpxButton.addEventListener('click', () => downloadGpx(`${p.id}.gpx`, segmentGpx(segment)));
  box.appendChild(gpxButton);

  return box;
}
