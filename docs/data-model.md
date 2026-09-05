# Data model

This is the contract between the canonical data in `data/`, the pipeline, the JSON Schemas in
`schemas/`, and the TypeScript types in `web/src/data/types.ts`. If you change something here, change
the schema, the types and the validator in the same pull request.

Conventions

* All geometry is WGS84 (EPSG:4326) GeoJSON, coordinates `[lon, lat]`, at most 6 decimals.
* Ids are kebab-case slugs with a type prefix and are **stable**: `n-`, `p-`, `s-`, `sec-`, `r-`.
* Names are English display names; `local_name` holds the Indonesian or local-language name when different.
* Every human-authored feature has `confidence` and `sources`.
* Fields marked *derived* are written by the pipeline and must not be hand-edited.
* Booleans default to `false`; `public` defaults to `false` (opt-in to the public site).

Shared enumerations

| Name | Values |
|---|---|
| `confidence` | `verified` (coordinates checked against two independent sources or a field GPS fix), `approximate` (one source or a well-known place located by hand within ~1 km), `unverified` (from memory or a single weak source; must be checked) |
| `status` (segments) | `concept`, `desk-checked`, `scouted-go`, `scouted-no-go`, `needs-recheck`, `confirmed` |
| `geometry_source` | `concept-sketch` (hand-drawn corridor), `overture-route` (computed on the track graph), `gpx-field` (recorded on the ground), `manual-trace` (traced on imagery by a human) |
| `character` | `paved`, `gravel`, `dirt`, `singletrack`, `hab` (hike-a-bike dominant), `mixed`, `unknown` |
| `theme` (sections) | `volcano`, `highland`, `coast`, `culture`, `forest`, `savanna`, `history` |

---

## `data/nodes.geojson` — anchor points (Point)

| Property | Type | Required | Meaning |
|---|---|---|---|
| `id` | string `^n-[a-z0-9-]+$` | yes | stable id |
| `name` | string | yes | display name |
| `local_name` | string | no | local name |
| `kind` | enum `start` `finish` `checkpoint` `town` `village` `junction` `trailhead` `port` `airport` | yes | role in the course |
| `resupply` | enum `none` `minimal` (a kiosk/warung) `basic` (shops, warungs) `full` (town with market, ATM, bike-ish parts) | yes | what a rider can buy |
| `water` | enum `none` `unreliable` `reliable` | yes | drinking water availability (bottled counts) |
| `sleep` | enum `none` `homestay` `guesthouse` `hotel` | yes | indoor sleeping options |
| `notes` | string | no | free text for scouts |
| `confidence` | enum | yes | geolocation confidence |
| `sources` | string[] | yes | URLs or `field:YYYY-MM-DD` or `map:overture` |
| `public` | boolean | no | show on the public site |
| `elevation_m` | number | *derived* | from the DEM |

## `data/pois.geojson` — points of interest (Point)

| Property | Type | Required | Meaning |
|---|---|---|---|
| `id` | string `^p-[a-z0-9-]+$` | yes | |
| `name`, `local_name` | string | name yes | |
| `category` | enum `volcano` `crater-lake` `lake` `traditional-village` `beach` `hot-spring` `waterfall` `cave` `heritage` `viewpoint` `market` `port` `airport` `national-park` `weaving` `religious` `hazard` `forest` `savanna` `rice-terrace` `other` | yes | drives the icon |
| `summary` | string ≤ 300 chars | yes | one or two sentences, shown in every mode |
| `story` | string (markdown) | no | longer narrative for stakeholder and public story mode |
| `race_relevance` | enum `anchor` (the course must touch it) `highlight` (we want it) `resupply` `hazard` `context` (background only) | yes | |
| `access` | enum `road` `track` `trail` `boat` `unknown` | yes | how you get there |
| `hike_a_bike` | boolean | no | reaching it implies carrying the bike |
| `cultural_protocol` | string | no | e.g. "guests are received by the elders; a small donation and the guest book are expected; agreement with the village council required for a race" |
| `elevation_m` | number | no | summit / lake / village elevation if known |
| `hazard_level` | string | no | for `hazard` category, e.g. "PVMBG alert level III (Nov 2024)" with date |
| `confidence` | enum | yes | |
| `sources` | string[] | yes | |
| `public` | boolean | no | |
| `image`, `image_credit` | string | no | optional illustration |

## `data/segments.geojson` — candidate segments (LineString)

A segment is one candidate way from `from_node` to `to_node`. Alternatives for the same pair share
`from_node`/`to_node` and differ in `variant`.

| Property | Type | Required | Meaning |
|---|---|---|---|
| `id` | string `^s-[a-z0-9-]+$` | yes | convention `s-<from>-<to>-<variant>` without the `n-` prefixes, e.g. `s-ruteng-reo-a` |
| `name` | string | yes | short human name, e.g. "Ruteng → Reo via Liang Bua" |
| `from_node`, `to_node` | node id | yes | must exist in `nodes.geojson` |
| `variant` | string `^[A-Z]$` | yes | `A`, `B`, `C`… |
| `status` | enum | yes | see shared enumerations |
| `geometry_source` | enum | yes | |
| `character` | enum | yes | dominant surface character (estimate until scouted) |
| `est_hab_km` | number ≥ 0 | yes | estimated hike-a-bike kilometres |
| `difficulty` | integer 1–5 | yes | 1 easy gravel, 5 full-day suffering |
| `remoteness` | integer 1–5 | yes | 1 town roads, 5 nobody for a day |
| `direction_note` | string | no | if only sensible in one direction |
| `water_points` | string[] | no | free text list ("spring at km 12", "warung in Rana Mese") |
| `resupply_notes` | string | no | |
| `hazards` | string[] | no | |
| `cultural_notes` | string | no | villages, permissions, sensitivities |
| `open_questions` | string[] | no | what scouting must answer |
| `scouting` | ScoutingEntry[] | no | history of field verdicts, newest last |
| `stats` | Stats | *derived* | filled by `build_profiles.py` |
| `surface_mix`, `class_mix` | object {label: km} | *derived* | from the Overture graph when `geometry_source = overture-route`, else empty |
| `route_profile` | string | no | cost profile that produced it (`remote`, `rideable`, `direct`) when computed |
| `public` | boolean | no | |
| `sources` | string[] | yes | |

