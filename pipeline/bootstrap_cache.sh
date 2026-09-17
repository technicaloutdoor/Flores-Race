#!/usr/bin/env bash
# bootstrap_cache.sh — rebuild /home/user/Flores-Race/.cache/ from scratch.
#
# .cache/ is gitignored: a fresh session starts with none of it. This script recreates it,
# in dependency order, skipping any stage whose output already exists so it is safe to
# re-run after an interruption or a partial cache. See .claude/AGENT-BRIEF.md for what each
# directory holds and why.
#
# Usage:
#   pipeline/bootstrap_cache.sh            # do the real thing
#   DRY_RUN=1 pipeline/bootstrap_cache.sh  # print every command this run WOULD execute,
#                                          # run nothing, download nothing
#
# This script only ever touches .cache/. It never writes to data/ or web/public/data — the
# steps that do (route_candidates.py, build_web_data.py) are printed at the end for a human
# or agent to run deliberately, on canonical data, never as an unattended side effect of
# rebuilding a cache.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CACHE="$REPO_ROOT/.cache"
PIPELINE="$REPO_ROOT/pipeline"
DRY_RUN="${DRY_RUN:-0}"
BBOX="119.70,-9.00,123.10,-8.00"

say() { printf '\n== %s ==\n' "$*"; }

# run <command...>  — always prints the command; executes it unless DRY_RUN=1.
run() {
  printf '+ %s\n' "$*"
  if [ "$DRY_RUN" = "1" ]; then
    return 0
  fi
  "$@"
}

# skip <label> <marker-path>  — true (and prints a skip note) if marker-path already
# exists, meaning this stage's output is already in place.
skip() {
  local label="$1" marker="$2"
  if [ -e "$marker" ]; then
    echo "[skip] $label already cached: $marker"
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------------------
say "1/6 Python dependencies"
run pip install -q -r "$PIPELINE/requirements.txt"

# ---------------------------------------------------------------------------------------
say "2/6 DEM tiles (fetch_dem.py) -> .cache/dem"
# fetch_dem.py --out DIR [--tiles ...] [-v]; with no --tiles it defaults to the 8 tiles
# that cover Flores, and it already skips any .hgt file that exists — so we only need to
# gate the whole call on all 8 being present, the script's own per-tile skip handles the
# rest on a partial cache.
dem_count=0
if [ -d "$CACHE/dem" ]; then
  dem_count=$(find "$CACHE/dem" -maxdepth 1 -name '*.hgt' | wc -l)
fi
if [ "$dem_count" -ge 8 ]; then
  echo "[skip] DEM already cached: 8 .hgt tiles in $CACHE/dem"
else
  run mkdir -p "$CACHE/dem"
  run python3 "$PIPELINE/fetch_dem.py" --out "$CACHE/dem" -v
fi

# ---------------------------------------------------------------------------------------
say "3/6 Regency boundaries (fetch_boundaries.py) -> .cache/boundaries"
# fetch_boundaries.py takes NO CLI flags at all (confirmed by reading the script — no
# argparse) and hardcodes its output to the relative path "raw/boundaries" under whatever
# directory it is run from. So it is run with cwd = .cache and its "raw/boundaries" output
# is then moved up into .cache/boundaries/ and the leftover "raw" wrapper removed. Do not
# add flags to this call — the script ignores them.
if ! skip boundaries "$CACHE/boundaries/flores_regencies.geojson"; then
  run mkdir -p "$CACHE/boundaries"
  if [ "$DRY_RUN" = "1" ]; then
    echo "+ (cd $CACHE && python3 $PIPELINE/fetch_boundaries.py)  # writes .cache/raw/boundaries/*.geojson"
    echo "+ mv $CACHE/raw/boundaries/*.geojson $CACHE/boundaries/"
    echo "+ rm -rf $CACHE/raw"
  else
    ( cd "$CACHE" && python3 "$PIPELINE/fetch_boundaries.py" )
    mv "$CACHE/raw/boundaries/"*.geojson "$CACHE/boundaries/"
    rm -rf "$CACHE/raw"
  fi
fi

# ---------------------------------------------------------------------------------------
say "4/6 Natural Earth extracts (fetch_naturalearth.py) -> .cache/naturalearth"
# Same situation as fetch_boundaries.py: no CLI flags, hardcoded relative output path
# ("raw/naturalearth"), so run it with cwd = .cache and relocate the result.
if ! skip naturalearth "$CACHE/naturalearth/ne_10m_land.geojson"; then
  run mkdir -p "$CACHE/naturalearth"
  if [ "$DRY_RUN" = "1" ]; then
    echo "+ (cd $CACHE && python3 $PIPELINE/fetch_naturalearth.py)  # writes .cache/raw/naturalearth/*.geojson"
    echo "+ mv $CACHE/raw/naturalearth/*.geojson $CACHE/naturalearth/"
    echo "+ rm -rf $CACHE/raw"
  else
    ( cd "$CACHE" && python3 "$PIPELINE/fetch_naturalearth.py" )
    mv "$CACHE/raw/naturalearth/"*.geojson "$CACHE/naturalearth/"
    rm -rf "$CACHE/raw"
  fi
fi

# ---------------------------------------------------------------------------------------
say "5/6 Overture Maps extract (fetch_overture.py) -> .cache/overture"
# --themes is omitted: its default is every theme (segment, connector, place, land, water,
# division_area, land_use), which is what build_network.py and route_candidates.py (for
# water_points) both need.
if ! skip overture "$CACHE/overture/manifest.json"; then
  run mkdir -p "$CACHE/overture"
  run python3 "$PIPELINE/fetch_overture.py" --bbox "$BBOX" --out "$CACHE/overture"
fi

# ---------------------------------------------------------------------------------------
say "6/6 Routable network (build_network.py) -> .cache/network"
if ! skip network "$CACHE/network/graph.json.gz"; then
  run mkdir -p "$CACHE/network"
  run python3 "$PIPELINE/build_network.py" \
    --overture-dir "$CACHE/overture" \
    --dem-dir "$CACHE/dem" \
    --regencies "$CACHE/boundaries/flores_regencies.geojson" \
    --out "$CACHE/network"
fi

# ---------------------------------------------------------------------------------------
say "Cache ready — next steps (not run automatically; these touch data/ and web/, not .cache/)"
cat <<EOF
Validate the canonical data against schemas:
  python3 pipeline/validate.py --data data --schemas schemas

Refresh/merge computed route candidates onto the hand-sketched segments (writes into
data/, in place — review the diff before trusting it):
  python3 pipeline/route_candidates.py \\
    --graph .cache/network/graph.json.gz \\
    --water .cache/overture/water.geojsonl \\
    --nodes data/nodes.geojson \\
    --routes data/routes.json \\
    --route-id r-traverse \\
    --existing-segments data/segments.geojson \\
    --merge --in-place \\
    --write-route r-traverse \\
    --out .cache/network

Build the web data bundle:
  python3 pipeline/build_web_data.py \\
    --dem-dir .cache/dem \\
    --regencies .cache/boundaries/flores_regencies.geojson \\
    --network-web .cache/network/network_web.geojson.gz \\
    --out web/public/data

Independent offline cross-check of node/POI coordinates against the Overture gazetteer:
  python3 pipeline/crosscheck_gazetteer.py \\
    --data data \\
    --overture-dir .cache/overture \\
    --dem-dir .cache/dem \\
    --out .cache/verify/gazetteer_report.md \\
    --json .cache/verify/gazetteer_report.json
EOF
