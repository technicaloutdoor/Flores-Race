/// <reference types="vitest/config" />
import { defineConfig } from 'vite';

// GitHub Pages serves the site under /Flores-Race/; CI sets VITE_BASE accordingly.
// Local dev and preview default to '/'.
const base = process.env.VITE_BASE ?? '/';

export default defineConfig({
  base,
  build: {
    target: 'es2022',
    sourcemap: true,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
