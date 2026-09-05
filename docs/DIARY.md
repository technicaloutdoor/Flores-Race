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

## 1. State of the project (updated 2026-09-05, session 2)

| Item | State |
|---|---|
| Repository | `technicaloutdoor/Flores-Race`, public. `main` holds only a stub README (created as a PR base; the repo was empty). |
| Work branches | `claude/flores-bike-race-viz-e53qim` (session 1, draft PR #1 against `main`). Session 2 continues on `claude/flores-race-track-brochure-rx3rog`, branched from PR #1's head, with its own draft PR based on the PR #1 branch. |
| Design docs | `ARCHITECTURE.md`, `docs/data-model.md`, `docs/route-concept.md`, `docs/ai-workflow.md`, `docs/adr/0001…0005`, `docs/scouting-protocol.md`, `docs/deployment.md`, `README.md`, `pipeline/README.md`. |
| Data (`data/`) | 46 nodes (session 2 added `n-gurusina`, `n-sewowoto` for the Inerie circuit), 78 POIs, 10 sections, 5 route variants (session 2 added `r-ultra-plus`), 272 segments (46 sketches, 226 network-routed candidates; session 2 generated 44 for seven new anchor pairs). Validation: 0 errors. Gazetteer cross-check (session 1): nodes 37 confirmed / 0 wrong; POIs 53 confirmed / 1 wrong (a known false positive). |
| Pipeline (`pipeline/`) | fetch_overture, fetch_dem + dem, fetch_boundaries, fetch_naturalearth, check_terrain_tiles, common, validate, build_network, route_candidates, build_profiles, build_web_data, apply_patch, crosscheck_gazetteer. 178 tests pass. |
| Web app (`web/`) | Vite + TypeScript + MapLibre, three modes, 103 tests, typecheck and build clean, screenshots of all modes reviewed. |
| CI | `validate.yml` (PR + push) green on every commit. `deploy.yml` needs GitHub Pages enabled by the owner (Settings → Pages → Source: GitHub Actions); not yet enabled. |
| Course numbers (network-routed, remote profile, 10 m climbing threshold; `exports/gpx/manifest.json`) | Traverse 1,331 km, 32,841 m climbing, 59% unpaved, ≈46 km estimated hike-a-bike. Ultra 1,382 km, 35,913 m. Ultra+ (with the Inerie circuit) 1,387 km, 35,768 m. Hand-sketched corridors ≈1,220 km (climbing meaningless; the app shows n/a). |
| Exports and brochure (session 2) | `exports/gpx/` (main, Ultra, Ultra+, 10 sections, 7 options, manifest, README), `docs/ridewithgps.md`, `docs/brochure/` (PDF + HTML, `img/sat/` 28 Sentinel-2 crops + island mosaic, `img/maps/` and `img/profiles/` rendered by `pipeline/render_brochure_maps.py`, `research/` 13 desk-research files), `pipeline/export_gpx.py`, `pipeline/build_brochure.py`, `pipeline/brochure_content.py`, `pipeline/templates/brochure.html.j2`, `pipeline/html_to_pdf.mjs`. |
| Not committed (ephemeral) | Raw data caches: SRTM tiles (207 MB), Overture extract (≈90 MB of GeoJSONL), track graph (≈90 MB), lossless map PNGs (`docs/brochure/img/maps/*.png`, ≈4 MB each; only JPEG copies are committed), screenshots. Recreate with `pipeline/bootstrap_cache.sh` into `.cache/` and re-run the map renderer. |
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

**D-016 · 2026-09-05 · The course is delivered to Ride with GPS as GPX files, not pushed by automation.**
The documented Ride with GPS API (v1) reads routes and creates trips from files but has no documented
route-creation endpoint (older clients use an undocumented `POST /routes.json`); the sandbox blocks
`ridewithgps.com` at the egress proxy and had no browser connector. So `pipeline/export_gpx.py` writes
importable GPX (main course plain and with POIs, Ultra, Ultra+, one file per section, one per option)
and `docs/ridewithgps.md` gives the two-minute import (Route planner → Import → Upload File). The maps
in the brochure are the project's own renders, not planner screenshots, and say so. Alternatives
rejected: an untested uploader against the undocumented endpoint; e-mail upload (creates activities,
not routes). Status: active.

**D-017 · 2026-09-05 · Optional tracks are first-class, each exported and compared against what it
replaces.** `exports/brochure_config.json` lists every option with the segment ids it uses and the
main-course ids it replaces; the exporter derives both sides' numbers (km, climbing, unpaved share,
hike-a-bike, weighted remoteness) so the brochure can show honest deltas. Seven options: Manggarai
Timur interior, Bola coast, Inerie full circuit (new, network-routed via new anchors `n-gurusina` and
`n-sewowoto`), Wae Rebo out-and-back (+ a generated Denge → Todo leg), Boawae → Nangaroro direct,
south coast direct Aimere → Nangaroro (new), Lewotobi corridor via Boru (generated, two legs). Two
computed ideas were recorded but not offered (Kelimutu → Egon ridge link; Riung → Mbay coast road),
with the reason in the config's `considered_not_offered`. `r-ultra-plus` was added to `routes.json`
as the Ultra with the Inerie circuit. Status: active.

