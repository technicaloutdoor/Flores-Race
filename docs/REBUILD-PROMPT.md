# Rebuild prompt

Copy everything below the rule into a capable coding assistant (one that can run code, install
packages and use a browser). It asks the assistant to rebuild this kind of tool and to **design its
own route**; it deliberately does not hand over ours.

---

# Build a planning tool for an adventure bike race across Flores

## Access and building online

* Reference implementation (public, for architecture and code only): https://github.com/technicaloutdoor/Flores-Race
  (branch `claude/flores-bike-race-viz-e53qim`, pull request https://github.com/technicaloutdoor/Flores-Race/pull/1).
  **Do not read its `docs/route-concept.md` or its `data/` until your own route is designed**; compare afterwards.
* The app is a static site: it builds in GitHub Actions and deploys to GitHub Pages (repository
  Settings → Pages → Source: GitHub Actions). The reference deploys to
  https://technicaloutdoor.github.io/Flores-Race/ once that setting is on. Any cloud dev environment
  (GitHub Codespaces or similar) works: Node 22, Python 3.11, outbound HTTPS. **No API keys anywhere.**
* Free data, no credentials: Overture Maps GeoParquet on S3
  (`https://overturemaps-us-west-2.s3.amazonaws.com/release/<version>/theme=<theme>/type=<type>/`),
  AWS Terrain Tiles (SRTM HGT under `.../skadi/`, terrarium PNG tiles), geoBoundaries ADM2 for Indonesia
  (via `media.githubusercontent.com`, CC BY 4.0), Natural Earth. Browser-side tiles: OpenTopoMap, OSM,
  Esri World Imagery.

## Mission

An ultra-distance, self-supported adventure bike race on the island of Flores, Indonesia, in the
spirit of the Silk Road Mountain Race: hard, remote, on small forgotten tracks and farmers' routes,
with cultural and historical connections to the land, real hike-a-bike, volcanoes, highlands and
untouched beaches, **1,000–2,000 km**, unforgettable. Build the tool that lets stakeholders see the
vision and numbers, lets the scouting team check route options in the field, and can later get a
public face. Design the architecture with your most capable model; delegate code, research and
reviews to a mid-tier model and schemas, docs and formatting to a small one.

## Design the course yourself

Research the island from open sources and data, then propose your own course: an ordered list of
anchor points (start, finish, checkpoints, key villages), narrative sections with a reason each
(a volcano, a village, a beach, a piece of history), alternatives where you are unsure, and the open
questions scouts must answer. Rules: prefer the small track over any road; touch both coasts
repeatedly; hike-a-bike is welcome but must be quantified honestly; traditional villages are hosts,
not scenery (checkpoints inside a village need the council's agreement; otherwise route around);
respect active-volcano exclusion zones (check the Indonesian volcanology agency's current alert
levels and keep dated hazard notes; Lewotobi in the east has erupted violently since late 2024); plan
for the dry season (June–September), water scarcity on the north coast, heat, malaria; no rider more
than ~120 km from food and water. Present every number as derived and unscouted.

## Principles

Static site, git as the database (every route, segment, point of interest and scouting verdict is a
file; changes are pull requests). Two layers of truth never blurred: every feature carries `status`
and `confidence`, concept lines are drawn differently from scouted ones. Provenance (`sources`,
`geometry_source`) on everything. Field-ready: GPX in and out, URL-shareable state, edits kept locally
and exported. Generated files are never hand-edited. Open data with attribution shown in the app.
Honest numbers: totals derived from selected segments, `n/a` where a number is meaningless. No model
or vendor names in the repository.

## Deliverables

`ARCHITECTURE.md`; an assistant-instructions file that says "read `docs/DIARY.md` first, update it
last"; `docs/DIARY.md` (state, decision log with reasoning, quirks, open questions, session log);
`docs/data-model.md`, `docs/route-concept.md` (yours), `docs/scouting-protocol.md`,
`docs/deployment.md`, ADRs; `data/` (nodes, pois, segments, sections, routes, scouting reports);
`schemas/` (JSON Schema 2020-12); `pipeline/` (Python 3.11, no GDAL) with tests; `web/` (Vite +
TypeScript strict + MapLibre GL from npm, no UI framework, no CDN) with tests and a Playwright
screenshot script; `.github/workflows/` (validate on PR and push; deploy to Pages on `main`); an agent
brief file and reusable verification/review workflow templates.

## Data contract

Ids `n-`, `p-`, `s-<from>-<to>-<variant>`, `sec-NN-`, `r-`; WGS84, 6 decimals; `confidence` ∈
verified | approximate | unverified; `sources[]`; `public` boolean.
* Nodes: kind (start, finish, checkpoint, town, village, junction, trailhead, port, airport), resupply
  (none…full), water (none, unreliable, reliable), sleep, notes, derived elevation.
* POIs: category (volcano, crater-lake, lake, traditional-village, beach, hot-spring, waterfall, cave,
  heritage, viewpoint, market, port, airport, national-park, weaving, religious, hazard, forest,
  savanna, rice-terrace, other), summary ≤ 300 chars, story (markdown), race_relevance, access,
  hike_a_bike, cultural_protocol, elevation_m, dated hazard_level.
* Segments (LineString between two nodes, variants A/B/C…): status `concept → desk-checked →
  scouted-go | scouted-no-go | needs-recheck → confirmed`; geometry_source (concept-sketch,
  overture-route, gpx-field, manual-trace); character; est_hab_km; difficulty and remoteness 1–5;
  water_points, resupply_notes, hazards, cultural_notes, open_questions; scouting[] entries (date,
  team, verdict, notes, gpx, photos); route_profile when computed; derived stats (length, ascent,
  descent, min/max elevation, unpaved %), surface_mix, class_mix.
* Sections: order, title, from/to node, themes, story, highlight POIs, target km range, expected
  hike-a-bike, scouting priority, open questions. Routes: ordered anchors (drive candidate
  generation), ordered segments that must chain, audience, status, target range, derived stats.
* Scouting patch exported by the app: scouting-owned fields and appended entries only; never geometry
  or ids. Generated bundle: the files above with stats filled, `profiles.json`, regencies,
  `network.geojson.gz`, `meta.json` with attribution.

## Pipeline (stages and the gotchas that cost us time)

1. Overture extract straight from S3 with HTTP Range requests and row-group pruning on the `bbox`
   column for bbox 119.70, −9.00, 123.10, −8.00 (segments, connectors, places, land incl. peaks,
   water, division areas); drop ferry segments (`subtype=water`); `road_surface` is mostly null;
   one-way lives in `access_restrictions`; inspect field shapes before coding.
2. SRTM tiles S08/S09 × E119–E122 with a bilinear sampler; **clamp negative values (bathymetry) to 0.**
3. Regency polygons as the land mask (the GitHub raw URL is an LFS pointer; use the media URL).
4. Routable graph: connectors as nodes, segment pieces as edges with geodesic length, class, tagged or
   inferred surface, DEM grades, and a 1–5 remoteness index (distance to main roads and settlements);
   connectivity report; a reduced web layer.
5. Route candidates: snap anchors (report off-network ones), Dijkstra plus penalised alternatives under
   three tunable cost profiles (remote, rideable, direct), merge near-duplicates, emit `concept` /
   `overture-route` segments with computed stats. Cap any adopted candidate at 2× the pair's shortest
   (the remote profile otherwise invents huge loops); simplify geometry to ~5 m; keep variant letters
   stable across re-runs; add a straight leg from an anchor to the nearest mapped way when > 25 m;
   never overwrite a segment a human touched.
6. Profiles: 50 m DEM samples, median+mean smoothing, then a **10 m hysteresis threshold** for
   climbing (SRTM noise otherwise inflates it badly); show climbing as n/a for hand-sketched corridors.
7. Validation (schemas + referential integrity + chaining), web bundle builder with a public-build
   flag, patch applier (idempotent), and an **offline gazetteer cross-check** that matches every
   node/POI name against Overture places, peaks, water and village polygons and reports distance and
   verdict (a first curation had 22 coordinates off by up to 11 km; this check found them without any
   web access). A bootstrap script recreates the uncommitted cache in order.

## Web app

Three modes (`stakeholder`, `scout`, `public`) from one build, state mirrored in the URL hash. Layers:
free raster basemaps plus a tile-free island view (regency polygons on a paper background, also used
for headless screenshots), hillshade and 3D terrain from terrarium tiles, the track network brighter
the more remote, segments coloured by status, nodes, POIs with category glyphs and a red ring on any
active hazard, labels, km markers. Sidebar: route selector, headline tiles (km, climbing, hike-a-bike,
% unpaved, rounded with an explicit concept notice while unscouted), status progress bar, sections
with stories, legend. Inspector: full properties with a prominent confidence badge; in scout mode an
editing form whose changes live in localStorage and export as a scouting patch. Bottom: SVG elevation
profile linked to a map marker. Story fly-through, GPX export and import, search, data-and-licences
panel, responsive bottom sheet on phones, keyboard reachable. Default route = first route allowed for
the mode; first view fits the whole island and re-fits on resize until the user moves the map.

## Verification (mandatory)

Challenge every geographic fact with independent lenses returning structured findings (feature id,
severity, claim, evidence, suggested fix): DEM and land-mask plausibility; independent web sources;
narrative, cultural and safety accuracy; the offline gazetteer. One fixer applies blocker and major
findings and re-validates. Only features confirmed within 1 km by an independent source become
`verified`. Web search may be limited to ~200 queries per session: spend it on facts a local partner
would notice, not on coordinates.

## Working method

Phases: probe the environment → architecture, data model, route concept and tiering by you →
feasibility scouts → build fan-out (schemas; regional curators; merge; course design; verification
lenses and fixer; pipeline core; web scaffold then panels; docs) → graph and candidates → integration
with CI and screenshots → adversarial review (code correctness; product fit in a real browser) and
fixes → computed routes as default view → project memory. Every agent reads a shared brief first and
owns an explicit list of files; `data/` is edited by one agent at a time; verifiers are read-only;
prefer honest gaps over invented geometry. Expect ~3.5 h and several million agent tokens for the
first build.

## Environment gotchas

Sandboxes often block tile servers, CDNs, Overpass, Geofabrik and Wikipedia while allowing npm, PyPI,
raw GitHub and S3: hence Overture instead of Overpass, MapLibre bundled, screenshots without tiles and
without labels. Never disable TLS. Use absolute paths in shells. An empty repository needs a stub
`main` before a pull request can exist.

## Done when

Validation reports 0 errors; pipeline and web tests, typecheck and build pass; screenshots of all
three modes at desktop and phone sizes were looked at; your route variant is complete, every anchor is
on the network and the derived length lies in 1,000–2,000 km; the gazetteer check reports no `wrong`
node; CI is green; a draft pull request describes the work with its caveats; the diary is updated.
Hand back the PR link, the Pages address or the one-time setting to enable, your route's numbers with
caveats, and the open questions for the first scouting season.
