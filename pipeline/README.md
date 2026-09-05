# Pipeline: building the web data from open sources

The pipeline is a sequence of Python scripts that fetch open data, build a routable track network, compute elevation profiles, and bundle everything for the web app. All stages are idempotent (safe to re-run) and cache downloads, so you can interrupt and resume.

## Quick overview

```
fetch_*.py          Download open data from S3 and GitHub
    ↓
build_network.py    Turn Overture segments + connectors into a routable graph
    ↓
build_profiles.py   Sample elevation profiles and compute segment stats
    ↓
validate.py         Check data integrity (schema + referential)
    ↓
build_web_data.py   Simplify geometry for the web and write the bundle
    ↓
web/public/data/    Generated files, committed or built in CI
```

## Raw data locations and caching

Downloaded files are stored in `.cache/` and are **gitignored**:

```
data/
├── .cache/
│   ├── dem/                                    # SRTM HGT tiles (8 × ~7 MB)
│   ├── boundaries/                             # geoBoundaries regencies
│   ├── naturalearth/                           # Natural Earth 10m extracts
│   ├── overture/                               # Overture Maps GeoParquet → GeoJSONL
│   └── network/                                # Routable graph + metadata
└── scouting/                                   # Field reports (git-tracked)
    └── gpx/                                    # Scouting GPX files
```

**Why gitignored:** These files are large (~500 MB for Overture) and reproducible. Re-running the fetch scripts always produces the same data (up to Overture release version). In CI, they are regenerated on each deploy.

## Pipeline stages

### 1. `fetch_dem.py` — Download SRTM elevation tiles

**Purpose:** Fetch 1-arc-second SRTM tiles from AWS for the Flores bounding box.

```bash
python3 pipeline/fetch_dem.py \
  --out data/.cache/dem \
  --tiles HGT1 HGT2 HGT3 HGT4 HGT5 HGT6 HGT7 HGT8
```

**Options:**
- `--out` (default: `raw/dem`) — Output directory for `.hgt` files.
- `--tiles` — Specific tile list; if omitted, defaults to the 8 Flores tiles.
- `-v, --verbose` — Print download progress.

**Output:** 8 gzipped HGT files (~7 MB each); `dem.py` reads them with bilinear interpolation.

**Notes:**
- Tiles include bathymetry (negative values); land profiles clamp these to 0.
- Sanity check: Kelimutu (121.82, -8.77) should be ~1,568 m; Ruteng (120.47, -8.61) ~1,168 m.

---

### 2. `fetch_boundaries.py` — Download geoBoundaries regencies

**Purpose:** Fetch administrative region (ADM2) polygons for the 8 Flores regencies.

```bash
python3 pipeline/fetch_boundaries.py \
  --out data/.cache/boundaries
```

**Options:**
- `--out` (default: `raw/boundaries`) — Output directory.

**Output:** `flores_regencies.geojson` with the 8 regencies (Ende, Flores Timur, Manggarai, Manggarai Barat, Manggarai Timur, Nagekeo, Ngada, Sikka).

**Notes:**
- Manggarai Barat includes the Komodo islands; Flores Timur includes Adonara and Solor.
- Used for the island mask (on-land test) and per-regency statistics.

---

### 3. `fetch_naturalearth.py` — Download Natural Earth context layers

**Purpose:** Fetch populated places, islands, and land outlines at 10 m resolution for context.

```bash
python3 pipeline/fetch_naturalearth.py \
  --out data/.cache/naturalearth
```

**Options:**
- `--out` (default: `raw/naturalearth`) — Output directory.

**Output:**
- `ne_10m_populated_places.geojson` — Populated places (filtered to Flores region).
- `ne_10m_minor_islands.geojson` — Small islands.
- `ne_10m_land.geojson` — Land outlines.

**Notes:**
- Used for context and potential POI verification.
- Public domain (Natural Earth).

---

### 4. `fetch_overture.py` — Download Overture Maps road network

