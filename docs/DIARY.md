# Project diary and memory

This document is the memory of the Flores Race Planner project across sessions of the assistant.
It survives sessions because it lives in the repository. **Read it fully at the start of every
session; update it before the last commit of every session** (see `CLAUDE.md`).

Rules for keeping it useful:

* Dated entries. Facts with the command or file that produced them. No marketing.
* Never delete history. Mark a decision superseded and point to the newer one.
* Write down doubts and rejected options, not only conclusions: the next session needs to know
  what was considered, not just what was chosen.
* Keep the **State** and **Open questions** sections current; they are what a new session reads
  when it has five minutes.

---

## 1. State of the project (updated 2026-09-05, session 1)

| Item | State |
|---|---|
| Repository | `technicaloutdoor/Flores-Race`, public. `main` holds only a stub README (created as a PR base; the repo was empty). |
| Work branch | `claude/flores-bike-race-viz-e53qim`, 17 commits, all CI-green. Draft PR #1 open against `main`. |
| Design docs | `ARCHITECTURE.md`, `docs/data-model.md`, `docs/route-concept.md`, `docs/ai-workflow.md`, `docs/adr/0001…0005`, `docs/scouting-protocol.md`, `docs/deployment.md`, `README.md`, `pipeline/README.md`. |
| Data (`data/`) | 44 nodes, 78 POIs, 10 sections, 4 route variants, 228 segments (46 hand-sketched concept corridors, 182 network-routed candidates). Validation: 0 errors. Gazetteer cross-check: nodes 37 confirmed / 0 wrong; POIs 53 confirmed / 1 wrong (a known false positive). |
| Pipeline (`pipeline/`) | fetch_overture, fetch_dem + dem, fetch_boundaries, fetch_naturalearth, check_terrain_tiles, common, validate, build_network, route_candidates, build_profiles, build_web_data, apply_patch, crosscheck_gazetteer. 178 tests pass. |
| Web app (`web/`) | Vite + TypeScript + MapLibre, three modes, 103 tests, typecheck and build clean, screenshots of all modes reviewed. |
| CI | `validate.yml` (PR + push) green on every commit. `deploy.yml` needs GitHub Pages enabled by the owner (Settings → Pages → Source: GitHub Actions); not yet enabled. |
| Course numbers (network-routed, remote profile, 10 m climbing threshold) | Traverse ≈1,340 km, ≈32,800 m climbing, 59% unpaved, ≈45 km estimated hike-a-bike. Ultra ≈1,390 km, ≈35,900 m. Hand-sketched corridors ≈1,220 km (their climbing figure is meaningless; the app shows n/a). |
| Not committed (ephemeral) | Raw data caches: SRTM tiles (207 MB), Overture extract (≈90 MB of GeoJSONL), track graph (≈90 MB), screenshots. Recreate with `pipeline/bootstrap_cache.sh` into `.cache/`. |
| Ownership | Owner: rico@technicaloutdoor.com (GitHub `technicaloutdoor`). |

---

## 2. Mission (the owner's brief, essentials)

An adventure bike race on Flores in the spirit of the Silk Road Mountain Race: hard, remote, on small
forgotten tracks and farmers' routes, with cultural and historical connections to the land, real
hike-a-bike, volcanoes, highlands and untouched beaches; 1,000–2,000 km; unforgettable. The tool is
internal for now (stakeholders + scouting team) and may get a public face later. The owner asked for
the architecture to be designed by the most capable reasoning model and for cheaper models to do
the work that does not need heavy reasoning.

---

## 3. Decision log (with the reasoning)

Format: id, date, decision, why, alternatives considered, status.

**D-001 · 2026-09-05 · Static site, git as the database.** No backend, no keys, no costs; every
change is a reviewable pull request; the whole planning state clones to a laptop for offline use.
Alternatives: hosted database (Supabase), Google My Maps, a CMS. Rejected for now because the team is
small and the data volume is tiny; a `RouteStore` interface leaves the door open. Status: active.

**D-002 · 2026-09-05 · Segment graph with variants and statuses.** The course = ordered *anchors*;
between consecutive anchors, *candidate segments* with variant letters and a status vocabulary
(`concept → desk-checked → scouted-go | scouted-no-go | needs-recheck → confirmed`). Route variants
are ordered segment lists; totals are always derived. Why: scouting is about alternatives, and
stakeholder numbers must never be typed by hand. Status: active.

**D-003 · 2026-09-05 · MapLibre GL bundled from npm, free tiles, no API keys.** OpenTopoMap, Esri
World Imagery, OSM raster; AWS terrarium tiles for hillshade and 3D. CDNs are blocked in the build
sandbox, so bundling was also a practical necessity. Glyphs come from the public MapLibre demo font
server (works in real browsers; not in the sandbox). Status: active.

