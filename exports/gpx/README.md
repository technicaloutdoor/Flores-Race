# GPX exports of the Flores Race course

Generated 2026-09-05 by `pipeline/export_gpx.py` from `data/routes.json`, `data/segments.geojson` and
`exports/brochure_config.json`. Every number is derived; nothing is typed. Status of every line: **concept, unscouted**.

Elevation is SRTM (30 m) sampled every 50 m, smoothed, with a 10 m hysteresis threshold for climbing
(the same rule as the web app). Ride with GPS recomputes elevation from its own terrain data on import,
so expect its figures to differ by a few percent.

## Course variants

| Variant | File | km | Climb (m) | Descent (m) | Unpaved | Hike-a-bike est. | Points |
|---|---|---|---|---|---|---|---|
| Traverse (network-routed) | `flores-race-traverse.gpx` (+ `flores-race-traverse-with-pois.gpx`) | 1331 | 32,841 | 32,852 | 59.4% | 45.5 km | 17,220 |
| Ultra (network-routed) | `flores-race-ultra.gpx` | 1382 | 35,913 | 35,923 | 67.8% | 45.4 km | 18,529 |
| Ultra+ (network-routed, Inerie circuit) | `flores-race-ultra-plus.gpx` | 1386 | 35,768 | 35,779 | 67.2% | 37.0 km | 18,593 |

## Sections of the main course

| # | Section | km | Climb (m) | Course km | File |
|---|---|---|---|---|---|
| 01 | Komodo gate and the Mbeliling forest | 102 | 3,368 | 0–102 | `sections/flores-race-s01-komodo-gate-and-the-mbeliling-forest.gpx` |
| 02 | Wae Rebo and the south coast of Manggarai | 165 | 4,151 | 102–266 | `sections/flores-race-s02-wae-rebo-and-the-south-coast-of-manggarai.gpx` |
| 03 | Manggarai highlands | 105 | 3,342 | 266–371 | `sections/flores-race-s03-manggarai-highlands.gpx` |
| 04 | The forgotten north coast | 157 | 2,335 | 371–528 | `sections/flores-race-s04-the-forgotten-north-coast.gpx` |
| 05 | Ngada: megaliths under Inerie | 129 | 3,280 | 528–657 | `sections/flores-race-s05-ngada-megaliths-under-inerie.gpx` |
| 06 | Ebulobo and the Nagekeo plains | 141 | 3,342 | 657–798 | `sections/flores-race-s06-ebulobo-and-the-nagekeo-plains.gpx` |
| 07 | The blue-stone coast to Ende | 107 | 2,093 | 798–904 | `sections/flores-race-s07-the-blue-stone-coast-to-ende.gpx` |
| 08 | Kelimutu and the Lio country | 149 | 4,704 | 904–1054 | `sections/flores-race-s08-kelimutu-and-the-lio-country.gpx` |
| 09 | Sikka and the Portuguese south | 87 | 2,447 | 1054–1141 | `sections/flores-race-s09-sikka-and-the-portuguese-south.gpx` |
| 10 | Egon and the far east | 191 | 3,776 | 1141–1332 | `sections/flores-race-s10-egon-and-the-far-east.gpx` |

## Optional loops and alternatives

| Option | Kind | km | Climb (m) | Replaces (km / m) | Δ km | File |
|---|---|---|---|---|---|---|
| Manggarai Timur interior loop | loop | 204 | 5,450 | 170 / 3,062 | +34 | `options/opt-manggarai-timur-interior.gpx` |
| Bola south-coast loop | loop | 46 | 1,332 | 29 / 649 | +16 | `options/opt-bola-coast.gpx` |
| Inerie full circuit via Gurusina and the Sewowoto coast | loop | 35 | 421 | 30 / 566 | +5 | `options/opt-inerie-circuit.gpx` |
| Wae Rebo out-and-back | alternative | 60 | 2,018 | 60 / 2,018 | +0 | `options/opt-wae-rebo-out-and-back.gpx` |
| Boawae to Nangaroro direct | alternative | 49 | 1,151 | 118 / 2,284 | -69 | `options/opt-boawae-nangaroro-direct.gpx` |
| South coast direct: Aimere to Nangaroro | alternative | 102 | 2,150 | 197 / 4,505 | -94 | `options/opt-south-coast-aimere-nangaroro.gpx` |
| Lewotobi southern corridor via Boru | alternative | 118 | 1,812 | 96 / 1,246 | +22 | `options/opt-lewotobi-corridor.gpx` |

## Importing into Ride with GPS

1. Open <https://ridewithgps.com/routes/new> (the route planner) while logged in.
2. Click **Import** (top of the left panel) → **Upload File** → choose one GPX from this folder → **Add to Planner**.
   The whole track appears; Ride with GPS snaps nothing and recomputes elevation and surface where it can.
3. Give it a name (for example `Flores Race — Traverse (concept)`), set the visibility, **Save**.
4. Repeat for the section files and for each option file. Put them in a Collection named `Flores Race`.
5. Alternative: the **Upload** page (left toolbar on the dashboard) accepts several files at once; choose *Save as Route*.

The `*-with-pois.gpx` variant carries the anchors and key points of interest as waypoints; the planner turns them
into POIs you can edit. Import the plain file if you prefer a clean map.

Planner and source data: https://github.com/technicaloutdoor/Flores-Race
