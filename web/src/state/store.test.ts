import { describe, expect, it } from 'vitest';
import { createStore, selectionFromId, selectionTypeFromId } from './store.ts';

describe('createStore', () => {
  it('set() replaces the whole state and notifies subscribers with (next, previous)', () => {
    const store = createStore({ count: 0 });
    const seen: Array<[number, number]> = [];
    store.subscribe((state, previous) => seen.push([state.count, previous.count]));

    store.set({ count: 5 });

    expect(store.getState().count).toBe(5);
    expect(seen).toEqual([[5, 0]]);
  });

  it('patch() shallow-merges without touching untouched keys', () => {
    const store = createStore({ a: 1, b: 'x' });
    store.patch({ a: 2 });
    expect(store.getState()).toEqual({ a: 2, b: 'x' });
  });

  it('subscribe() returns an unsubscribe function that stops further notifications', () => {
    const store = createStore({ n: 0 });
    let calls = 0;
    const unsubscribe = store.subscribe(() => calls++);

    store.patch({ n: 1 });
    unsubscribe();
    store.patch({ n: 2 });

    expect(calls).toBe(1);
    expect(store.getState().n).toBe(2);
  });
});

describe('selectionTypeFromId / selectionFromId', () => {
  it('infers the selection type from the id prefix', () => {
    expect(selectionTypeFromId('s-ruteng-reo-a')).toBe('segment');
    expect(selectionTypeFromId('p-kelimutu')).toBe('poi');
    expect(selectionTypeFromId('n-ruteng')).toBe('node');
    expect(selectionTypeFromId('r-traverse')).toBeNull();
  });

  it('builds a Selection object only for a recognised prefix', () => {
    expect(selectionFromId('p-kelimutu')).toEqual({ type: 'poi', id: 'p-kelimutu' });
    expect(selectionFromId('unknown-id')).toBeNull();
  });
});
