# Getting the course into Ride with GPS

The course lives in this repository as data (`data/routes.json`, `data/segments.geojson`) and is
exported to GPX by `pipeline/export_gpx.py` into `exports/gpx/`. Ride with GPS is the team's shared
planner for looking at it, sharing it and sending it to devices. This page says exactly how the two
connect, what was automated, and what needs a person with a browser.

## What is in `exports/gpx/`

| File | What | Import as |
|---|---|---|
| `flores-race-traverse.gpx` | the main course, Labuan Bajo to Larantuka, one track | route |
| `flores-race-traverse-with-pois.gpx` | same track plus the anchors and key points of interest as waypoints (they become Ride with GPS POIs) | route |
| `flores-race-ultra.gpx` | Ultra: main course with the Manggarai Timur interior and Bola coast loops | route |
| `flores-race-ultra-plus.gpx` | Ultra plus the full circuit of Inerie via Gurusina and the Sewowoto coast | route |
| `sections/flores-race-sNN-….gpx` | the ten narrative sections of the main course, each with its anchors and POIs | route |
| `options/opt-….gpx` | every optional loop and alternative on its own, so it can be compared with the main line | route |
| `manifest.json`, `README.md` | derived numbers for every file (km, climbing, unpaved share, hike-a-bike estimate) | — |

Regenerate everything with:

```bash
python3 pipeline/export_gpx.py --data data --config exports/brochure_config.json --dem-dir .cache/dem
```

## Importing (two minutes per file)

You were already logged in and on `ridewithgps.com/routes/new` (the route planner); that is the right
page.

1. In the **Route** panel on the left, click **Import** (next to **Add New**).
2. In the dialog choose **Upload File**, pick a `.gpx` from `exports/gpx/`, then **Add to Planner**.
   The track appears exactly as drawn; Ride with GPS does not re-route it, but it recomputes elevation,
   surface and the cue sheet from its own data.
3. Do not drag any control point afterwards unless you mean to re-route that stretch with its routing
   engine (which prefers roads and would undo the farm tracks).
4. Rename it (suggestion: `Flores Race · Traverse (concept)`, `Flores Race · S05 Ngada`, `Flores Race ·
   Option · Inerie circuit`), set visibility to private or friends while the course is a concept, and **Save**.
5. Repeat for the other files. Put all of them in a **Collection** named `Flores Race` so the team finds
   them in one place; pin the Traverse.

Bulk alternative: on the dashboard, **Upload** in the left toolbar accepts several files at once
(Ctrl/Cmd-click to select); choose **Save as Route** for each, not *Add to My Activities*. The
e-mail upload address (`upload@ridewithgps.com`) turns files into activities, not routes, so it is not
useful here.

Getting the files onto your computer: download the folder from the repository branch (GitHub's
*Download raw file* button on each file, or `git clone`). Direct links follow the pattern
`https://raw.githubusercontent.com/technicaloutdoor/Flores-Race/<branch>/exports/gpx/flores-race-traverse.gpx`.

If you want a browser assistant to do the clicking, a workable instruction is:
*"On this page, use Import → Upload File to import each GPX from my Downloads/flores-gpx folder in turn,
name each one 'Flores Race · <file title>', keep it private, save it, and add it to a collection called
Flores Race."* The files must be on the local machine first; a browser cannot upload from a URL.

## What ride-with-GPS-side automation is possible

* The documented Ride with GPS API (v1) reads routes, trips, events and users and creates trips
  (activities) from files; it does **not** offer a documented endpoint to create a *route*. Older
  clients call an undocumented `POST /routes.json`; it is not relied on here.
* This planning session ran in a sandbox whose network policy blocks `ridewithgps.com` (403 at the
  egress proxy), and no browser connector was attached to it, so nothing could be pushed or
  screenshotted from Ride with GPS directly. The maps in the brochure are therefore rendered by
  `pipeline/render_brochure_maps.py` from the same data (SRTM relief, Overture/OpenStreetMap roads
  and coastline) instead of being planner screenshots. Once the routes exist in Ride with GPS, their
  screenshots can replace or complement those maps.

## Reading the numbers

* Ride with GPS will show slightly different climbing figures than the brochure. Ours use SRTM 30 m
  sampled every 50 m, smoothed, with a 10 m hysteresis threshold (see `pipeline/build_profiles.py`);
  theirs use their own terrain model and smoothing. Differences of a few percent are normal.
* Surface: the exported track carries no surface tags. Ride with GPS infers surface from
  OpenStreetMap where tags exist; on Flores most tracks are untagged, so treat its "unpaved %" as a
  lower bound. Our figure comes from the Overture extract plus class inference (`surface_mix`).
* Every line is `concept` status: routed over the mapped network, never ridden by us. The scouting
  protocol (`docs/scouting-protocol.md`) is how a segment earns a better status.