**D-018 · 2026-09-05 · Illustrations come from open satellite data and the project's own
cartography.** Every photo host (Wikimedia, Flickr, Unsplash, Pexels) and every tile server is blocked
from the sandbox; the Sentinel-2 L2A cloud-optimised GeoTIFF bucket on AWS is not. The brochure
therefore uses least-cloud Sentinel-2 true-colour crops of 28 places (scene chosen per target by the
cloud fraction of the SCL band inside the box, dry seasons 2025–2026) plus an island mosaic, and maps
rendered offline from SRTM relief and the Overture extract. Ground photographs are left as a
shot-list appendix with Commons search terms, sourced from the research files. Status: active; replace
or complement with real photographs and planner screenshots when a session with network can.

**D-019 · 2026-09-05 · Brochure text is code, numbers are data.** `pipeline/brochure_content.py`
holds the prose; every kilometre, metre and percentage is injected by `pipeline/build_brochure.py`
from `exports/gpx/manifest.json`, so the document cannot drift from the data. HTML is printed to PDF
with the sandbox's Chromium (`pipeline/html_to_pdf.mjs`); fonts are bundled woff2 files from npm
(Fontsource) because Google Fonts' file host is blocked. Status: active.

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

Session 2 additions:

* **Reachable** in addition to the table: `sentinel-cogs.s3.us-west-2.amazonaws.com` (Sentinel-2 L2A
  COGs, listable with `?list-type=2`; windowed reads work with rasterio when `GDAL_HTTP_PROXY` is set to
  `$HTTPS_PROXY` and `GDAL_CURL_CA_BUNDLE`/`CURL_CA_BUNDLE` to the proxy CA bundle), `copernicus-dem-30m`
  and `esa-worldcover` buckets, `naturalearth.s3.amazonaws.com`, `elevation-tiles-prod` terrarium PNGs,
  `api.github.com`, `raw.githubusercontent.com`. **Blocked**: `ridewithgps.com`, Wikipedia/Wikimedia,
  every photo host, every map API, `huggingface.co`, `fonts.gstatic.com` (font files; get woff2 via
  `npm pack @fontsource/<family>` instead). `WebFetch` obeys the same allowlist.
* No browser connector was attached to the session even though the owner had a browser side panel open
  on Ride with GPS; a cloud session cannot see or drive a local browser tab. Say so early.
* Chromium at `/opt/pw-browsers/chromium` prints A4 PDFs with `@page` margin boxes (page numbers) and
  named pages working; drive it with the global `playwright` package (`NODE_PATH=/opt/node22/lib/node_modules`).
  `pymupdf` (pip) renders pages to PNG for visual QA; `pypdf` is broken by the system `cryptography`.
* The account's usage limit can end a session mid-run and kill every background agent at once (it
  did, at 06:20 UTC). Background shell jobs (`nohup`) survive; agents do not. Keep agent work
  resumable (files on disk, manifests) and prefer a few well-scoped agents to a wide fan-out.
* `WebSearch` budget: 13 research agents at a hard cap of 9 searches each used ≈117 of the ≈200-search
  session budget; capping per agent in the prompt works.
* `route_candidates.py` for a new anchor pair: add the nodes, write a scratch `routes.json` with a
  two-anchor route in the scratchpad, run with `--existing-segments data/segments.geojson --merge
  --in-place` (no `--write-route`); ≈5 s per pair once the graph is built. The merge re-sorts the
  feature list by id, so the git diff of `segments.geojson` is large even for 44 added features.

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

Session 2 (desk research, September 2026, sources and confidence labels in `docs/brochure/research/`):

* **Lewotobi Laki-laki**: Level IV at times in 2024–2025 (last ≈7 Sep 2025), Level II / 4 km early
  2026, Level III / 5 km from 12 May 2026, still Level III / 5 km with lahar warnings in the week of
  27 Aug–2 Sep 2026; 778 eruptive events in 2026 by 27 Aug. Recorded in `p-lewotobi-laki-laki`.
* **15 Aug 2026 M7.7 earthquake**, epicentre ≈68 km NNW of Ende: 47+ dead, ≈2,000 evacuated in
  Nagekeo, 230+ aftershocks, tsunami warning lifted; Badan Geologi reported summit-area landslides on
  Ebulobo, Kelimutu and Anak Ranakah without volcanic unrest. Recorded in `p-ebulobo`; a standalone
  hazard entry is still missing.
