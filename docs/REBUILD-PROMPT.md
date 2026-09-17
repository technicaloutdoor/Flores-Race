# Rebuild prompt

Everything below the rule is a single, self-contained prompt for a capable coding assistant (one that
can run code, install packages, use a browser and, ideally, spawn sub-agents) to rebuild this project
from scratch or to continue it. It condenses the whole first design-and-build session: intent,
architecture, data contract, pipeline behaviour, app behaviour, the course concept, the verification
method, the working method with model tiers, environment lessons and acceptance criteria. Copy it whole.

---

# Build the Flores Race Planner

## 0. Access, reference and how to build online

* **Reference implementation (public):** https://github.com/technicaloutdoor/Flores-Race
  * Work branch with the full build: `claude/flores-bike-race-viz-e53qim`
  * Pull request with the complete description and test plan: https://github.com/technicaloutdoor/Flores-Race/pull/1
  * Once GitHub Pages is enabled on that repository (Settings → Pages → Source: *GitHub Actions*) the
    app deploys to https://technicaloutdoor.github.io/Flores-Race/ on every push to `main`.
  * Read these files first if you have repository access: `ARCHITECTURE.md`, `docs/DIARY.md` (the
    project memory: every decision with its reasoning, environment quirks, open questions),
    `docs/data-model.md`, `docs/route-concept.md`, `.claude/AGENT-BRIEF.md`, `pipeline/README.md`.
* **Your task:** rebuild an equivalent project in a repository of your own (or continue this one if you
  are given write access). You may reuse ideas and structure freely; say explicitly which files you
  copied and which you rewrote.
* **Build online, no local machine required:** the project is a static site plus a Python pipeline.
  It builds in GitHub Actions (workflows included: validation on every pull request, deployment to
  GitHub Pages on `main`) and in any cloud development environment (GitHub Codespaces or similar).
  Requirements: Node 22 with npm, Python 3.11 with pip, outbound HTTPS. **No API keys of any kind**;
  every data source and every map tile service used is free and public.