**D-004 · 2026-09-05 · Overture Maps on S3 as the track-network source.** Overpass, Geofabrik and
the OSM API are blocked from the sandbox; Overture's GeoParquet on S3 is reachable and can be read with
HTTP range requests and row-group pruning on the `bbox` column: the whole island in 45 s, 660 MB
transferred, 43,088 road/track segments. Caveats learned: `road_surface` is null on 88% of segments;
the `connectors` list is flattened to ids (positions reconstructed from vertices); one-way is in
`access_restrictions`, not `road_flags`; 55 ferry segments have `subtype=water` and must be dropped.
Status: active.

**D-005 · 2026-09-05 · Anchors first, candidates second, humans third.** Route design starts from a
human-ordered anchor list; the pipeline proposes k alternatives per pair under three cost profiles
(`remote`, `rideable`, `direct`); humans accept, reject or trace. Computed candidates never overwrite
a segment a human touched. Status: active.

**D-006 · 2026-09-05 · Detour cap of 2.0× direct for adopted remote candidates.** The remote profile
sent Reo → Pota on a 144 km loop for a 50 km hop. Rather than only softening penalties, the route
chain now refuses any candidate longer than twice the pair's shortest candidate and falls back in
precedence order. Class penalties were also softened (tertiary 1.5, secondary 2.2, primary 2.8,
trunk 4.0; remoteness coefficient 0.06). Doubt: the cap is a blunt tool; a per-pair human override
would be better once scouts have opinions. Status: active.

**D-007 · 2026-09-05 · Climbing uses smoothing plus a 10 m hysteresis threshold.** SRTM noise on
50 m samples inflated ascent (35 m/km on real roads, 67 m/km on sketches). Measured on the real
candidates: 5 m still left the best route above 30 m/km; 10 m gives ≈24–30 m/km, plausible for
Flores. Alternatives: bigger smoothing windows (flatten real passes), Copernicus DEM (reachable,
better quality; not done yet). Status: active; revisit with GPS tracks from scouting.

**D-008 · 2026-09-05 · Computed routes are the default view; sketches stay as reference.** The
hand-drawn corridors were produced by an agent, not by a human designer, and one fixer step made
them "wander" to hit target lengths. They are honest as *indicative shapes* only, so the app shows
their climbing as n/a and opens on the network-routed variant. Consideration: replacing the
sketches entirely was tempting, but the data model deliberately keeps a human corridor per pair and
the team may want to redraw them by hand. Status: active.

**D-009 · 2026-09-05 · Candidate geometry simplified to 5 m; stable variant lettering.** Full
Overture resolution made `segments.geojson` 30 MB; 5 m simplification gives 7.4 MB with no visible
change. Variant letters for regenerable candidates are recomputed from *surviving* features only, so
re-running a second route over shared pairs keeps the first route's segment ids valid. Status: active.

**D-010 · 2026-09-05 · Anchors get a straight connector leg to the nearest mapped way.** Anchors
snap up to 2.5 km to the graph; the validator requires endpoints within 300 m of nodes and route
chains must meet. The straight leg makes the off-network approach visible instead of hiding it.
Status: active.

**D-011 · 2026-09-05 · `public` mode is a presentation filter, not a security boundary.** The
repository is public; anything in `data/` is on the internet. Recommendation to the owner: make the
repository private during planning, or keep sensitive material out of `data/`. A public build flag
strips non-public features at build time. Status: active, owner decision pending.

**D-012 · 2026-09-05 · Model tiering.** Architecture, route concept, verification arbitration and
final review by the top tier; code, research and reviews by the mid tier; schemas, docs, merges and
inventories by the small tier. Applied throughout session 1 (see §7). Status: active.

**D-013 · 2026-09-05 · Verification by independent lenses, then one fixer.** Every geographic fact
is challenged by agents with different lenses (geo-plausibility against DEM and land mask;
independent sources; narrative/cultural/safety). Only survivors become `verified`. Status: active.

**D-014 · 2026-09-05 · Offline gazetteer cross-check as the primary coordinate check.** The
session's web-search budget (≈200 searches) ran out during curation, leaving the source lenses
blind. Matching names against Overture places, peaks, water and village polygons turned out to be a
*better* check than web snippets for this island: it found Mataloko and the Mengeruda hot spring
10 km off, Aimere and Wai Sano 9 km off, and the Wae Rebo trailhead villages inverted. Status:
active; run `pipeline/crosscheck_gazetteer.py` after every curation pass.