**Purpose:** Extract Overture Maps (OSM-derived) features for the Flores bounding box via Parquet row-group pruning (avoids downloading the full planet).

```bash
python3 pipeline/fetch_overture.py \
  --bbox 119.70,-9.00,123.10,-8.00 \
  --release latest \
  --out data/.cache/overture \
  --themes segment,connector,place,land,water,division_area
```

**Options:**
- `--bbox` — Bounding box as `xmin,ymin,xmax,ymax` (WGS84).
- `--release` (default: `latest`) — Overture Maps release version.
- `--out` (required) — Output directory.
- `--cache` (default: `.cache/overture`) — Cache directory for Parquet footers and row-group metadata.
- `--themes` — Comma-separated list of themes to fetch (default: all).

**Output:** One GeoJSONL file per theme (newline-delimited GeoJSON):
- `segment.geojsonl` — Roads, tracks, paths (subtype=`road`) with class, surface, name, connector ids.
- `connector.geojsonl` — Vertices where segments meet; used to build the graph.
- `place.geojsonl` — Points of interest (populated places, landmarks).
- `land.geojsonl` — Peaks and named landforms.
- `water.geojsonl` — Water features.
- `division_area.geojsonl` — Admin areas.
- `manifest.json` — Metadata (Overture version, download timestamp, feature counts).

**Notes:**
- Uses plain HTTPS Range requests (no boto3) so it works through an HTTP proxy.
- Row-group pruning keeps the download to hundreds of MB instead of a full-planet archive.
- ODbL license (same as OpenStreetMap).

---

### 5. `build_network.py` — Build the routable graph

**Purpose:** Turn Overture segments and connectors into a routable, classified graph with remoteness index.

```bash
python3 pipeline/build_network.py \
  --overture-dir data/.cache/overture \
  --dem-dir data/.cache/dem \
  --regencies data/.cache/boundaries/flores_regencies.geojson \
  --out data/.cache/network \
  --dem-step-m 50 \
  --remote-main-thresholds 20,50 \
  --remote-settlement-thresholds 10,30
```

**Options:**
- `--overture-dir` (required) — Path to `fetch_overture.py` output.
- `--dem-dir` (required) — Path to DEM tiles (from `fetch_dem.py`).
- `--regencies` (required) — Regency GeoJSON (from `fetch_boundaries.py`).
- `--out` (required) — Output directory.
- `--dem-step-m` — Sample DEM every N metres for gradient calculation (default: 50).
- `--remote-main-thresholds` — Distance thresholds (km) for remoteness index from primary/secondary roads (default: `20,50`).
- `--remote-settlement-thresholds` — Distance thresholds (km) from populated places (default: `10,30`).
- `--web-max-gzip-mb` — Max file size for gzip in the web bundle (default: 10).

**Output:**
- `network.graphml` or JSON — Routable graph (nodes = connectors, edges = segment pieces).
- `graph_meta.json` — Metadata (edge counts, class distribution, caveats).
- Various GeoJSONL reports for inspection.

**Notes:**
- Cuts every segment into edges between connectors using the reconstructed `at` fractions.
- Classifies edges by Overture class and surface; flags problematic classes (steps, cycleway, etc.).
- Computes remoteness index per edge for routing cost.
- This is the heaviest computation; re-runs only if `data/nodes.geojson` changes.

---

### 6. `build_profiles.py` — Sample elevation and compute segment stats

**Purpose:** For every segment, sample the DEM along its geometry, smooth, and compute ascent, descent, length, and % unpaved.

```bash
python3 pipeline/build_profiles.py \
  --dem-dir data/.cache/dem \
  --data data \
  --out data/.cache/profiles \
  --step-m 50 \
  --max-profile-points 500
```

**Options:**
- `--dem-dir` (required) — Path to DEM tiles.
- `--data` (default: `data`) — Path to canonical data directory (contains `segments.geojson`, `routes.json`).
- `--out` (required unless `--in-place`) — Output directory for `segments.geojson`, `routes.json`, `profiles.json`.
- `--in-place` — Write back into `--data` instead of `--out` (only for maintainers; the default is to preserve the canonical source).
- `--step-m` (default: 50) — Sample DEM every N metres.
- `--max-profile-points` (default: 500) — Decimate profiles to this many points for the web.