* **Iya** Level II / 2 km through June 2026; **Kelimutu** Level I with a June 2026 rise in the middle
  lake's temperature (28→35 °C); **Egon**, **Ebulobo** Level I in the last public round-ups.
* **North coast water**: emergency water trucking to Pota, Nangambaur, Golo Lijun, Nangambaling and
  posts in Sambi Rampas and Borong in August 2026. A road exists Reo → Pota (paved) and Pota → Riung via
  Buntal, Golo Lijung, Dampek (rough, potholed, landslide-prone); the open question is condition and water.
* **Corrections applied**: `sec-04` story softened accordingly; `sec-08` highlight_pois gained
  `p-paga-beach`; `p-seventeen-islands` now says the flying-fox colony is reported on Pulau Ontoloe
  (older sources: Tembang). **Flagged, not applied**: `p-wolobobo` elevation text vs field (1,700 vs
  1,468 m); `p-gurusina` story distance to Bajawa stale; `n-bena` may be day-visit only (beds at
  Tololela/Gurusina); Poco Mandasawu/Ranaka elevations conflict across sources; Lio ikat summaries
  overstate natural dyeing; Wuring may be mixed Bugis/Bajo; Sikka church builder's name disputed;
  "Nangaroro/Maukaro" in the concept is a labelling error (Maukaro is a north-coast sub-district).
* **Missing entries suggested**: Marapokot port (Mbay), Etu ritual boxing (Boawae, June–July), Blidit
  hot spring, Mata Menge/So'a basin fossil site, Bukit Nilo statue near Lela, Buntal/Golo Lijung/Dampek
  on the north coast.

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

* Session 2: the options as routed add far less than the concept hoped (see `docs/route-concept.md`,
  "Status after the brochure session"). The Inerie full circuit is the one new loop that adds cultural
  value (Gurusina, the Sewowoto coast) at +5 km with far less estimated hike-a-bike than the shoulder
  traverse; the south-coast Aimere → Nangaroro line is the one new alternative with real remoteness
  (index 4) but it removes the whole Nagekeo highland act. A Kelimutu → Egon link and the Riung → Mbay
  coast road were computed and set aside.

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

Session 2 additions (top of the list):

0. **Import the GPX into Ride with GPS** (owner, two minutes per file; `docs/ridewithgps.md`) and
   decide whether planner screenshots should replace the rendered maps in the brochure.
0. **Ground photographs** for the brochure from Wikimedia Commons / Flickr CC using the shot-list
   appendix; needs a session whose network can reach image hosts.
0. **Apply the flagged data corrections** (above, §5) and add the suggested entries; re-run
   `pipeline/crosscheck_gazetteer.py`.
0. **Re-check volcano statuses** (Lewotobi, Iya, Kelimutu, Ebulobo, Egon) and 2026 earthquake damage in
   Nagekeo before the next planning milestone.

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

### 2026-09-05 · Session 2 · course export and brochure (≈2.5 h, interrupted once by the usage limit)

Asked: connect to Ride with GPS (the owner was logged in, in a local browser) and create the full
track from `docs/route-concept.md` with adventure, remoteness, views and culture as priorities; then
an illustrated PDF brochure with track screenshots, photos of the places and a clear explanation of the
optional tracks; research everything as deeply as possible.

Found first: no browser connector in the session, `ridewithgps.com` and every photo and tile host
blocked at the egress proxy; the routed course data on the PR #1 branch; Sentinel-2 COGs, SRTM and the
Overture extract reachable. Told the owner immediately what could and could not be done.

Done, in order: branch fast-forwarded onto PR #1's head → `bootstrap_cache.sh` → two new anchors
and seven new anchor pairs through `route_candidates.py` (44 candidates, in place, validated) →
`r-ultra-plus` and `exports/brochure_config.json` → `pipeline/export_gpx.py` (main, Ultra, Ultra+,
sections, options, manifest, README, profile JSONs) → `docs/ridewithgps.md` → 13 research agents
(mid tier, 9 searches each; the first workflow attempt died with the usage limit after two topics and
was re-run as plain agents without the critic stage) → Sentinel-2 crops and mosaic (mid-tier agent,
resumed after the limit) → offline cartography script and renders (mid-tier agent) → sourced data
corrections → brochure content, template, builder, PDF → README, route-concept status, this diary.

Verified: `validate.py` 0 errors; `pytest` 171 passed, 7 skipped; every GPX parses; chain continuity
(no gaps > 300 m); brochure pages inspected as rendered PNGs; no model or vendor names in committed
files.

Left open: see §8 (import into Ride with GPS, ground photographs, flagged corrections, status
re-checks). The web app was not rebuilt (`web/public/data` is unchanged); a `build_web_data.py` run
would pick up the new segments and routes.
