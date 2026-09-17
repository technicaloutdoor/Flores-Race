# Agent brief — Flores Race Planner

Read this fully before doing anything. Then read the design documents named below. This
file is written to be valid in **any** session — it contains no session-specific paths.

## Project

A static web app + Python pipeline to plan an ultra-distance adventure bike race across the
island of Flores (Indonesia). Repository root: `/home/user/Flores-Race`. Design documents
(authoritative):

- `/home/user/Flores-Race/ARCHITECTURE.md` (system design, layers, modes, pipeline stages)
- `/home/user/Flores-Race/docs/data-model.md` (the exact data contract: fields, enums, ids)
- `/home/user/Flores-Race/docs/route-concept.md` (the course concept: sections, anchors, hazards)
- `/home/user/Flores-Race/docs/ai-workflow.md`
- `/home/user/Flores-Race/docs/DIARY.md` — project memory: what was tried, what worked, what
  didn't, across sessions. Read it for context before repeating work; it is maintained
  separately from this brief.

## Before you start: the cache

Raw downloads and everything derived from them live under `/home/user/Flores-Race/.cache/`
(gitignored — never committed, never assumed to exist). A fresh session has an **empty**
`.cache/`. Run `pipeline/bootstrap_cache.sh` first — it is idempotent (safe to re-run,
skips any step whose output already exists) and rebuilds, in order:

- `.cache/dem/` — 8 SRTM `.hgt` tiles. Sampler: `pipeline/dem.py` → `DEM(dir).elevation(lon,
  lat)` and `sample_line(coords, step_m)`. Values below 0 are bathymetry: clamp to 0 for
  anything on land/coast. Sanity check: Kelimutu (121.82,-8.77) ≈ 1568 m; Ruteng
  (120.47,-8.61) ≈ 1168 m.
- `.cache/boundaries/flores_regencies.geojson` — the 8 Flores kabupaten (geoBoundaries, CC
  BY 4.0). Use the union as the "island mask / on-land" test. Note Manggarai Barat includes
  the Komodo islands, Flores Timur includes Adonara and Solor, Sikka includes Palue.
- `.cache/naturalearth/` — Natural Earth extracts (land, minor islands, populated places).
- `.cache/overture/` — output of `fetch_overture.py` for bbox `119.70,-9.00,123.10,-8.00`
  (segment/connector/place/land/water/division_area/land_use `.geojsonl` plus
  `manifest.json`).
- `.cache/network/` — output of `build_network.py`: `graph.json.gz`, `network_web.geojson.gz`
  (+ its `.gz`), `graph_meta.json`.
- `.cache/verify/` — reports from `crosscheck_gazetteer.py` (the offline gazetteer
  cross-check).
- `.cache/screenshots/` — Playwright screenshots taken during integration/review runs.

If any of these directories are missing or empty when you need them, run
`pipeline/bootstrap_cache.sh` (or the one stage you need — read its own `--help` output for
exact flags, do not guess) before proceeding. Do not re-invent a fetch step inline; the
script exists precisely so every session reproduces the same cache the same way.

## Hard rules

1. Do NOT run any `git` command. Do not commit, do not init, do not stash.
2. **File ownership** (see the rule set below) — write only inside the directories your task
   names. Never delete or rewrite files owned by another task. Files under
   `pipeline/fetch_*.py`, `pipeline/dem.py`, `pipeline/check_terrain_tiles.py` are the
   data-fetch scripts: read them, import them, do not rewrite them.
3. No model names, vendor names or session links anywhere in files you write (code
   comments, docs, data). Describe roles ("the route designer", "a research agent") if you
   must.
4. Never disable TLS verification, never unset `HTTPS_PROXY`, never add
   `--no-verify`/`rejectUnauthorized:false`.
5. Never put API keys or tokens anywhere. The app must work with zero keys.
6. Temporary working files that are not a deliverable (scratch scripts, one-off checks,
   intermediate dumps) belong in your own scratchpad directory, never written loose under
   `/tmp`. Your environment tells you that directory's path for this session; it is
   session-scoped, so never hardcode a path to it in a file you commit or hand off.
7. Your final message may be read by an orchestrator program, not a human. Return the
   requested data plainly; no pleasantries.

## File ownership (parallel-agent rule set)

