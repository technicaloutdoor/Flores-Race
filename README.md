# Flores Race Planner

A static web app and Python pipeline to plan an ultra-distance adventure bike race across the island of Flores (Nusa Tenggara Timur, Indonesia). The planner visualizes candidate segments, evaluates alternatives using open data (Overture Maps, SRTM terrain), and collects field scouting verdicts. The race concept draws inspiration from the Silk Road Mountain Race: 1,000–2,000 km, self-supported, remote, on forgotten tracks and farmers' routes, with real hike-a-bike and a deliberate connection to the volcanoes, villages, and history of the island.

**Status:** Concept under scouting. The route, segments, and course details are proposals for the field team to evaluate. See the "Open questions" section in [`docs/route-concept.md`](docs/route-concept.md) for the priorities.

[Screenshot placeholder]


## Project memory

`docs/DIARY.md` is the running memory of the project: current state, every decision with its
reasoning, environment quirks, open questions and a log of each working session. Read it before
changing anything substantial; update it when you finish. `CLAUDE.md` tells the assistant to do the
same automatically.

## Quick start

### For the team (web app only)

**Prerequisites:** Node 22, npm.

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:5173/Flores-Race/`. Use the mode selector in the header to switch between **stakeholder** (overview), **scout** (field scouting), and **public** (teaser) views.

### For the pipeline (full build)

**Prerequisites:** Python 3.11, Node 22, 4 GB of free disk space.

```bash
# Install Python and Node dependencies
pip install -r pipeline/requirements.txt
cd web && npm install && cd ..

# Run the pipeline
# Note: raw data (.cache/) is gitignored; the pipeline downloads it from public sources (S3, GitHub)
python3 pipeline/fetch_dem.py --out data/.cache/dem
python3 pipeline/fetch_boundaries.py --out data/.cache/boundaries
python3 pipeline/fetch_naturalearth.py --out data/.cache/naturalearth
python3 pipeline/fetch_overture.py \
  --bbox 119.70,-9.00,123.10,-8.00 \
  --release latest \
  --out data/.cache/overture \
  --themes segment,connector,place,land,water,division_area

# Build the routable network and elevation profiles
python3 pipeline/build_network.py \
  --overture-dir data/.cache/overture \
  --dem-dir data/.cache/dem \
  --regencies data/.cache/boundaries/flores_regencies.geojson \
  --out data/.cache/network

python3 pipeline/build_profiles.py \
  --dem-dir data/.cache/dem \
  --out data/.cache/profiles

# Validate the canonical data
python3 pipeline/validate.py --data data --schemas schemas

# Build the web bundle
python3 pipeline/build_web_data.py \
  --dem-dir data/.cache/dem \
  --regencies data/.cache/boundaries/flores_regencies.geojson \
  --overture-dir data/.cache/overture \
  --out web/public/data

# Build and start the web app
cd web && npm run build && npm run dev && cd ..
```

(The actual CI/CD workflows and local development may automate these steps; see [`docs/deployment.md`](docs/deployment.md).)

## Repository map

| Directory | Purpose |
|---|---|
| `ARCHITECTURE.md` | System design, layers, modes, pipeline stages (start here). |
| `docs/` | Reference documentation: data model, route concept, scouting protocol, deployment, architecture decision records. |
| `data/` | **Canonical source of truth** (git is the database). Nodes, POIs, segments, sections, routes, and scouting reports. Edited via pull requests. |
| `schemas/` | JSON Schema definitions for every file in `data/` and the generated bundle. Validated in CI. |
| `pipeline/` | Python 3.11 scripts to fetch open data, build the routable network, compute elevation profiles, and bundle everything for the web app. See [`pipeline/README.md`](pipeline/README.md). |
| `web/` | Vite + TypeScript web application. MapLibre GL JS rendering, no UI framework. Deployed to GitHub Pages. |
| `.github/workflows/` | CI/CD: `validate.yml` (on every PR), `deploy.yml` (on push to main). |

## Data sources and licenses

The planner uses open data from the following sources:

| Source | Layer | License | Attribution |
|---|---|---|---|
| [Overture Maps](https://overturemaps.org/) | Road network, places, peaks, water, admin areas | ODbL (OpenStreetMap-derived) | © OpenStreetMap contributors via Overture Maps |
| [SRTM / AWS Terrain Tiles](https://registry.opendata.aws/raster/elevation-tiles-prod/) | Elevation (DEM) and terrarium tiles for hillshade | Public domain | Shuttle Radar Topography Mission (USGS) |
| [geoBoundaries](https://www.geoboundaries.org/) | Regency (kabupaten) polygons | CC BY 4.0 | geoBoundaries contributors |
| [Natural Earth](https://www.naturalearthdata.com/) | Populated places, islands, land outlines | Public domain | Natural Earth |
| [OpenTopoMap](https://opentopomap.org/) | Basemap tiles (scout mode default) | CC BY-SA 4.0 | © OpenTopoMap contributors |
| [OpenStreetMap](https://www.openstreetmap.org/) | Basemap tiles | ODbL | © OpenStreetMap contributors |
| [Esri World Imagery](https://www.arcgisonline.com/) | Satellite imagery tiles | Esri terms (attribution required) | © Esri, DigitalGlobe, GeoEye, Earthstar Geographics, etc. |

Each attribution is displayed in the web app's attribution control and recorded in the generated `web/public/data/meta.json`.

## Links

- **[`ARCHITECTURE.md`](ARCHITECTURE.md)** — The authoritative system design. Start here for an overview of audiences, design principles, the route model, and the pipeline stages.
- **[`docs/data-model.md`](docs/data-model.md)** — The contract between the canonical data, schemas, and the web app. Field-by-field reference for nodes, POIs, segments, sections, and routes.
- **[`docs/route-concept.md`](docs/route-concept.md)** — The conceptual course: sections, anchors, hike-a-bike, hazards, and open questions for scouting.
- **[`docs/scouting-protocol.md`](docs/scouting-protocol.md)** — How the field team prepares, records verdicts in the field, and submits scouting reports.
- **[`docs/deployment.md`](docs/deployment.md)** — GitHub Pages setup, CI/CD workflows, and the public build option.
- **[`docs/ai-workflow.md`](docs/ai-workflow.md)** — Model tiering policy for AI-assisted development.
- **[`pipeline/README.md`](pipeline/README.md)** — Reference for each pipeline script, execution order, and raw data locations.

## Development

The project is built with:
- **Frontend:** Vite, TypeScript, MapLibre GL JS (no UI framework).
- **Backend:** Python 3.11 (pure-Python geoprocessing; no GDAL).
- **Hosting:** GitHub Pages via GitHub Actions.
- **Data:** Git (static files, no database).

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full rationale and [`pipeline/README.md`](pipeline/README.md) for pipeline setup.

## Roadmap

- **Phase 0 (current):** Architecture, data model, route concept, pipeline, web app v0 with concept course.
- **Phase 1:** Network-derived candidates for every anchor pair; scouting protocol tested in the field; GPX round-trip.
- **Phase 2:** Offline field mode (PWA), photo attachments, live collaboration.
- **Phase 3:** Public teaser site, custom domain, story mode.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) section 11 for details.

## Questions?

Start with [`ARCHITECTURE.md`](ARCHITECTURE.md). For specific topics, see the `docs/` directory. To report an issue or propose a change, open an issue or pull request on GitHub.
