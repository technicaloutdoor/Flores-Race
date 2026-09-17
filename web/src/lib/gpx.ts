// GPX 1.1 export/import (ARCHITECTURE.md §7.3, §7.4). Export builds one `<trk>` per segment (each
// with its own `<name>` and a `<desc>` carrying the segment's status, so opening the file in GPS
// software shows which candidate lines are confirmed vs. still concept) inside one `<gpx>` file per
// route/section/segment request. Import is a small hand-written parser rather than `DOMParser`, so
// the same code path is usable — and unit-testable — in both the browser and a plain Node test
// environment with no DOM.

import type { Route, Section, SegmentFeature } from '../data/types.ts';
import { haversineKm } from '../data/derive.ts';

const GPX_NS = 'http://www.topografix.com/GPX/1/1';

const XML_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&apos;',
};

function escapeXml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => XML_ESCAPES[c]!);
}

export interface GpxTrackInput {
  name: string;
  desc: string;
  /** [lon, lat] pairs, as in GeoJSON. */
  coordinates: [number, number][];
}

export interface BuildGpxOptions {
  creator?: string;
  /** File-level `<metadata><name>` — the route or section name for a multi-segment export. */
  metadataName?: string;
}

/** Builds a full GPX 1.1 document: one `<trk>` (with one `<trkseg>`) per input track. */
export function buildGpx(tracks: GpxTrackInput[], options: BuildGpxOptions = {}): string {
  const creator = escapeXml(options.creator ?? 'Flores Race Planner');
  const metadata = options.metadataName
    ? `<metadata><name>${escapeXml(options.metadataName)}</name></metadata>`
    : '';
  const trkXml = tracks
    .map((t) => {
      const points = t.coordinates
        .map(([lon, lat]) => `<trkpt lat="${lat}" lon="${lon}"></trkpt>`)
        .join('');
      return `<trk><name>${escapeXml(t.name)}</name><desc>${escapeXml(
        t.desc,
      )}</desc><trkseg>${points}</trkseg></trk>`;
    })
    .join('');
  return (
    `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<gpx version="1.1" creator="${creator}" xmlns="${GPX_NS}">${metadata}${trkXml}</gpx>`
  );
}

function segmentDesc(segment: SegmentFeature): string {
  const p = segment.properties;
  return `status: ${p.status}; character: ${p.character}; variant ${p.variant}`;
}

export function segmentToGpxTrack(segment: SegmentFeature): GpxTrackInput {
  return {
    name: segment.properties.name,
    desc: segmentDesc(segment),
    coordinates: segment.geometry.coordinates as [number, number][],
  };
}

export function segmentGpx(segment: SegmentFeature): string {
  return buildGpx([segmentToGpxTrack(segment)], { metadataName: segment.properties.name });
}

export function routeGpx(route: Route, segments: SegmentFeature[]): string {
  return buildGpx(segments.map(segmentToGpxTrack), { metadataName: route.name });
}

export function sectionGpx(section: Section, segments: SegmentFeature[]): string {
  return buildGpx(segments.map(segmentToGpxTrack), { metadataName: section.title });
}

/** Triggers a browser download of `content` as `filename` via a Blob object URL — no server, no
 * `<a download>` link left in the page (the object URL is revoked right after the click). */
export function downloadTextFile(filename: string, content: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadGpx(filename: string, gpxXml: string): void {
  downloadTextFile(filename, gpxXml, 'application/gpx+xml');
}

export function downloadJson(filename: string, data: unknown): void {
  downloadTextFile(filename, JSON.stringify(data, null, 2), 'application/json');
}

// --- Import ----------------------------------------------------------------------------------

export interface ParsedGpxTrack {
  name?: string;
  /** [lon, lat] pairs, concatenated across every trk/trkseg in the file, in document order. */
  points: [number, number][];
}

function attrValue(tagAttrs: string, attr: string): string | undefined {
  const re = new RegExp(`${attr}\\s*=\\s*"([^"]*)"|${attr}\\s*=\\s*'([^']*)'`, 'i');
  const m = re.exec(tagAttrs);
  if (!m) return undefined;
  return m[1] ?? m[2];
}

/**
 * Extracts every `<trkpt lat="…" lon="…">` from a GPX (or GPX-ish) XML string and the first
 * `<name>` found, without a full XML parser — this keeps GPX import usable in a plain Node test
 * environment (no `DOMParser`) as well as the browser. Malformed or non-numeric points are
 * skipped rather than thrown; a file with no track points at all yields `{ points: [] }` so the
 * caller can show "no track points found" instead of crashing.
 */
export function parseGpxTrack(xml: string): ParsedGpxTrack {
  const nameMatch = /<name>([^<]*)<\/name>/i.exec(xml);
  const name = nameMatch?.[1]?.trim();

  const points: [number, number][] = [];
  const trkptRe = /<trkpt\b([^>]*)>/gi;
  let match: RegExpExecArray | null;
  while ((match = trkptRe.exec(xml))) {
    const attrs = match[1] ?? '';
    const lat = attrValue(attrs, 'lat');
    const lon = attrValue(attrs, 'lon');
    if (lat === undefined || lon === undefined) continue;
    const latNum = Number(lat);
    const lonNum = Number(lon);
    if (Number.isFinite(latNum) && Number.isFinite(lonNum)) points.push([lonNum, latNum]);
  }

  return name ? { name, points } : { points };
}

/** Total geodesic length of a point sequence, in kilometres, rounded to one decimal. */
export function gpxTrackLengthKm(points: readonly [number, number][]): number {
  let total = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (!a || !b) continue;
    total += haversineKm(a, b);
  }
  return Math.round(total * 10) / 10;
}
