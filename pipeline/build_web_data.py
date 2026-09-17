#!/usr/bin/env python3
"""build_web_data.py

Orchestrates the whole pipeline into the generated web bundle
(``web/public/data/``): validate -> profiles -> write.

    1. Validate data/ against schemas/ (schema + referential integrity).
       Aborts on any error; warnings are printed but do not block the build.
    2. Compute segment/route stats and elevation profiles
       (build_profiles.py), using the *original* geometry -- lengths must be
       measured before anything gets simplified for display.
    3. Fill node.elevation_m from the DEM.
    4. Simplify segment geometry to ~5 m for the web copy, regency polygons
       to ~30 m, and the track network (see below) to ~8 m, gzipped.
    5. Write nodes/pois/segments/regencies.geojson, sections/routes/
       profiles/meta.json (and network.geojson.gz if available) to --out.

The track network layer (``network.geojson.gz``) comes from one of two
places, in priority order:

* ``--network-web`` -- a ``network_web.geojson`` or ``.geojson.gz`` export
  already produced by ``build_network.py`` (one LineString per Overture
  segment, with ``id``/``class``/``subclass``/``surface``/
  ``surface_source``/``name``/``remoteness``/``km`` -- the graph build has
  already classified surfaces and computed remoteness, so this is strictly
  richer than what this script can derive from a raw Overture extract).
  Those properties are kept as-is; geometry is simplified to
  ``NETWORK_WEB_TOLERANCE_M`` only if the file is not already coarser than
  that (see ``is_already_coarser_than`` -- re-simplifying an
  already-reduced export at the same or a finer tolerance would do
  essentially nothing and just cost time).
* ``--overture-dir`` -- used only when ``--network-web`` is absent (or the
  path it names does not exist): reduces a raw ``fetch_overture.py``
  segment extract in place (subtype filter, property reduction, geometry
  simplified to ``NETWORK_WEB_TOLERANCE_M``), the original behaviour before
  ``build_network.py`` had its own web export. No remoteness or
  ``surface_source`` is available this way unless the extract happens to
  carry it already.

Whichever path is used, ``meta.json`` records it as ``network_source``
(``"network-web"`` or ``"overture-dir"``) alongside ``counts.network_features``,
so it is clear which source produced the network layer in a given build.

``--public-build`` drops anything not opted into the public site (nodes,
pois, segments: ``public`` != true; sections: ``public`` != true; routes:
``"public"`` not in ``audience`` -- routes have no ``public`` flag of their
own, see docs/data-model.md, so audience is the public-site signal there).
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import build_profiles
import common
import validate

REPO_ROOT = Path(__file__).resolve().parent.parent

SEGMENT_WEB_TOLERANCE_M = 5.0
REGENCY_WEB_TOLERANCE_M = 30.0
NETWORK_WEB_TOLERANCE_M = 8.0

#: Attribution obligations, per ARCHITECTURE.md section 9. Static because the
#: set of upstream datasets is a project decision, not something derived
#: from data/ at build time.
SOURCES = [
    {
        "name": "OpenStreetMap contributors, via Overture Maps",
        "license": "ODbL 1.0",
        "url": "https://overturemaps.org",
    },
    {
        "name": "OpenTopoMap",
        "license": "CC BY-SA",
        "url": "https://opentopomap.org",
    },
    {
        "name": "Esri World Imagery",
        "license": "Esri terms of use (attribution required)",
        "url": "https://www.esri.com",
    },
    {
        "name": "SRTM (NASA/USGS), via AWS Terrain Tiles",
        "license": "Public domain",
        "url": "https://www2.jpl.nasa.gov/srtm/",
    },
    {
        "name": "geoBoundaries",
        "license": "CC BY 4.0",
        "url": "https://www.geoboundaries.org",
    },
]

OVERTURE_SEGMENT_FILE_CANDIDATES = [
    "segment.geojsonl",
    "segments.geojsonl",
    "segment.geojson",
    "segments.geojson",
]


# ---------------------------------------------------------------------------
# Node elevations
# ---------------------------------------------------------------------------


def fill_node_elevations(nodes_fc: dict, dem) -> dict:
    for feat in nodes_fc.get("features", []):
        lon, lat = feat["geometry"]["coordinates"][:2]
        elev = common.clamp_elevation(dem.elevation(lon, lat))
        feat["properties"]["elevation_m"] = round(elev, 1)
    return nodes_fc


# ---------------------------------------------------------------------------
# Web geometry simplification
# ---------------------------------------------------------------------------


def simplify_feature_collection(fc: dict, tolerance_m: float) -> dict:
    out = {"type": fc.get("type", "FeatureCollection"), "features": []}
    for feat in fc.get("features", []):
        new_feat = dict(feat)
        new_feat["geometry"] = common.simplify_geometry(feat.get("geometry"), tolerance_m)
        out["features"].append(new_feat)
    return out


# ---------------------------------------------------------------------------
# public-build filtering
# ---------------------------------------------------------------------------


def filter_public_geojson(fc: dict) -> dict:
    out = {"type": fc.get("type", "FeatureCollection"), "features": []}
    for feat in fc.get("features", []):
        if bool(feat.get("properties", {}).get("public")):
            out["features"].append(feat)
    return out


def filter_public_sections(sections: list) -> list:
    return [s for s in sections if bool(s.get("public"))]


def filter_public_routes(routes: list) -> list:
    return [r for r in routes if "public" in (r.get("audience") or [])]


# ---------------------------------------------------------------------------
# Overture track network -> network.geojson.gz
# ---------------------------------------------------------------------------


def find_overture_segments_file(overture_dir: Path) -> Optional[Path]:
    for name in OVERTURE_SEGMENT_FILE_CANDIDATES:
        candidate = overture_dir / name
        if candidate.exists():
            return candidate
    return None


def iter_geojson_features(path: Path):
    """Yield Features from either a .geojsonl (one Feature per line) or a
    .geojson (single FeatureCollection) file."""
    if path.suffix == ".geojsonl":
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)
    else:
        fc = common.read_json(path)
        yield from fc.get("features", [])


def build_network_bundle(path: Path, tolerance_m: float = NETWORK_WEB_TOLERANCE_M) -> dict:
    """Reduce an Overture ``segment`` extract to the web network layer:
    non-road subtypes dropped, properties reduced to class/subclass/surface/
    name (+ remoteness if the graph build has added it), geometry simplified.
    """
    features_out = []
    for feat in iter_geojson_features(path):
        props = feat.get("properties") or {}
        subtype = props.get("subtype")
        if subtype is not None and subtype != "road":
            continue

        new_props = {}
        if props.get("class") is not None:
            new_props["class"] = props["class"]
        if props.get("subclass") is not None:
            new_props["subclass"] = props["subclass"]
        if props.get("road_surface") is not None:
            new_props["surface"] = props["road_surface"]
        if props.get("name") is not None:
            new_props["name"] = props["name"]
        if props.get("remoteness") is not None:
            new_props["remoteness"] = props["remoteness"]

        geometry = common.simplify_geometry(feat.get("geometry"), tolerance_m)
        features_out.append({"type": "Feature", "geometry": geometry, "properties": new_props})

    return {"type": "FeatureCollection", "features": features_out}


#: Properties build_network.py's network_web export carries per segment
#: (see build_network.py's own module docstring, "network_web.geojson").
#: Kept as-is when building the web network layer from that file -- richer
#: than what build_network_bundle() can derive from a raw Overture extract
#: (surface_source and remoteness in particular require the graph build).
NETWORK_WEB_KEPT_PROPS = [
    "id",
    "class",
    "subclass",
    "surface",
    "surface_source",
    "name",
    "remoteness",
    "km",
]


def read_network_web_file(path: Path) -> dict:
    """Read a build_network.py ``network_web.geojson`` export, gzip-
    compressed or plain. Detected by content (the gzip magic bytes), not by
    filename suffix, so either ``network_web.geojson`` or
    ``network_web.geojson.gz`` (or any other name pointing at one of the
    two) works."""
    with open(path, "rb") as f:
        magic = f.read(2)
    opener = gzip.open if magic == b"\x1f\x8b" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def mean_vertex_spacing_m(fc: dict) -> Optional[float]:
    """Average distance between consecutive vertices across every
    LineString in a FeatureCollection (metres), weighted by edge count
    (not by feature). None if there is nothing to measure."""
    total_len_m = 0.0
    total_edges = 0
    for feat in fc.get("features", []):
        geometry = feat.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        total_len_m += common.geodesic_length_m(coords)
        total_edges += len(coords) - 1
    if total_edges == 0:
        return None
    return total_len_m / total_edges


def is_already_coarser_than(fc: dict, tolerance_m: float) -> bool:
    """True when a FeatureCollection's vertices are, on average, already at
    least ``tolerance_m`` apart. Douglas-Peucker simplification only removes
    a point when it deviates from a longer chord by less than the
    tolerance; once points are this far apart already, a pass at the same
    (or a finer) tolerance would remove essentially nothing, so it is
    skipped rather than spending time reprojecting and simplifying a whole
    network for no real reduction."""
    spacing = mean_vertex_spacing_m(fc)
    return spacing is not None and spacing >= tolerance_m


def build_network_bundle_from_network_web(
    network_web_fc: dict, tolerance_m: float = NETWORK_WEB_TOLERANCE_M
) -> tuple:
    """Build the web network layer directly from a build_network.py
    ``network_web`` export: keep its properties (see
    NETWORK_WEB_KEPT_PROPS) as-is, and simplify geometry to ``tolerance_m``
    only if the file is not already coarser (see is_already_coarser_than).

    Returns (network_fc, already_coarser) -- the second element is recorded
    for logging/meta only, it does not change the output.
    """
    already_coarser = is_already_coarser_than(network_web_fc, tolerance_m)
    features_out = []
    for feat in network_web_fc.get("features", []):
        props = feat.get("properties") or {}
        new_props = {k: props[k] for k in NETWORK_WEB_KEPT_PROPS if k in props}
        geometry = feat.get("geometry")
        if already_coarser:
            geometry = common.round_geometry(geometry)
        else:
            geometry = common.simplify_geometry(geometry, tolerance_m)
        features_out.append({"type": "Feature", "geometry": geometry, "properties": new_props})
    return {"type": "FeatureCollection", "features": features_out}, already_coarser


def write_network_gz(path: Path, network_fc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(network_fc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(payload)


# ---------------------------------------------------------------------------
# meta.json
# ---------------------------------------------------------------------------


def read_git_commit(repo_root: Path) -> Optional[str]:
    """Read the current commit hash from .git/HEAD without invoking git
    (the sandbox/CI policy for this project is to never shell out to git
    from the pipeline)."""
    git_dir = repo_root / ".git"
    head_file = git_dir / "HEAD"
    if not head_file.exists():
        return None
    try:
        head = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not head.startswith("ref:"):
        # Detached HEAD: the file holds the hash directly.
        return head or None

    ref = head.split(" ", 1)[1].strip()
    ref_file = git_dir / ref
    if ref_file.exists():
        try:
            return ref_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    packed_refs = git_dir / "packed-refs"
    if packed_refs.exists():
        try:
            for line in packed_refs.read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + ref):
                    return line.split(" ", 1)[0]
        except OSError:
            return None
    return None


def read_overture_release(overture_dir: Optional[Path]) -> Optional[str]:
    if overture_dir is None:
        return None
    manifest_path = overture_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = common.read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return None
    return manifest.get("release")


def build_attribution(sources: list) -> list:
    """Attribution strings for MapLibre's attribution control, in display order.

    Matches `MetaJSON.attribution: string[]` in web/src/data/store.ts — every source
    listed in `sources` must be credited somewhere in the running app (ARCHITECTURE.md
    §9), not just the ones whose basemap already carries its own attribution string.
    """
    return [f'{source["name"]} ({source["license"]})' for source in sources]


def build_meta(
    *,
    counts: dict,
    public_build: bool,
    overture_release: Optional[str],
    network_source: Optional[str] = None,
) -> dict:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "generated_at": generated_at,
        # `build_time` is the field name the web app's MetaJSON type actually reads;
        # kept alongside `generated_at` (which existing tests and tooling check) so
        # neither producer nor consumer has to change its field name.
        "build_time": generated_at,
        "git_commit": read_git_commit(REPO_ROOT),
        "public_build": public_build,
        "counts": counts,
        "sources": SOURCES,
        "attribution": build_attribution(SOURCES),
    }
    if overture_release:
        meta["overture_release"] = overture_release
    if network_source:
        # Which of the two network.geojson.gz code paths produced the file
        # this build wrote (see module docstring) -- "network-web" (from
        # build_network.py's own export, richer properties) or
        # "overture-dir" (reduced straight from a raw Overture extract).
        meta["network_source"] = network_source
    return meta


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data", help="Path to data/ (default: data)")
    parser.add_argument("--schemas", default="schemas", help="Path to schemas/ (default: schemas)")
    parser.add_argument("--dem-dir", required=True, help="Directory of SRTM .hgt tiles")
    parser.add_argument(
        "--regencies", required=True, help="Path to the raw geoBoundaries Flores regency GeoJSON"
    )
    parser.add_argument(
        "--overture-dir",
        default=None,
        help="Directory holding a fetch_overture.py extract "
        "(segment.geojsonl or segments.geojson). Used only when "
        "--network-web is absent. If it doesn't exist or holds no "
        "segments file, network.geojson.gz is skipped.",
    )
    parser.add_argument(
        "--network-web",
        default=None,
        help="Path to a build_network.py network_web.geojson or "
        ".geojson.gz export. Preferred over --overture-dir when given "
        "(and present): keeps its id/class/subclass/surface/"
        "surface_source/name/remoteness/km properties, simplifying "
        "geometry only if the file is not already coarser than "
        "NETWORK_WEB_TOLERANCE_M. Falls back to --overture-dir when this "
        "path is not given or does not exist.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (default: <repo>/web/public/data)",
    )
    parser.add_argument(
        "--public-build",
        action="store_true",
        help="Drop everything not opted into the public site before writing",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    data_dir = Path(args.data)
    schemas_dir = Path(args.schemas)
    out_dir = Path(args.out) if args.out else (REPO_ROOT / "web" / "public" / "data")
    overture_dir = Path(args.overture_dir) if args.overture_dir else None
    network_web_path = Path(args.network_web) if args.network_web else None

    # 1. Validate.
    report = validate.validate_data(data_dir, schemas_dir)
    report.print_report()
    if report.errors:
        print("build aborted: data/ has validation errors", file=sys.stderr)
        return 1

    # 2. Load canonical data.
    nodes_fc = common.read_geojson(data_dir / "nodes.geojson")
    pois_fc = common.read_geojson(data_dir / "pois.geojson")
    segments_fc = common.read_geojson(data_dir / "segments.geojson")
    sections = common.read_json(data_dir / "sections.json")
    routes = common.read_json(data_dir / "routes.json")

    dem = common.load_dem(args.dem_dir)

    # 3. Stats + profiles, computed on the original (unsimplified) geometry.
    segments_with_stats, routes_with_stats, profiles = build_profiles.build_profiles(
        segments_fc, routes, dem
    )

    # 4. Node elevations, from the DEM.
    fill_node_elevations(nodes_fc, dem)

    # 5. Simplify geometry for the web copy (after stats are computed).
    segments_web = simplify_feature_collection(segments_with_stats, SEGMENT_WEB_TOLERANCE_M)
    regencies_raw = common.load_regencies(args.regencies)
    regencies_web = simplify_feature_collection(regencies_raw, REGENCY_WEB_TOLERANCE_M)

    sections_out = sections
    routes_out = routes_with_stats
    nodes_out = nodes_fc
    pois_out = pois_fc

    # 6. Public-build filter.
    if args.public_build:
        nodes_out = filter_public_geojson(nodes_out)
        pois_out = filter_public_geojson(pois_out)
        segments_web = filter_public_geojson(segments_web)
        sections_out = filter_public_sections(sections_out)
        routes_out = filter_public_routes(routes_out)
        kept_ids = {f["properties"]["id"] for f in segments_web["features"]}
        kept_ids |= {r["id"] for r in routes_out}
        profiles = {k: v for k, v in profiles.items() if k in kept_ids}

    # 7. Track network layer (optional): prefer --network-web (richer,
    # already-classified properties from build_network.py); fall back to
    # reducing a raw --overture-dir extract only when it is absent.
    network_fc = None
    network_source = None
    if network_web_path is not None and network_web_path.exists():
        network_web_fc = read_network_web_file(network_web_path)
        network_fc, already_coarser = build_network_bundle_from_network_web(network_web_fc)
        network_source = "network-web"
        note = "kept as-is (already coarser than target tolerance)" if already_coarser else "simplified to target tolerance"
        print(f"network.geojson.gz from --network-web {network_web_path} ({note})")
        write_network_gz(out_dir / "network.geojson.gz", network_fc)
    elif network_web_path is not None:
        print(f"--network-web given but not found at {network_web_path}, falling back to --overture-dir")

    if network_fc is None and overture_dir is not None:
        segments_path = find_overture_segments_file(overture_dir)
        if segments_path is None:
            print(f"no Overture segments file found under {overture_dir}, skipping network.geojson.gz")
        else:
            network_fc = build_network_bundle(segments_path)
            network_source = "overture-dir"
            write_network_gz(out_dir / "network.geojson.gz", network_fc)

    # 8. Write the bundle.
    common.write_geojson(out_dir / "nodes.geojson", nodes_out)
    common.write_geojson(out_dir / "pois.geojson", pois_out)
    common.write_geojson(out_dir / "segments.geojson", segments_web)
    common.write_geojson(out_dir / "regencies.geojson", regencies_web)
    common.write_json(out_dir / "sections.json", sections_out)
    common.write_json(out_dir / "routes.json", routes_out)
    common.write_json(out_dir / "profiles.json", profiles)

    counts = {
        "nodes": len(nodes_out["features"]),
        "pois": len(pois_out["features"]),
        "segments": len(segments_web["features"]),
        "sections": len(sections_out),
        "routes": len(routes_out),
        "regencies": len(regencies_web["features"]),
    }
    if network_fc is not None:
        counts["network_features"] = len(network_fc["features"])

    meta = build_meta(
        counts=counts,
        public_build=bool(args.public_build),
        overture_release=read_overture_release(overture_dir),
        network_source=network_source,
    )
    common.write_json(out_dir / "meta.json", meta)

    print(f"Wrote web bundle to {out_dir}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