- Every agent/task is given an explicit list of files or directories it owns for that step.
  Write only inside that list. Anything you did not create and were not explicitly told to
  own is read-only to you.
- Never delete or rewrite a file owned by another task that may be running concurrently.
- `data/` (the canonical `nodes.geojson`, `pois.geojson`, `segments.geojson`,
  `sections.json`, `routes.json`) is edited by **at most one agent at a time**. Never fan
  out two parallel tasks that both hold write ownership of `data/*` in the same phase —
  curation/merge/course-design/fix steps that touch `data/` run one after another (a
  barrier or explicit hand-off), never in parallel with each other.
- `schemas/`, `web/src/data/types.ts`, `pipeline/*` (excluding the data-fetch scripts above),
  and `docs/*` each belong to whichever single task was assigned them for that phase; do not
  cross into another task's file list even if it looks related.
- Read-only lenses (verification/review agents) touch nothing — they report findings; only
  a designated fixer agent applies them, and it re-validates before returning.

## Network reality (matters for testing)

Outbound HTTPS goes through a policy proxy. WORKS: `registry.npmjs.org`, `pypi.org`,
`raw.githubusercontent.com`, `media.githubusercontent.com`, `fonts.googleapis.com`, AWS S3
public buckets (`elevation-tiles-prod.s3.amazonaws.com`, `overturemaps-us-west-2.s3.amazonaws.com`,
etc.). BLOCKED (403 at the proxy): tile servers (OpenTopoMap, OSM, Esri, MapTiler), CDNs
(unpkg, cdnjs, jsdelivr), `demotiles.maplibre.org`, Overpass, Wikipedia/Wikidata, Google.

Consequences:

- In the browser of a real team member all tile/glyph URLs work; in a sandbox session
  basemap tiles and MapLibre glyph PBFs will fail to load. That is expected, NOT a bug to
  fix. Test with the app's `basemap=none` option (blank ground + island polygon) so the
  app's own data layers can be screenshot.
- Bundle every JS dependency from npm (Vite); never load a script/style from a CDN.
- `WebSearch` tool works (server-side). `WebFetch` is blocked for most sites. `curl` to
  Wikipedia fails.
- Node fetch needs `NODE_USE_ENV_PROXY=1`; Python `requests` honours the proxy
  automatically.

## Tooling available

Node 22 (`npm`, `pnpm`, `npx`), TypeScript 6, Vite (install locally), Playwright 1.56 with
Chromium at `/opt/pw-browsers` (do not run `playwright install`; set
`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, or use `executablePath:
'/opt/pw-browsers/chromium-1194/chrome-linux/chrome'` if needed — check the folder), Python
3.11 with requests, shapely 2, pyproj, numpy (`pip install` allowed: jsonschema, networkx,
pyarrow, pyyaml...). 4 CPUs, 15 GB RAM.

## Conventions

- GeoJSON: WGS84, `[lon, lat]`, ≤ 6 decimals, pretty-printed with 2-space indent, features
  sorted by id.
- Ids: kebab-case with prefixes `n-`, `p-`, `s-`, `sec-NN-`, `r-` (see data-model.md).
- Python: 3.11, type hints, `argparse` CLIs with `--out`, idempotent, no GDAL, docstrings,
  no prints of huge payloads. Shared helpers go in `pipeline/common.py` (create if missing;
  coordinate with the pipeline task owner by keeping functions small and pure).
- TypeScript: strict mode, ES modules, no `any` unless justified, no UI framework, small
  modules.
- Every file you create must be referenced from somewhere (an import, a doc, a script), no
  orphans.
- Prefer clarity over cleverness: the maintainers are a small race-organising team, not a
  dev shop.
- Before running a pipeline script with flags you're guessing at, run
  `python3 pipeline/<script>.py --help` and read it — several scripts (notably
  `fetch_boundaries.py` and `fetch_naturalearth.py`) take **no** CLI flags at all and write
  to a hardcoded relative path; don't assume every script matches the pattern of its
  neighbours.

## Geographic frame

Island bbox: lon 119.70 … 123.10, lat −9.00 … −8.00 (Flores main island roughly 119.85 …
123.00). Web Mercator, initial view centre ≈ (121.4, −8.6), zoom ≈ 8 for the whole island.