**D-015 · 2026-09-05 · Repository memory.** `CLAUDE.md` + this diary + `.claude/AGENT-BRIEF.md` +
`.claude/workflows/` so that every new session starts with the same knowledge and the same agent
method. Status: active (created at the owner's request at the end of session 1).

---

## 4. Environment and tooling knowledge

Sandbox (Claude Code on the web, remote container, 4 CPUs, 15 GB RAM, ≈30 GB disk):

| Host | Reachable | Use |
|---|---|---|
| `registry.npmjs.org`, `pypi.org`, `raw.githubusercontent.com`, `media.githubusercontent.com`, `fonts.googleapis.com` | yes | dependencies, Natural Earth, geoBoundaries |
| `overturemaps-us-west-2.s3.amazonaws.com`, `elevation-tiles-prod.s3.amazonaws.com`, Copernicus DEM / ESA WorldCover / Sentinel-2 COG buckets on S3 | yes | network, terrain, future land cover and imagery |
| Tile servers (OSM, OpenTopoMap, Esri), CDNs (unpkg, cdnjs, jsdelivr), `demotiles.maplibre.org`, Overpass, Geofabrik, Nominatim, Wikipedia, Wikidata, `fonts.gstatic.com` | **no** (403 at the proxy) | browser-side only; screenshots in the sandbox use `base=none` and show no labels |

Practical lessons:

* `WebSearch` works but has a **per-session budget of about 200 searches**. In session 1 three
  curators spent it all; the verification lenses got nothing. Ration it: facts that matter, not
  coordinates (use the gazetteer). `WebFetch` is blocked for almost everything.
* The Bash tool's working directory persists between calls; a `cd web && …` leaves later commands in
  `web/`. Use absolute paths.
* Node's `fetch` needs `NODE_USE_ENV_PROXY=1`; Python `requests` honours the proxy automatically.
  Never disable TLS; never unset `HTTPS_PROXY`.
* Playwright: Chromium at `/opt/pw-browsers` (`chromium-1194`), do not run `playwright install`.
* The terrain tiles' HGT files include **bathymetry**: clamp negative elevations to 0 on land.
* GitHub: the `gh` CLI is absent; use the GitHub MCP tools. An empty repository has no default
  branch until the first push; a PR needs a base, hence the stub `main`.
* Stop hooks nag about uncommitted files; commit in coherent units, not to silence the hook.
* A full multi-agent build of this size took ≈3.4 h wall clock and ≈4.1 M agent tokens (20 agents,
  2 concurrent). Budget sessions accordingly.

---

## 5. Data knowledge (what we learned about Flores from the data)

Corrections made after the gazetteer cross-check (all recorded in `sources`):

* **Mataloko** (and its seminary) is on the Trans-Flores east of Bajawa at ≈121.052, −8.824; the
  curated point was 11 km north. **Mengeruda hot spring** (Soa) is at ≈121.087, −8.709.
* **Aimere** town cluster (port, clinic, bank, mosque) is at ≈120.857, −8.843; the curated point
  was 20 km east near the Inerie south coast.
* **Wai Sano** volcano (903 m) and the **Sano Nggoang** lake sit in the same caldera at ≈120.02,
  −8.72; the lake had been placed 9 km north. The route anchor now sits on the lake shore; the
  kecamatan capital is Werang 8 km north.
* **Dintor** is the coastal village (≈120.308, −8.846, the community lodge), **Denge** the trailhead
  (≈120.302, −8.808), **Wae Rebo** above it (≈120.284, −8.770). The trail climbs north-west from
  Denge; the first curation had Denge north of Wae Rebo.
* **Riung** ≈121.029, −8.419; **Wolobobo** hill ≈120.981, −8.835; **Gurusina** ≈120.991, −8.896;
  **Wologai** traditional village ≈121.823, −8.709; **Watublapi** ≈122.313, −8.698; **Talibura**
  ≈122.517, −8.545 (kecamatan office cluster); Cunca Rami and Cunca Wulang waterfalls moved 3–5 km.

Known ambiguities to settle in the field: **Tololela** (placed at a homestay, unverified);
**Penggajawa** blue-stone beach vs. village centre (≈5 km apart, both kept); **Kelimutu** point is
the lakes, not the higher neighbouring summit Kelibara 1.4 km away (do not "snap" it); **Nggela**,
**Luba**, **Blidit** have no independent record.

Hazards: **Lewotobi Laki-laki** erupted violently in November 2024 with fatalities and repeatedly in
2025; alert levels change, so `hazard_level` texts are dated and section 10 keeps the north-coast
corridor as primary. Check PVMBG before every planning milestone.

Data gaps: OpenStreetMap knows Flores' roads far better than its footpaths (tracks + paths ≈1,740 km
of 15,193 km); most computed pairs have 0–25% track/path share. The remoteness layer shows where
mapped tracks exist; the rest is field work.

---

## 6. Route design considerations

* The Traverse concept (Labuan Bajo → Larantuka, 10 sections, 37 anchors) routed over the real
  network lands at ≈1,340 km without forcing, inside the 1,120–1,540 km target. Good sign: the
  concept is geographically coherent.