`ScoutingEntry`

| Field | Type | Meaning |
|---|---|---|
| `date` | `YYYY-MM-DD` | |
| `team` | string | initials or names |
| `verdict` | enum `go` `no-go` `partial` | |
| `notes` | string | |
| `gpx` | string | path under `data/scouting/gpx/` |
| `photos` | string[] | paths or URLs |

`Stats` (*derived*)

| Field | Type | Meaning |
|---|---|---|
| `length_km` | number | geodesic length |
| `ascent_m`, `descent_m` | number | from the DEM with smoothing |
| `min_elev_m`, `max_elev_m` | number | |
| `unpaved_pct` | number 0–100 | from surface mix when available, else from `character` (paved → 0, otherwise 100) |
| `profile_ref` | string | key in `profiles.json` |

## `data/sections.json` — narrative chapters

Array of objects, ordered by `order`.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | `^sec-[0-9]{2}-[a-z0-9-]+$` | yes | e.g. `sec-03-north-coast` |
| `order` | integer | yes | |
| `title`, `subtitle` | string | title yes | |
| `from_node`, `to_node` | node id | yes | the chapter spans these anchors |
| `theme` | theme[] | yes | one or more |
| `story` | string (markdown) | yes | the narrative for stakeholders |
| `highlight_pois` | poi id[] | yes | |
| `target_km` | [min, max] | yes | concept distance range for the chapter |
| `hab_expected` | enum `low` `medium` `high` | yes | |
| `scouting_priority` | integer 1–3 | yes | 1 = scout first |
| `open_questions` | string[] | yes | |
| `public` | boolean | no | |

## `data/routes.json` — route variants

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | `^r-[a-z0-9-]+$` | yes | |
| `name`, `tagline`, `description` | string | name yes | |
| `audience` | enum[] `stakeholder` `scout` `public` | yes | |
| `anchors` | node id[] | yes | ordered anchors the variant must visit; drives candidate generation |
| `segments` | segment id[] | yes | ordered selected segments; consecutive segments must chain `to_node → from_node` (validator enforces) |
| `status` | enum `concept` `in-scouting` `confirmed` | yes | |
| `target_km_range` | [min, max] | yes | |
| `time_limit_days` | number | no | |
| `notes` | string | no | |
| `stats` | Stats + `hab_km` + `segments_by_status` {status: count} | *derived* | |

## `data/scouting/*.md` — field reports

Markdown with YAML front matter:

```yaml
---
date: 2026-07-14
team: [RC, MB]
segments: [s-ruteng-reo-a]
verdict: partial
gpx: gpx/2026-07-14-ruteng-reo.gpx
---
```

The body is free text. `pipeline/validate.py` checks that referenced segments exist.

## Scouting patch (`schemas/scouting-patch.schema.json`)

Exported by the app in scout mode; applied by `pipeline/apply_patch.py`.

```json
{
  "version": 1,
  "created": "2026-07-14T18:22:00Z",
  "author": "RC",
  "segments": {
    "s-ruteng-reo-a": {
      "status": "scouted-go",
      "character": "gravel",
      "est_hab_km": 2,
      "scouting_append": [{ "date": "2026-07-14", "team": "RC", "verdict": "go", "notes": "..." }]
    }
  },
  "nodes": { "n-reo": { "water": "reliable" } },
  "new_pois": [ { "type": "Feature", "geometry": {...}, "properties": {...} } ]
}
```

Rules: a patch may change scouting-owned fields (`status`, `character`, `est_hab_km`, `difficulty`,
`remoteness`, `water_points`, `resupply_notes`, `hazards`, `cultural_notes`, `open_questions`, node
`resupply`/`water`/`sleep`/`notes`) and append scouting entries. It may not change geometry or ids;
geometry changes come as GPX files referenced by a scouting entry and are traced by the route designer.

---

## Generated web bundle (`web/public/data/`)

| File | Content |
|---|---|
| `nodes.geojson`, `pois.geojson` | canonical files with `elevation_m` filled |
| `segments.geojson` | canonical segments with `stats`, geometry simplified to ~5 m tolerance |
| `sections.json`, `routes.json` | canonical with `stats` filled |
| `profiles.json` | `{ "<segment id>": [[km, m], ...] }` sampled every 50 m, plus `"<route id>"` concatenated |
| `network.geojson.gz` | Overture segments for the island, properties reduced to `class`, `surface`, `name`, `remoteness`; built in CI, not committed |
| `regencies.geojson` | 8 regencies, simplified |
| `meta.json` | build time, Overture release, sources and license strings, counts, git commit |
