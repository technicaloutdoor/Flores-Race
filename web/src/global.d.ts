export {};

declare global {
  interface Window {
    /** Resolves once the map has fired its first 'idle' event. Read by scripts/screenshot.mjs. */
    __mapIdle?: Promise<void>;
  }
}