* The Ultra as sketched adds only ≈50 km. The concept's loop estimates (+120–250 km) were
  optimistic. To reach 1,600–1,900 km the Ultra needs new anchors (north-coast Riung → Mbay by the
  coast and the plateau, an Inerie full circuit, a Kelimutu–Egon ridge link, or an Adonara/Lembata
  epilogue by ferry). Adding anchors to `routes.json` and re-running the generator is all it takes.
* The remote profile's low track share suggests the real "forgotten tracks" are not mapped. The
  scouting priority list in `docs/route-concept.md` (north coast Reo → Pota → Riung water; cultural
  checkpoints; Wae Rebo onward trail; Inerie shoulder; Lewotobi corridor; ridge crossings) stands.
* Ascent figures will only become trustworthy with ridden GPS tracks; keep the threshold decision
  (D-007) open until then.

---

## 7. The agent system (how work is split, what it cost, what to reuse)

Roles used in session 1 (tiers per `docs/ai-workflow.md`):

| Job | Tier | Notes |
|---|---|---|
| Architecture, data model, route concept, verification arbitration, final decisions | top | written directly, no delegation |
| Overture extraction, network graph, route candidates, pipeline core, web scaffold and panels, integration, reviews, fixers, gazetteer tool | mid | one agent per well-scoped job with an explicit file-ownership list |
| DEM/boundaries fetch, schemas + types, docs (ADRs, protocol, deployment, READMEs), merges | small | fast and cheap; check their output |

What worked: precise specs with exact paths and acceptance checks; file ownership per agent; a
shared brief file every agent reads first; verification lenses returning a structured findings
schema so a fixer can act mechanically; offline checks that need no network.

What did not: letting three curators burn the whole web-search budget; a fixer that "redrew"
sketches with a synthetic wander generator to satisfy length constraints (looked plausible, was
fiction: prefer honest gaps over invented geometry); agents in parallel on the same file (avoided by
the ownership rule, but watch the `pipeline/requirements.txt` appends).

Reusable assets in the repository: `.claude/AGENT-BRIEF.md` (agent preamble), `.claude/workflows/`
(verification and review-fix templates; they take the model tier values as `args.tiers` at
invocation because no repository file may name a model), `pipeline/bootstrap_cache.sh` (recreate
the cache).

---

## 8. Open questions and next steps (priority order)

1. **Owner decisions:** make the repository private for the planning phase? Enable GitHub Pages
   (Settings → Pages → Source: GitHub Actions) and merge PR #1.
2. **Ultra variant:** add anchors for real loops, regenerate, set an honest target range.
3. **Scouting season 1:** use scout mode, export GPX per segment, follow `docs/scouting-protocol.md`;
   the first patches and GPX tracks will also calibrate the climbing threshold (D-007).
4. **Better DEM:** Copernicus 30 m is reachable from S3; swap it in `dem.py` behind the same API and
   compare ascent numbers.
5. **Bundle size:** `segments.geojson` ≈7.4 MB and `profiles.json` ≈4 MB are served on every load;
   lazy-load candidate variants and per-segment profiles when the team notices slowness.
6. **Web-search verification** of the still-`approximate` features once a session has budget:
   prioritise cultural sites and hazards, not coordinates.
7. **Public teaser build** (`--public-build` / `VITE_PUBLIC_BUILD=1`) when the organisers decide.
8. **Offline field mode** (PWA, cached tiles for the scouting corridor) after the first field trip.

---

## 9. Session log

### 2026-09-05 · Session 1 · bootstrap (≈5.5 h)

Asked: design the architecture with the most capable model, build an online visualisation for
stakeholders and the scouting team, use cheaper models where heavy reasoning is not needed; then
(end of session) create this persistent memory.

Done, in order: environment probing (network policy, reachable data hosts) → architecture, data
model, route concept, tiering policy written by the top tier → feasibility scouts on cheaper tiers
(Overture extraction, DEM and boundaries) → a 20-agent build workflow (schemas and types; three
regional curators; merge; course design; five verification lenses; fixer; pipeline core; web
scaffold and panels; docs; integration with CI workflows; two adversarial reviews; review fixer) →
track graph builder and route candidate generator → offline gazetteer cross-check and coordinate
corrections → network-routed route variants with detour cap, stable lettering, simplification and
anchor legs → climbing hysteresis, network layer with remoteness → UI polish (default route, island
fit, honest ascent) → PR #1 description → this memory (CLAUDE.md, diary, agent brief and workflow
templates moved from the scratchpad into `.claude/`).

Verified: validate 0 errors; 178 pipeline tests; 103 web tests; typecheck and build; screenshots of
all modes at desktop and phone sizes; CI green on every commit.

Left open: see §8. The hourly PR check-in routine created in this session will keep re-checking PR #1
until it is merged or closed.
