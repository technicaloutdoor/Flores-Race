import { describe, expect, it } from 'vitest';
import { defaultRouteId, routeAllowedForMode } from './visibility.ts';
import type { Route } from './types.ts';

function route(id: string, audience: Route['audience']): Route {
  return {
    id,
    name: id,
    audience,
    anchors: [],
    segments: [],
    status: 'concept',
    target_km_range: [0, 0],
  };
}

// Mirrors the real routes.json order this feature depends on: network-routed variants before their
// hand-sketched counterparts, Traverse before Ultra.
const routes: Route[] = [
  route('r-traverse-remote', ['stakeholder', 'scout']),
  route('r-ultra-remote', ['stakeholder', 'scout']),
  route('r-traverse', ['stakeholder', 'scout', 'public']),
  route('r-ultra', ['stakeholder', 'scout']),
];

describe('defaultRouteId', () => {
  it('picks the first route (in list order) whose audience includes the mode', () => {
    expect(defaultRouteId(routes, 'stakeholder')).toBe('r-traverse-remote');
    expect(defaultRouteId(routes, 'scout')).toBe('r-traverse-remote');
  });

  it('skips routes not allowed for the mode, even earlier in the list', () => {
    // Only r-traverse (3rd in the list) allows 'public'.
    expect(defaultRouteId(routes, 'public')).toBe('r-traverse');
  });

  it('returns null when no route allows the mode', () => {
    expect(defaultRouteId([route('r-solo', ['scout'])], 'public')).toBeNull();
  });

  it('returns null for an empty route list', () => {
    expect(defaultRouteId([], 'stakeholder')).toBeNull();
  });
});

describe('routeAllowedForMode', () => {
  it('treats null (no route selected) as always allowed', () => {
    expect(routeAllowedForMode(routes, null, 'public')).toBe(true);
  });

  it('is true when the route exists and its audience includes the mode', () => {
    expect(routeAllowedForMode(routes, 'r-traverse-remote', 'scout')).toBe(true);
  });

  it('is false when the route exists but its audience excludes the mode', () => {
    expect(routeAllowedForMode(routes, 'r-traverse-remote', 'public')).toBe(false);
  });

  it('is false when the route id is not in the list at all', () => {
    expect(routeAllowedForMode(routes, 'r-nope', 'stakeholder')).toBe(false);
  });
});
