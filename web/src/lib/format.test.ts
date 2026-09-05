import { describe, expect, it } from 'vitest';
import { formatApproxKm, formatApproxM } from './format.ts';

describe('formatApproxKm', () => {
  it('rounds to the nearest step and prefixes a tilde', () => {
    expect(formatApproxKm(1132.09, 10)).toBe('~1,130 km');
  });

  it('defaults to rounding to the nearest 10', () => {
    expect(formatApproxKm(1134)).toBe('~1,130 km');
    expect(formatApproxKm(1136)).toBe('~1,140 km');
  });

  it('returns the dash placeholder for undefined/non-finite input', () => {
    expect(formatApproxKm(undefined)).toBe('—');
    expect(formatApproxKm(Number.NaN)).toBe('—');
  });
});

describe('formatApproxM', () => {
  it('rounds to the nearest step and prefixes a tilde', () => {
    expect(formatApproxM(72863.9, 100)).toBe('~72,900 m');
  });

  it('defaults to rounding to the nearest 100', () => {
    expect(formatApproxM(72864)).toBe('~72,900 m');
  });
});
