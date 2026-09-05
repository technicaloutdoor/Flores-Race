// Story mode: fly section by section with the narrative in an overlay card (ARCHITECTURE.md §7.3,
// BRIEF panel 4). Stakeholder and public modes only — scout mode has real work to do, not a slideshow.

import type { Route, Section, SegmentFeature } from '../data/types.ts';
import { bboxOf, segmentsInSection } from '../data/derive.ts';
import { flyToBbox } from '../map/fit.ts';
import { renderMarkdown } from '../lib/markdown.ts';
import { el } from './ui.ts';
import type { PanelContext } from './context.ts';

const FLY_DURATION_MS = 2500;

export function isStoryAvailable(mode: PanelContext['state']['mode']): boolean {
  return mode === 'stakeholder' || mode === 'public';
}

interface StoryState {
  ctx: PanelContext;
  sections: Section[];
  route: Route | undefined;
  resolvedSegments: SegmentFeature[];
  index: number;
  card: HTMLElement;
  keyHandler: (e: KeyboardEvent) => void;
}

let active: StoryState | null = null;

/** `getCtx` is called fresh at click time (not once at button-creation time), so the story always
 * starts from whatever route/mode/bundle is current, even though the button itself is built once
 * during header setup before the map or bundle exist yet. */
export function createPlayButton(getCtx: () => PanelContext): HTMLButtonElement {
  const button = el('button', 'btn btn-accent', 'Play story');
  button.type = 'button';
  button.title = 'Fly through the route section by section with the narrative.';
  button.addEventListener('click', () => start(getCtx()));
  return button;
}

function start(ctx: PanelContext): void {
  stop();

  const sections = ctx.routeStore
    .getSections()
    .filter((s) => ctx.state.mode !== 'public' || s.public)
    .sort((a, b) => a.order - b.order);
  if (sections.length === 0) {
    window.alert('No sections are published for story mode yet.');
    return;
  }

  const routes = ctx.routeStore.getRoutes().filter((r) => r.audience.includes(ctx.state.mode));
  const route =
    (ctx.state.routeId ? ctx.routeStore.getRoute(ctx.state.routeId) : undefined) ?? routes[0];
  const resolvedSegments = route
    ? route.segments.map((id) => ctx.getSegment(id)).filter((s): s is SegmentFeature => Boolean(s))
    : [];

  const card = el('div', 'story-overlay');
  ctx.map.getContainer().appendChild(card);

  const keyHandler = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight') next();
    else if (e.key === 'ArrowLeft') prev();
    else if (e.key === 'Escape') stop();
  };
  document.addEventListener('keydown', keyHandler);

  active = { ctx, sections, route, resolvedSegments, index: 0, card, keyHandler };
  showSection(0);
}

function stop(): void {
  if (!active) return;
  document.removeEventListener('keydown', active.keyHandler);
  active.card.remove();
  active = null;
}

function next(): void {
  if (!active) return;
  showSection(Math.min(active.index + 1, active.sections.length - 1));
}

function prev(): void {
  if (!active) return;
  showSection(Math.max(active.index - 1, 0));
}

function showSection(index: number): void {
  if (!active) return;
  active.index = index;
  const section = active.sections[index]!;
  const { ctx, route, resolvedSegments } = active;

  const segsInSection = route ? segmentsInSection(section, route, resolvedSegments) : [];
  const bbox = segsInSection.length
    ? bboxOf(segsInSection)
    : bboxOf(
        section.highlight_pois
          .map((id) => ctx.routeStore.getPoi(id))
          .filter((p): p is NonNullable<typeof p> => Boolean(p)),
      );
  flyToBbox(ctx.map, bbox, { padding: 80, duration: FLY_DURATION_MS });

  active.card.replaceChildren();
  const header = el('div', 'story-header');
  header.append(
    el('span', 'story-index', `${index + 1} / ${active.sections.length}`),
    el('h3', undefined, section.title),
  );
  const closeButton = el('button', 'story-close', '✕');
  closeButton.type = 'button';
  closeButton.setAttribute('aria-label', 'Close story mode');
  closeButton.addEventListener('click', stop);
  header.appendChild(closeButton);
  active.card.appendChild(header);

  if (section.subtitle) active.card.appendChild(el('p', 'tagline', section.subtitle));

  const story = el('div', 'story');
  story.appendChild(renderMarkdown(section.story));
  active.card.appendChild(story);

  const nav = el('div', 'story-nav');
  const prevButton = el('button', 'btn', '← Prev');
  prevButton.type = 'button';
  prevButton.disabled = index === 0;
  prevButton.addEventListener('click', prev);
  const nextButton = el('button', 'btn btn-accent', 'Next →');
  nextButton.type = 'button';
  nextButton.disabled = index === active.sections.length - 1;
  nextButton.addEventListener('click', next);
  nav.append(prevButton, nextButton);
  active.card.appendChild(nav);
}