**Output:**
- `segments.geojson` — Copy of input with `stats` fields filled (length_km, ascent_m, descent_m, min/max_elev, unpaved_pct, profile_ref).
- `routes.json` — Copy with rolled-up `stats` per route.
- `profiles.json` — `{ "<segment_id>": [[km, elevation], ...], "<route_id>": [...] }` for elevation display.

**Notes:**
- Applies a 5-sample median filter then 5-sample moving average to SRTM heights to kill noise before computing ascent/descent.
- Never overwrites the canonical `data/` unless `--in-place` is passed (reproducible derivations policy).
- Bathymetry (values < 0) is clamped to 0 for on-land profiles.

---

### 7. `validate.py` — Validate data integrity

**Purpose:** Check the canonical data in `data/` against JSON Schemas and referential integrity (unique ids, segment endpoints match nodes, routes chain segments, etc.).

```bash
python3 pipeline/validate.py \
  --data data \
  --schemas schemas \
  --strict
```

**Options:**
- `--data` (default: `data`) — Path to canonical data directory.
- `--schemas` (default: `schemas`) — Path to schema directory.
- `--strict` — Treat warnings as errors (exit 1 if any warnings).

**Output:** Exit code 0 if valid; 1 if errors (or warnings + `--strict`). Errors printed to stderr.

**Notes:**
- Runs in CI on every PR and before deployment.
- Imported by `build_web_data.py` and `apply_patch.py` to validate before acting.

---

### 8. `build_web_data.py` — Bundle for the web app

**Purpose:** Orchestrate the final bundle: validate, fill elevation_m, simplify geometry, and write `web/public/data/`.

```bash
python3 pipeline/build_web_data.py \
  --dem-dir data/.cache/dem \
  --regencies data/.cache/boundaries/flores_regencies.geojson \
  --overture-dir data/.cache/overture \
  --out web/public/data \
  --public-build
```

**Options:**
- `--dem-dir` (required) — Path to DEM tiles.
- `--regencies` (required) — Regency GeoJSON.
- `--overture-dir` — Path to Overture extract (optional; skips `network.geojson.gz` if absent).
- `--out` (default: `web/public/data`) — Output directory.
- `--data` (default: `data`) — Path to canonical data.
- `--schemas` (default: `schemas`) — Path to schemas.
- `--public-build` — Drop non-public features before writing (fields where `public != true`).

**Output:**
- `nodes.geojson` — Nodes with `elevation_m` filled.
- `pois.geojson` — POIs.
- `segments.geojson` — Segments with simplified geometry (~5 m tolerance) and stats.
- `sections.json`, `routes.json` — With computed stats.
- `profiles.json` — Elevation profiles (one per segment and route).
- `regencies.geojson` — Simplified regency outlines (~30 m tolerance).
- `network.geojson.gz` — Overture network (simplified, gzipped) if available.
- `meta.json` — Build metadata (timestamp, Overture version, sources, license strings, counts).

**Notes:**
- The only script that writes to `web/public/data/`.
- Validates before writing.
- The `--public-build` flag filters features to opt-in only; the repository is still public.

---

### 9. `apply_patch.py` — Apply scouting feedback

**Purpose:** Apply a scouting patch (exported by scouts from the web app) to the canonical data, merging scouting-owned fields.

```bash
python3 pipeline/apply_patch.py \
  --patch scouting-patch.json \
  --data data \
  --dry-run
```

**Options:**
- `--patch` (required) — Path to the scouting-patch JSON file.
- `--data` (default: `data`) — Path to canonical data (will be modified in place unless `--out` is given).
- `--out` — Output directory (if given, write to a copy instead of modifying `--data`).
- `--dry-run` — Print the diff summary; write nothing.
- `--schemas` (default: `schemas`) — Path to schemas.