* **Data sources to fetch at build time (all reachable without credentials):**
  * Overture Maps GeoParquet on S3: `https://overturemaps-us-west-2.s3.amazonaws.com/release/<version>/theme=<theme>/type=<type>/*.parquet` (list `release/` to find the latest version).
  * AWS Terrain Tiles: SRTM 1-arc-second HGT at `https://elevation-tiles-prod.s3.amazonaws.com/skadi/S09/S09E121.hgt.gz` (and the neighbours S08/S09 × E119…E122); terrarium PNG tiles at `https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png`.
  * geoBoundaries ADM2 for Indonesia (CC BY 4.0), served through Git LFS: `https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/IDN/ADM2/geoBoundaries-IDN-ADM2_simplified.geojson`.
  * Natural Earth 10 m GeoJSON from `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/`.
  * Browser-side only (the team's browsers, not the build): OpenTopoMap, OpenStreetMap and Esri World Imagery raster tiles, MapLibre demo glyphs.

## 1. Who you are and what this is

You are the architect and lead builder of a planning and visualisation tool for an ultra-distance,
self-supported adventure bike race across the island of **Flores (Nusa Tenggara Timur, Indonesia)**,
in the spirit of the Silk Road Mountain Race. The race must be hard and remote, use small forgotten
tracks and farmers' routes, have cultural and historical connections with the land, include real
hike-a-bike, visit volcanoes, highlands and untouched beaches, measure **1,000–2,000 km**, and be
unforgettable.

The tool serves three audiences from one code base:

| Audience | Needs | App mode |
|---|---|---|
| Stakeholders (partners, local government, sponsors, communities) | the vision on one screen: island, candidate course, highlights, honest numbers (km, climbing, % unpaved, hike-a-bike), a story per section, how far planning has progressed | `stakeholder` |
| Scouting team | every candidate segment with alternatives, what is known vs guessed, elevation profiles, surface classes, water and resupply, the raw track network, GPX in/out, a way to record verdicts in the field | `scout` |
| Public (later) | a teaser: island, spirit, coarse route, highlights; nothing sensitive | `public` |

**Working policy requested by the owner:** design the architecture and make every judgement call with
your most capable reasoning model; delegate code generation, research and reviews to a mid-tier model;
delegate schemas, documentation, formatting and inventories to a small fast model. If you can spawn
sub-agents, do so; if not, still work in the phases below.

## 2. Principles that are not negotiable

1. **Static first, zero operations.** A static site on GitHub Pages. No servers, no databases, no keys.
2. **Git is the database.** Every route, segment, point of interest and scouting verdict is a file in
   `data/`; changes are pull requests. The planning state clones to a laptop for offline use.
3. **Two layers of truth, never blurred.** Everything carries a `status` and a `confidence`. A concept
   line is drawn differently from a scouted line. The UI never presents a guess as a fact.
4. **Provenance on every feature** (`sources`, `geometry_source`).
5. **Field ready:** low bandwidth, GPX export, URL-shareable state, edits kept locally and exported.
6. **Reproducible derivations:** everything under `web/public/data/` is generated by the pipeline; nobody
   hand-edits it.
7. **Open data, open licences,** attribution shown in the app (OpenStreetMap contributors via Overture,
   ODbL; OpenTopoMap CC-BY-SA; Esri World Imagery terms; SRTM public domain; geoBoundaries CC BY 4.0;
   Natural Earth public domain).
8. **Honest numbers.** Totals are always derived from the selected segments, never typed. Where a number
   is meaningless (climbing along a hand-sketched corridor) show `n/a` and say why.
9. **No model identifiers, vendor names or session links** in any file pushed to the repository.

## 3. Deliverables (repository layout)

```
<repo>/
├── ARCHITECTURE.md              system design (audiences, principles, overview diagram, layout, components,
│                                data model summary, route computation model, hosting/privacy, environment
│                                notes, roadmap, ADR index)
├── CLAUDE.md (or AGENTS.md)     instructions the assistant loads every session: read the diary first, update
│                                it last, tiering policy, checks before pushing, rules
├── README.md                    quick start, repository map, licences, status
├── docs/
│   ├── DIARY.md                 project memory: state, decision log with reasoning, environment and data
│   │                            quirks, route considerations, agent method, open questions, session log
│   ├── data-model.md            field-by-field contract (below)
│   ├── route-concept.md         the course concept (below) and its computed status
│   ├── scouting-protocol.md     how the field team records and submits verdicts (printable checklist)
│   ├── deployment.md            Pages setup, public build flag, privacy warning, custom domain
│   ├── ai-workflow.md           model tiering policy and where the method lives
│   ├── REBUILD-PROMPT.md        this prompt
│   └── adr/0001…0005            static-first; segment graph; MapLibre + free tiles; Overture on S3; tiering
├── data/                        canonical, human-edited
│   ├── nodes.geojson  pois.geojson  segments.geojson  sections.json  routes.json  scouting/*.md
├── schemas/                     JSON Schema 2020-12 for every data file + the scouting patch
├── pipeline/                    Python 3.11, pure-Python geospatial stack (shapely, pyproj, numpy, pyarrow,
│   │                            networkx, jsonschema, pyyaml; no GDAL)
│   ├── fetch_overture.py  fetch_dem.py  dem.py  fetch_boundaries.py  fetch_naturalearth.py
│   ├── build_network.py  route_candidates.py  build_profiles.py  build_web_data.py
│   ├── validate.py  apply_patch.py  crosscheck_gazetteer.py  bootstrap_cache.sh  common.py
│   ├── tests/  requirements.txt  README.md
├── web/                         Vite + TypeScript (strict) + MapLibre GL JS, no UI framework, no CDN
│   ├── src/{main.ts, state/, data/, map/, panels/, lib/}  public/data/ (generated bundle)  scripts/screenshot.mjs
├── .claude/                     AGENT-BRIEF.md, workflows/ (verify-data, review-fix), README.md
└── .github/workflows/           validate.yml (PR + push), deploy.yml (Pages on main)
```

## 4. Data contract (`docs/data-model.md`, mirrored by `schemas/` and `web/src/data/types.ts`)

Conventions: WGS84 GeoJSON `[lon, lat]` with at most 6 decimals; stable kebab-case ids with type prefixes
`n-`, `p-`, `s-`, `sec-NN-`, `r-`; English `name` plus optional `local_name`; `confidence` ∈
{`verified`, `approximate`, `unverified`}; `sources` (URLs, `field:YYYY-MM-DD`, `map:overture`);
`public` boolean defaulting to false; fields marked *derived* are written only by the pipeline.

* **nodes.geojson** (Point): `id`, `name`, `kind` ∈ {start, finish, checkpoint, town, village, junction,
  trailhead, port, airport}, `resupply` ∈ {none, minimal, basic, full}, `water` ∈ {none, unreliable,
  reliable}, `sleep` ∈ {none, homestay, guesthouse, hotel}, `notes`, `confidence`, `sources`, `public`,
  `elevation_m` *(derived)*.
* **pois.geojson** (Point): `id`, `name`, `local_name`, `category` ∈ {volcano, crater-lake, lake,
  traditional-village, beach, hot-spring, waterfall, cave, heritage, viewpoint, market, port, airport,
  national-park, weaving, religious, hazard, forest, savanna, rice-terrace, other}, `summary` (≤ 300
  chars), `story` (markdown), `race_relevance` ∈ {anchor, highlight, resupply, hazard, context},
  `access` ∈ {road, track, trail, boat, unknown}, `hike_a_bike`, `cultural_protocol`, `elevation_m`,
  `hazard_level` (dated text), `confidence`, `sources`, `public`, `image`, `image_credit`.
* **segments.geojson** (LineString): `id` = `s-<from>-<to>-<variant>` (node ids without `n-`),
  `name`, `from_node`, `to_node`, `variant` `^[A-Z]$`, `status` ∈ {concept, desk-checked, scouted-go,
  scouted-no-go, needs-recheck, confirmed}, `geometry_source` ∈ {concept-sketch, overture-route,
  gpx-field, manual-trace}, `character` ∈ {paved, gravel, dirt, singletrack, hab, mixed, unknown},
  `est_hab_km`, `difficulty` 1–5, `remoteness` 1–5, `direction_note`, `water_points[]`,
  `resupply_notes`, `hazards[]`, `cultural_notes`, `open_questions[]`, `scouting[]` (entries with
  `date`, `team`, `verdict` ∈ {go, no-go, partial}, `notes`, `gpx`, `photos[]`), `route_profile` ∈
  {remote, rideable, direct} when computed, `public`, `sources`; *derived*: `stats` {`length_km`,
  `ascent_m`, `descent_m`, `min_elev_m`, `max_elev_m`, `unpaved_pct`, `profile_ref`}, `surface_mix`,
  `class_mix`.
* **sections.json** (array, ordered): `id`, `order`, `title`, `subtitle`, `from_node`, `to_node`,
  `theme[]` ⊂ {volcano, highland, coast, culture, forest, savanna, history}, `story` (markdown),
  `highlight_pois[]`, `target_km` [min, max], `hab_expected` ∈ {low, medium, high},
  `scouting_priority` 1–3, `open_questions[]`, `public`.
* **routes.json** (array): `id`, `name`, `tagline`, `description`, `audience[]` ⊂ {stakeholder, scout,
  public}, `anchors[]` (ordered node ids; drives candidate generation), `segments[]` (ordered segment
  ids; consecutive segments must chain `to_node → from_node`), `status` ∈ {concept, in-scouting,
  confirmed}, `target_km_range`, `time_limit_days`, `notes`; *derived* `stats` plus `hab_km` and
  `segments_by_status`.
* **scouting/*.md**: YAML front matter (`date`, `team`, `segments`, `verdict`, `gpx`) + free text.
* **Scouting patch** (exported by the app, applied by `apply_patch.py`): `{version, created, author,
  segments: {id: {scouting-owned fields…, scouting_append: [...]}}, nodes: {id: {resupply|water|sleep|notes}},
  new_pois: [Feature]}`. A patch may never change geometry or ids.
* **Generated bundle** (`web/public/data/`): nodes, pois, segments (stats filled, 5 m simplified),
  sections, routes (stats filled), `profiles.json` `{id: [[km, m], …]}` (≤ 400 points per segment,
  concatenated per route), `regencies.geojson`, `network.geojson.gz` (built in CI, not committed),
  `meta.json` (build time, Overture release, sources with licences → `attribution[]`, counts).

Status vocabulary shared everywhere: `concept → desk-checked → scouted-go | scouted-no-go | needs-recheck → confirmed`.

## 5. Pipeline: stages, exact behaviours, hard-won gotchas

All stages: `argparse` CLIs with `--out`, idempotent, cache downloads under a git-ignored `.cache/`,
pretty-printed GeoJSON sorted by id, 6-decimal coordinates, geodesic lengths via `pyproj.Geod`.

1. **fetch_overture.py** — read the latest Overture release straight from S3 over HTTPS with **Range
   requests** (`requests` + a file-like wrapper handed to `pyarrow.parquet.ParquetFile`); prune row
   groups with the footer statistics of the `bbox` struct (xmin/xmax/ymin/ymax) for bbox
   `119.70, −9.00, 123.10, −8.00`; then a row-level bbox filter. Extract `transportation/segment`
   (id, subtype, class, subclass, names.primary → `name`, road_surface, road_flags,
   access_restrictions, connectors, sources), `transportation/connector`, `places/place`,
   `base/land` (peaks and volcanoes), `base/water` (lakes, springs, hot springs, waterfalls),
   `divisions/division_area` (country ID; regencies, localities), optional `base/land_use`. Write
   GeoJSONL per type plus `manifest.json`. Expect ≈660 MB transferred, ≈100k features, under a minute.
   Gotchas: 55 ferry segments have `subtype=water` and null class (drop them); `road_surface` is null
   on ≈88% of segments; the `connectors` list may be flattened to ids only (recompute positions from
   vertices); one-way lives in `access_restrictions`, not `road_flags`.
2. **fetch_dem.py + dem.py** — 8 HGT tiles (S08/S09 × E119–E122), 3601×3601 big-endian int16, row 0 is
   north, void −32768; a `DEM` class with bilinear `elevation(lon, lat)` and `sample_line(coords,
   step_m)`. **Tiles contain bathymetry: clamp negative values to 0 on land.** Sanity: Kelimutu
   (121.82, −8.77) ≈ 1,570 m; Ruteng (120.47, −8.61) ≈ 1,170 m.
3. **fetch_boundaries.py** — the 8 Flores regencies (Manggarai Barat, Manggarai, Manggarai Timur,
   Ngada, Nagekeo, Ende, Sikka, Flores Timur) from geoBoundaries ADM2 (the raw GitHub URL is an LFS
   pointer; use the media URL). Their union is the land mask. Manggarai Barat includes Komodo, Flores
   Timur includes Adonara and Solor, Sikka includes Palue.
4. **build_network.py** — graph nodes = connectors; edges = segment pieces cut at connectors
   (`shapely.ops.substring`); per edge: geodesic length, class, subclass, surface (tag or inferred:
   track/path/footway → unpaved, trunk/primary/secondary → paved, tertiary → unknown-likely-paved,
   else unknown, with `surface_source`), DEM ascent/descent/max grade/mean elevation from 50 m samples,
   and a **remoteness index 1–5** from distance to the nearest trunk/primary/secondary way and to the
   nearest settlement proxy (residential way or place point) using STRtree, thresholds CLI-tunable.
   Honour one-way except on track/path. Outputs: `graph.json.gz` (compact keys), `graph_meta.json`
   (counts, km by class, remoteness histogram, connectivity report with the 10 largest disconnected
   components), `network_web.geojson(.gz)` (one line per original segment, properties id/class/
   subclass/surface/surface_source/name/remoteness/km). Expect ≈39k nodes, ≈48k edges, ≈15,200 km,
   a giant component holding 95% of the km and all five main towns; Labuan Bajo → Larantuka shortest
   path ≈560 km along the north coast.
5. **route_candidates.py** — for a route variant's ordered `anchors`, snap each anchor to the nearest
   graph node (≤ 2.5 km; report off-network anchors loudly), then for each consecutive pair and each
   cost profile run Dijkstra and up to k alternatives by iterative edge penalisation (accept if
   edge-set Jaccard overlap with accepted candidates < 0.6 and length ≤ 1.6× the first). Profiles as
   per-metre multipliers: `remote` (track/path/footway 1.0; unclassified/residential/service 1.2;
   tertiary 1.5; secondary 2.2; primary 2.8; trunk 4.0; remoteness discount `1 − 0.06·(rem−1)`; paved
   ×1.3 except on track/path; grade penalty above 10%), `rideable` (like remote but path 1.4, footway
   2.0, steps 4.0, weaker remoteness discount, paved 1.1 / unpaved 0.9), `direct` (length, trunk 1.2).
   Merge near-identical candidates across profiles (Jaccard > 0.85), keep the most remote profile's
   label. Emit each candidate as a `concept` / `overture-route` segment with computed `character`,
   `est_hab_km` (path/footway/steps km), `difficulty`, `remoteness`, `surface_mix`, `class_mix`,
   `stats`, `water_points` from springs within 300 m, `open_questions` ("verify on the ground").
   **Rules learned the hard way:** (a) simplify candidate geometry to 5 m or the file becomes 30 MB;
   (b) compute variant letters from *surviving* features only, so regenerating a second route over
   shared pairs keeps the first route's ids valid; (c) prepend/append a straight leg from the anchor's
   true coordinate to the snapped node when > 25 m away, so segments start and end exactly at their
   nodes and off-network approaches are visible; (d) `--merge` never touches a segment a human owns
   (anything not `overture-route`+`concept`+no scouting); (e) `--write-route <id>` chains the best
   candidate per pair **but refuses any candidate longer than 2.0× the pair's shortest candidate**
   (the remote profile once proposed a 144 km loop for a 50 km hop) and falls back in precedence order.
6. **build_profiles.py** — sample the DEM every 50 m along each segment, clamp < 0, smooth (5-sample
   median then 5-sample mean), then accumulate ascent/descent with a **10 m hysteresis threshold**
   (SRTM noise otherwise inflates climbing: measured 35 → 30 m/km on real roads; hand-sketched
   corridors that cross terrain freely stay at 60+ m/km whatever you do, which is why the app shows
   `n/a` for them). Write `profiles.json` decimated with Douglas-Peucker, fill segment `stats`, roll up
   route stats.
7. **validate.py** — JSON Schema 2020-12 with a registry for relative `$ref`s, then referential
   integrity: unique ids, segments reference existing nodes, endpoints within 300 m of their nodes
   (warning only for `concept-sketch`), routes chain from first anchor to last, sections reference
   existing nodes and POIs, scouting reports reference existing segments. Exit 1 on errors; `--strict`.
8. **build_web_data.py** — validate → profiles → write the bundle; `--network-web` takes the graph
   builder's layer (preferred, it carries remoteness) else reduces the raw Overture extract;
   `--public-build` drops non-public features; `meta.json` carries `build_time`, `attribution[]`,
   `network_source`, counts, Overture release, git commit (read `.git/HEAD`, do not shell out).
9. **apply_patch.py** — applies a scouting patch to `data/` (allowed fields only, append scouting
   entries, add `new_pois` with generated ids, refuse geometry/id changes, idempotent: skip a
   `new_pois` entry matching an existing POI by slug and within 100 m), `--dry-run`.
10. **crosscheck_gazetteer.py** — the offline coordinate check: build a gazetteer from Overture places,
    named peaks/volcanoes, water features and locality polygons; normalise names (strip Indonesian and
    English generic prefixes: gunung, poco, wolo, ile, keli, danau, pantai, desa, kelurahan, kampung,
    kantor desa, pulau, air panas, air terjun, gua, bukit / mount, lake, beach, village, cave, hot
    springs, waterfall, island); match with word-boundary containment or difflib ≥ 0.85, prefer kinds
    compatible with the feature category, exclude regency-level offices from village matching; verdicts
    confirmed ≤ 1 km (or inside the matched village polygon), plausible 1–3 km, suspect 3–8 km, wrong
    > 8 km, unmatched; DEM elevation check (> 200 m = major) and summit-snap suggestion for volcanoes.
    Markdown + JSON report; exit 0 always.
11. **bootstrap_cache.sh** — recreate `.cache/` in order, skipping existing outputs, then print the
    follow-up commands (validate, route_candidates, build_web_data, crosscheck).

Tests: pytest on synthetic inputs for every stage (splitting, surface inference, remoteness
thresholds, cost maths, alternatives, dedupe, freeze rule, lettering, profile maths, patch refusal and
idempotency, gazetteer normalisation and verdicts). Target ≈180 tests.

## 6. Web application: behaviour to reproduce

Stack: Vite + TypeScript strict, `maplibre-gl` from npm (never a CDN), `geojson` types, vitest,
Playwright for screenshots; fonts via Google Fonts link tags (Inter for UI, Source Serif 4 for
stories); `vite.config.ts` base from `VITE_BASE` (CI sets `/<repo>/`). A tiny typed reactive store
(mode, routeId, selection, basemap, layer visibility, hoverId) mirrored two-way into the URL hash
(`#mode=&route=&sel=&c=lon,lat&z=&base=&layers=`), debounced. A `RouteStore` interface with one
`StaticFileStore` implementation fetching the bundle; `network.geojson.gz` inflated lazily with the
native `DecompressionStream('gzip')` and degrading gracefully on 404.

Map layers, bottom to top: raster basemap (OpenTopoMap default in scout mode; Esri World Imagery;
OSM; and `none`, a warm paper background with the regency polygons filled in sand so the island reads
without tiles, which is also what headless screenshots use); hillshade from terrarium tiles plus a 3D
terrain toggle (exaggeration ≈1.3); regency outlines; the track network (min zoom 9, colour by class
group, **width and opacity increasing with remoteness** so far-from-everything tracks glow); candidate
segments coloured by status (concept grey dashed, desk-checked amber, scouted-go and confirmed greens,
scouted-no-go red, needs-recheck orange), width 4 for the selected route's segments, faded for others,
a casing for the selection; nodes as diamonds; POIs as circles with a canvas-drawn glyph per category
and **a red ring on any POI carrying a `hazard_level`**; labels via a public glyph server; cumulative
km markers; a hover marker that follows the elevation profile.

Panels: header (mode switch with a help tooltip, route selector, basemap, layer toggles collapsible
behind "Map settings" on narrow screens, search over nodes/POIs/segments, share-link copy, GPX export,
a persistent "Data & licences" panel built from `meta.json`). Left sidebar: route selector; headline
tiles for total km, ascent, hike-a-bike km, % unpaved (rounded with a `~` and an explicit concept
notice while ≥ 50% of km is unscouted; ascent `n/a` when every segment is a sketch), a status progress
bar, the ordered section list (title, theme chips, target vs sketched km, hab_expected, priority badge,
expandable story rendered by a small safe markdown renderer), legend. Right inspector: segment
(name, from/to, variant, status pill, geometry source, character, difficulty and remoteness as
5-dot meters, est_hab_km, stats, water, resupply, hazards, cultural notes, open questions, sources as
links, scouting history, sibling variants with a compare toggle), POI (summary, story, elevation,
access, hike-a-bike, cultural protocol, hazard level, sources, **prominent confidence badge**), node
(kind, resupply/water/sleep, notes, elevation); in scout mode the **scouting form** whose edits live in
localStorage as an overlay with an "edited locally" badge and export as `scouting-patch.json`. Bottom:
SVG elevation profile of the route (section boundaries, coloured by status) or of the selected segment
with km/elevation readout linked to the map marker. Story mode (stakeholder and public): fly section to
section with the narrative card, keyboard arrows. GPX 1.1 export (route/section/segment, one trkseg
per segment) and, in scout mode, GPX import drawn magenta with its length.

Modes: `public` filters non-public features at load and hides the form, network, sources and open
questions; `stakeholder` hides the form and defaults network off; `scout` defaults network on above
zoom 10 with the topo basemap. Default route = first route in `routes.json` whose audience includes the
mode; switching mode to one the current route does not allow switches route. First view fits the island
`[[119.75, −9.0], [123.1, −8.05]]` with padding and **re-fits on map resize until the user takes the
camera** (the container reflows after load and a single fit lands on a strip of the island on phones).
Responsive: under 800 px the panels become a tabbed bottom sheet. Everything keyboard reachable
(section headers are buttons with `aria-expanded`). Store patches that change nothing must not
re-render panels (hover must be cheap).

Screenshot script: build, `vite preview`, open each mode at 1440×900 and 390×844 with `base=none`,
wait for map idle, save PNGs, fail on console errors from your own code (ignore tile/glyph network
failures). Look at the PNGs yourself.

## 7. The course concept to encode (then let the network decide)

West → east traverse, **Labuan Bajo (Komodo gateway) → Larantuka (Portuguese heritage, Semana Santa)**,
prevailing dry-season wind from the east-south-east, single stage, self-supported, fixed route,
mandatory checkpoints including **cultural checkpoints** in host villages, ≈13-day limit, dry-season
window late June–September. Design rules: prefer the small track; touch both coasts repeatedly;
hike-a-bike is a feature but must be honest; every section has a reason; villages are hosts, not
scenery (agreements with village councils before any rider passes); respect volcanic exclusion zones;
no rider more than ≈120 km from food and water.

Ten sections (anchors → target km, hike-a-bike expectation): 01 Komodo gate and the Mbeliling forest
(Labuan Bajo → Sano Nggoang → Werang; the largest crater lake, hot springs); 02 Wae Rebo and the
south coast of Manggarai (Werang → Dintor → Denge → Wae Rebo on foot → Todo → Iteng; the
cone-shaped *mbaru niang* houses, permission required; variant B out-and-back); 03 Manggarai highlands
(Iteng → Ruteng → Ranamese/Poco Ranaka → Liang Bua; spider-web *lingko* fields at Cancar, Poco
Mandasawu 2,370 m, the *Homo floresiensis* cave); 04 the forgotten north coast (Liang Bua → Reo → Pota
→ Riung; dry savanna, water is the constraint, scouting priority 1; Seventeen Islands marine park);
05 Ngada: megaliths under Inerie (Riung → Soa/Mengeruda hot springs → Bajawa → Bena, Luba, Tololela,
Gurusina → Aimere; Inerie 2,245 m shoulder as hike-a-bike option; cultural checkpoints); 06 Ebulobo
and the Nagekeo plains (Aimere → Mataloko/Wogo → Boawae/Ebulobo 2,124 m → Mbay; variant B direct to
Nangaroro); 07 the blue-stone coast to Ende (Mbay → Nangaroro/Maukaro → Penggajawa → Ende; Sukarno's
exile 1934–38, Iya volcano); 08 Kelimutu and the Lio country (Ende → Wolotopo → Detusoko → Wologai →
Moni → Kelimutu three lakes 1,639 m at dawn → Wolojita/Nggela ikat villages → Paga/Koka beaches);
09 Sikka and the Portuguese south (Koka → Sikka village 1899 church → Lela → Maumere; Wuring Bajo stilt
village; 1992 earthquake and tsunami); 10 Egon and the far east (Maumere → Watublapi weaving → Egon
1,703 m from Blidit → Waiterang/Talibura → **north of Lewotobi** → Larantuka under Ile Mandiri;
optional final hike-a-bike). Concept total 1,120–1,540 km; an *Ultra* variant with loops
(Ruteng → Borong → Elar → Pota; Bola coast; Inerie circuit) that, as first sketched, adds only ≈50 km
(the concept's loop estimates were optimistic; new anchors are needed to reach 1,600–1,900 km).

Hazards to encode with dated `hazard_level` texts: **Lewotobi Laki-laki** (violent eruptions
November 2024 with fatalities, repeated activity 2025, exclusion radii of several km; north-coast
corridor is primary, check PVMBG monthly, pre-agreed reroute); Ebulobo, Iya, Egon (alert levels
change); Kelimutu gas; wet season November–April; north-coast water scarcity; heat; malaria and dengue
(East Nusa Tenggara has among Indonesia's highest incidence); Trans-Flores traffic; 1992 tsunami
history; dogs. Cultural threads for the stories: *Homo floresiensis*; Ngada *ngadhu* and *bhaga*
shrines; Manggarai *mbaru niang* and *lingko*; Lio and Sikka ikat; Portugal and Rome (Larantuka,
Sikka, Solor fort, Ledalero); Sukarno in Ende; the Bajo of Wuring; Kelimutu's lakes as resting place
of souls.

Coordinates to get right (these were wrong in a first curation and found by the offline check):
Mataloko ≈ 121.052, −8.824 (east of Bajawa, not north); Mengeruda hot spring ≈ 121.087, −8.709;
Aimere town ≈ 120.857, −8.843; Wai Sano volcano (903 m) and Sano Nggoang lake in the same caldera ≈
120.02, −8.72; Dintor (coast) ≈ 120.308, −8.846, Denge (trailhead) ≈ 120.302, −8.808, Wae Rebo ≈
120.284, −8.770 (the trail climbs north-west from Denge); Riung ≈ 121.029, −8.419; Wolobobo hill ≈
120.981, −8.835; Gurusina ≈ 120.991, −8.896; Wologai ≈ 121.823, −8.709; Watublapi ≈ 122.313, −8.698;
Talibura ≈ 122.517, −8.545. Do not snap Kelimutu to the higher summit 1.4 km away (that is Kelibara).

## 8. Verification method (do not skip)

Every geographic fact is generated by one agent and **challenged by independent lenses**, each
returning findings `{feature_id, severity ∈ blocker|major|minor, claim, evidence, suggested_fix}`:
(a) geo-plausibility with the DEM and land mask (on land? summit elevation within 250 m of the DEM
maximum within 1.5 km? beach under 40 m and within 800 m of the coast? highland towns 900–1,300 m?
segment endpoints within 300 m of nodes? no vertex > 1 km offshore? route chains complete?);
(b) independent sources via web search, one to three queries per feature, distance to the stored
coordinate, confirmations listed so the fixer can upgrade `confidence`; (c) narrative, cultural and
safety accuracy of every text with URLs; (d) the **offline gazetteer cross-check** against the Overture
extract, which turned out to be the most reliable coordinate check and needs no network. One fixer
applies blocker and major findings, moves segment endpoints with nodes, re-validates, and records
skipped findings with reasons. Only features confirmed within 1 km by an independent source become
`verified`. Budget lesson: web search may be limited to roughly 200 queries per session; do not let
curation spend it before verification runs; spend it on facts a partner would notice, not on
coordinates.

## 9. Working method: phases, agents, ownership, memory

Phases (each ends with checks green and a commit): (0) probe the environment (which hosts are
reachable) and write the architecture, data model, route concept and tiering policy yourself;
(1) feasibility scouts on cheap tiers (Overture extraction, DEM and boundaries); (2) a build fan-out:
schemas and types (small tier) → three regional curators for nodes and POIs (west: Manggarai regencies;
central: Ngada, Nagekeo, Ende; east: Sikka, Flores Timur), a merger, a course designer for sections,
routes and concept corridors, the verification lenses and a fixer (mid tier), in parallel with pipeline
core, web scaffold then panels, and docs; (3) track graph and route candidates; (4) integration: run
everything, CI workflows, screenshots, small fixes; (5) adversarial review by two lenses (code
correctness; product fit via a real browser run) and a fixer; (6) computed route variants become the
default view; (7) project memory (`CLAUDE.md`, `docs/DIARY.md`, agent brief, workflow templates).

Rules for agents: every agent reads a shared brief file first (hard rules, network reality, paths,
conventions); every agent gets an explicit list of files it owns and never edits outside it; `data/` is
edited by one agent at a time; verification agents are read-only; a fixer writes; structured outputs
for findings so fixers act mechanically; agents return raw data, not prose; prefer honest gaps over
invented geometry (a fixer that "redrew" sketches with synthetic wandering to hit length targets
produced fiction and was corrected). Expect a build of this size to take ≈3.5 h wall clock with two
agents concurrent and ≈4 M agent tokens.

Memory: the diary is read at the start and updated at the end of every session (state, decision log
with reasoning and rejected alternatives, quirks, open questions, session log); the instructions file
enforces it.

## 10. Environment gotchas you will probably meet

Sandboxes often block map tile servers, CDNs, Overpass, Geofabrik, Wikipedia and Wikidata while
allowing npm, PyPI, raw GitHub and AWS S3 buckets: hence Overture instead of Overpass, MapLibre bundled
instead of CDN-loaded, screenshots with `base=none`, and no labels in headless screenshots (glyphs
and font files do not load; not a bug). Node's `fetch` needs the proxy environment enabled; Python
`requests` follows it automatically; never disable TLS verification. Bash working directory may persist
between commands; use absolute paths. An empty GitHub repository has no default branch until the first
push; create a stub `main` so a pull request has a base. Terrain tiles include bathymetry. Overture
flattens nested fields differently between releases: inspect the first lines before coding.

## 11. Definition of done

* `validate.py` reports 0 errors; ≈180 pipeline tests pass; web typecheck, ≈100 unit tests and the
  production build pass; screenshots of all three modes at desktop and phone sizes were looked at.
* Data: ≈44 nodes, ≈78 POIs, 10 sections, concept corridors for every pair, computed candidates for
  every pair, four route variants (network-routed Traverse and Ultra listed first, corridors kept as
  reference); gazetteer cross-check with no `wrong` node.
* Sanity numbers for the network-routed Traverse: ≈1,340 km, ≈32,800 m climbing (≈24 m/km), ≈59%
  unpaved, ≈45 km estimated hike-a-bike; all 37 anchors on the network.
* CI green on every commit; a draft pull request whose description lists what is included, the first
  numbers, reviewer notes (public repository warning, partial web verification, uncommitted cache) and
  a test plan; the diary updated.
* Nothing in the repository names a model, a vendor or a session.

## 12. Hand back

A pull request link, the deployed Pages address (or the one-time setting the owner must enable), the
first computed numbers with their caveats, the list of open questions for the first scouting season
(north-coast water Reo → Pota → Riung; which villages host cultural checkpoints; Wae Rebo onward
trail; Inerie shoulder; Lewotobi corridor; ridge crossings between coasts), and the recommendation to
make the repository private while scouting notes accumulate.
