# ADR-0003: MapLibre GL with free tiles and no API keys

**Status:** Accepted

**Context**
The application must work offline and without API keys or vendor lock-in. Team members are in remote areas with inconsistent connectivity. Basemap tiles and terrain hillshade should load from free public services with proper attribution.

**Decision**
Use MapLibre GL JS (OSM-derived, bundled from npm, not CDN-loaded) for vector map rendering. Basemaps come from free raster tile services: OpenTopoMap (default for scouts), OpenStreetMap, and Esri World Imagery. Hillshade and optional 3D terrain are sampled from free AWS Terrarium tiles. No proprietary keys, no CDN, no vendor tie-in.

**Consequences**
- Zero dependency on tile service availability; team can fork and self-host forever.
- MapLibre is built into the bundle, so it works offline if tiles are pre-cached (Phase 2 PWA).
- Attribution is baked into the app and auto-generated from `meta.json`.
- Free services may have rate limits and coverage gaps; Esri imagery is limited to daytime viewing.

**Alternatives considered**
1. *Mapbox GL with a token:* Proprietary; requires a key management and API account.
2. *Leaflet + raster-only tiles:* No vector rendering of our own data; harder to style dynamically.
3. *Google Maps:* Requires key; vendor lock-in; expensive at scale.