**Output:** Modified `segments.geojson`, `nodes.geojson`, `pois.geojson` (if `--out` is given).

**Notes:**
- Used by maintainers after scouts export a patch from the web app.
- A patch may only modify scouting-owned fields (status, character, est_hab_km, scouting entries, node resupply/water/sleep, new POIs).
- Geometry changes come as GPX files and are traced by the route designer, not applied via patch.

---

### 10. `route_candidates.py` — Propose candidate segments (planned)

**Purpose:** For each consecutive anchor pair, propose up to k alternatives from the Overture graph using different cost profiles (remote, rideable, direct).

**Status:** Planned (to be implemented; see ARCHITECTURE.md, section 6).

```bash
# Placeholder invocation
python3 pipeline/route_candidates.py \
  --graph data/.cache/network/network.graphml \
  --anchors data/nodes.geojson \
  --routes data/routes.json \
  --dem-dir data/.cache/dem \
  --out data/.cache/candidates \
  --k 3 \
  --profiles remote,rideable,direct
```

---

## Execution order

**Typical development workflow:**

```bash
# 1. Fetch raw data (once, unless sources update)
python3 pipeline/fetch_dem.py --out data/.cache/dem
python3 pipeline/fetch_boundaries.py --out data/.cache/boundaries
python3 pipeline/fetch_naturalearth.py --out data/.cache/naturalearth
python3 pipeline/fetch_overture.py --out data/.cache/overture --bbox 119.70,-9.00,123.10,-8.00 --release latest

# 2. Build the network and profiles
python3 pipeline/build_network.py \
  --overture-dir data/.cache/overture \
  --dem-dir data/.cache/dem \
  --regencies data/.cache/boundaries/flores_regencies.geojson \
  --out data/.cache/network

python3 pipeline/build_profiles.py \
  --dem-dir data/.cache/dem \
  --out data/.cache/profiles

# 3. Validate
python3 pipeline/validate.py --data data --schemas schemas

# 4. Build the web bundle
python3 pipeline/build_web_data.py \
  --dem-dir data/.cache/dem \
  --regencies data/.cache/boundaries/flores_regencies.geojson \
  --overture-dir data/.cache/overture \
  --out web/public/data

# 5. Run the web app
cd web && npm install && npm run dev
```

**After a scouting trip:**

```bash
# 1. Apply the patch (maintainer)
python3 pipeline/apply_patch.py --patch scouting-patch.json --data data

# 2. Re-validate and rebuild
python3 pipeline/build_profiles.py --dem-dir data/.cache/dem --out data/.cache/profiles
python3 pipeline/validate.py --data data --schemas schemas
python3 pipeline/build_web_data.py \
  --dem-dir data/.cache/dem \
  --regencies data/.cache/boundaries/flores_regencies.geojson \
  --overture-dir data/.cache/overture \
  --out web/public/data

# 3. Commit and open a PR
git add -A
git commit -m "Scouting: <section>, <date> — verdict: go on variant A"
```

## Sandbox and network notes

The pipeline runs in a sandbox with restricted outbound access. See ARCHITECTURE.md section 10 for full details.

**Reachable:**
- AWS S3 (Overture, SRTM, Mapzen terrain tiles).
- GitHub (raw.githubusercontent.com, media.githubusercontent.com).
- npm registry, PyPI.
- Google Fonts.

**Blocked:**
- OSM Overpass, OpenTopoMap, Esri tile servers (tile requests come from the browser, not the pipeline).
- CDNs (unpkg, cdnjs, jsdelivr) — hence MapLibre is bundled.
- Wikipedia, Wikidata.

**Implication for development:** If you run the pipeline on your own machine (not in CI), these restrictions do not apply; tile servers and APIs work normally. To test the CI environment locally, use Docker or a VM with proxy filtering.

## References

- See `ARCHITECTURE.md` for the system design and why each stage exists.
- See `docs/data-model.md` for the canonical data schema.
- See `docs/deployment.md` for CI/CD workflows that automate the pipeline.
