#!/usr/bin/env python3
"""build_network.py — the routable track graph of Flores from the Overture extract.

Turns the raw Overture Maps `segment` / `connector` extract into a routable graph that
the rest of the pipeline (`route_candidates.py`) and the web app can use, plus a couple of
reports so a human can sanity-check the result.

INPUT SHAPE (as actually produced by `fetch_overture.py`, confirmed by inspection — not
the shape a generic Overture doc would lead you to expect):

* `segment.geojsonl` — one Feature per road/ferry way. Properties of interest: `id`,
  `subtype` (`road` | `water`), `class` (Overture road class, null for `water`),
  `subclass`, `name`, `road_surface` (present for ~14% of roads, else null),
  `road_flags` (list of `{values: [...], between: [start,end] | null}`, used here only
  to flag bridges/links/tunnels for the meta report — it does *not* carry one-way
  information in this extract), `access_restrictions` (list of `{access_type, when,
  between}` — this is where one-way *is* encoded: `access_type: "denied"`,
  `when.heading: "backward"`, `between: null` means the whole way is forward-only), and
  `connector_ids` — a **flat, ordered list of connector ids** (NOT the `{connector_id,
  at}` pairs the Overture schema allows — `fetch_overture.py` flattens them). Order was
  verified to run start-to-end along the geometry and every connector id was verified to
  sit exactly on a vertex of the segment's own LineString (except a handful — see below).
* `connector.geojsonl` — one Point Feature per connector id.
* `place.geojsonl` — one Point Feature per place, with `name` and `category` (Overture
  place category, flattened from `categories.primary`).

Because there is no `at` fraction on disk, this module reconstructs one: for each
connector id referenced by a segment it looks up the connector's coordinate, finds the
matching vertex of the segment's LineString, and turns the vertex's cumulative geodesic
distance into a 0..1 fraction. A handful of connector ids (15 segments island-wide, ~23 km
of track) are missing from `connector.geojsonl` entirely (extract edge effects); for those
that are the first or last id of a segment this is exact (a segment's first/last
connector is always its first/last vertex, no lookup needed); for the rare interior case
it falls back to spacing connectors evenly by index, which is an approximation confined to
one or two long segments and is reported in `graph_meta.json` under `caveats`.

WHAT THIS SCRIPT DOES
1. Loads connectors and places, filters segments to `subtype == "road"` (ferries carry
   `subtype == "water"` and a null class; they are dropped — this is a bike race).
2. Cuts every kept segment into edges (graph theory sense) between consecutive
   connectors using `shapely.ops.substring(..., normalized=True)` on the reconstructed
   `at` fractions. Every edge remembers its parent segment id and piece index.
3. Classes `steps`, `pedestrian`, `cycleway`, `living_street` are kept (a scout may have
   to walk a section) but counted separately in the meta report as "flagged" — the app
   and route_candidates.py should treat them with suspicion.
4. Surface: uses `road_surface` when present (`surface_source: "tag"`), otherwise infers
   one from `class` (`surface_source: "inferred"`):
     track / path / footway   -> "unpaved"
     trunk / primary /
       secondary               -> "paved"
     tertiary                  -> "unknown_likely_paved"
     unclassified / residential
       / service / unknown /
       steps / pedestrian /
       cycleway / living_street -> "unknown"
5. Samples the DEM every `--dem-step-m` metres along each edge (`dem.DEM.sample_line`),
   clamps negative (bathymetry) readings to 0, and derives `ascent_m` / `descent_m` /
   `mean_elev_m` from a 3-sample moving average of elevation (to damp SRTM noise — same
   idea as `build_profiles.py` will use for whole segments) and `max_grade_pct` from the
   steepest consecutive pair of that smoothed series.
6. Remoteness (1..5, "1 town roads, 5 nobody for a day", per `docs/data-model.md`) is
   computed per edge from its midpoint:
     - distance to the nearest trunk/primary/secondary edge ("main road"), via an
       STRtree of those edges' geometries;
     - distance to the nearest "settlement" — the nearer of (a) the nearest
       `class == "residential"` edge (a proxy for "there is a village grid here") and
       (b) the nearest Overture place point whose category is not one of the generic /
       physical-feature categories (`river`, `structure_and_geography`, `beach`,
       `mountain`, or a missing category) — again via STRtree.
     Both distances are bucketed independently against CLI-tunable thresholds
     (`--remote-main-thresholds`, `--remote-settlement-thresholds`, each 4 ascending km
     values whose upper bound is the boundary between remoteness levels 1-2, 2-3, 3-4 and
     4-5; beyond the fourth value is level 5) and the edge's remoteness is the *worse*
     (higher) of the two buckets. With the defaults `1, 2.5, 5, 8` and `1, 1.5, 2, 3`:
     both distances < 1 km -> 1 (matches the brief's town-roads example), and a main road
     more than 8 km away *and* a settlement more than 3 km away -> 5 (matches the
     brief's nobody-for-a-day example); 2, 3 and 4 sit in between.
     Distances are computed in a simple equirectangular metres projection centred on the
     island (`_project`, latitude scale fixed at the island's mean latitude) — adequate
     because remoteness only ever compares distances of a few kilometres, well inside the
     range where that approximation is sub-percent accurate; it is not used for anything
     that is reported in kilometres (those all use `pyproj.Geod`, true geodesic length).
7. Connectivity: weakly-connected components of the resulting graph (one-way edges are
   still connectivity, just not two-way travel), largest component's share of total
   length and of track/path length, and the 10 largest non-giant components (approximate
   centre + total km) — the gaps a scout should know about.

OUTPUTS (all under `--out`)
* `graph.json.gz` — gzip level 9, `{"nodes": {id: [lon, lat]}, "edges": [...]}`.
  Every node is a connector id that is an endpoint of at least one kept edge; coordinates
  rounded to 6 decimals. Each edge is a compact dict:
    u, v        endpoint node ids (u -> v is the direction of the original geometry)
    seg, i      parent segment id, 0-based piece index within that segment
    cls, sub    Overture class, subclass (subclass may be null)
    surf, surf_src   surface string, "tag" | "inferred"
    len         geodesic length, metres (round 1)
    asc, desc   ascent / descent, metres (round 1)
    grade       max grade, percent (round 2)
    elev        mean elevation, metres (round 1)
    rem         remoteness, 1..5
    oneway      true if only u -> v is traversable (ignored for track/path — see below)
    coords      the edge's own [lon, lat] pairs, rounded to 6 decimals
* `graph_meta.json` — counts, km by class, remoteness histogram, connectivity report,
  and every caveat this run hit (missing connectors, DEM voids, oversized web export...).
* `network_web.geojson` (+ gzip copy) — one LineString per *original* segment (not per
  edge), properties reduced to `id`, `class`, `subclass`, `surface`, `surface_source`,
  `name`, `remoteness` (length-weighted mode across the segment's edges), `km`.
  Coordinates rounded to 5 decimals. Target size is under ~12 MB gzipped; if the gzipped
  file comes out larger, `service`/`residential` segments shorter than 150 m are dropped
  from this export only (never from `graph.json.gz`) and the drop is reported.

`load_graph(path)` builds a `networkx.MultiDiGraph` from `graph.json.gz` for
`route_candidates.py` to import — see its docstring for the edge attribute names (they
are the un-abbreviated versions of the compact keys above, e.g. `length_m` not `len`).
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

import numpy as np
from pyproj import Geod
from shapely.geometry import LineString, Point
from shapely.ops import substring
from shapely.strtree import STRtree

try:
    from dem import DEM
except ImportError:  # pragma: no cover - fallback when imported from elsewhere
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dem import DEM

GEOD = Geod(ellps="WGS84")

# ---------------------------------------------------------------------------
# Classification tables
# ---------------------------------------------------------------------------

# Overture road classes we keep. Everything else (only `motorway`, none expected on
# Flores) is dropped. Classes in FLAGGED_CLASSES are kept but counted separately in the
# meta report: they are not really bike-race track network, but a rider may still have to
# walk a `footway`/`steps`, so we do not throw the data away.
KEEP_CLASSES = {
    "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "service", "track", "path", "footway", "unknown",
    "steps", "pedestrian", "cycleway", "living_street",
}
FLAGGED_CLASSES = {"steps", "pedestrian", "cycleway", "living_street"}
MAIN_ROAD_CLASSES = {"trunk", "primary", "secondary"}

# Surface inference when `road_surface` is null (see module docstring).
_UNPAVED = {"track", "path", "footway"}
_PAVED = {"trunk", "primary", "secondary"}
_LIKELY_PAVED = {"tertiary"}


def infer_surface(cls: str | None, road_surface: str | None) -> tuple[str, str]:
    """Return (surface, surface_source) for one segment.

    `surface_source` is "tag" when `road_surface` was present on the Overture record,
    "inferred" when it was derived from `class` per the table in the module docstring.
    """
    if road_surface:
        return road_surface, "tag"
    if cls in _UNPAVED:
        return "unpaved", "inferred"
    if cls in _PAVED:
        return "paved", "inferred"
    if cls in _LIKELY_PAVED:
        return "unknown_likely_paved", "inferred"
    return "unknown", "inferred"


# Place categories that do not indicate a settlement (physical features, generic geo
# entries, or a missing category). Everything else — a school, a church, a shop, a
# government office — is treated as "there is a village/town here".
_NON_SETTLEMENT_PLACE_CATEGORIES = {None, "river", "structure_and_geography", "beach", "mountain"}


def is_forward_only(access_restrictions: list | None) -> bool:
    """True if the Overture `access_restrictions` list makes this segment one-way.

    Matches the common, whole-segment case actually present in the extract:
    `{"access_type": "denied", "when": {"heading": "backward", ...}, "between": None}`
    (809 of 43033 road segments). Partial (`between` not covering [0, 1]) or otherwise
    shaped restrictions are left bidirectional — rare, and being permissive rather than
    accidentally cutting a scout off is the safer default; see `graph_meta.json`
    `caveats.partial_access_restrictions` for the count this run saw.
    """
    if not access_restrictions:
        return False
    for item in access_restrictions:
        if item.get("access_type") != "denied":
            continue
        when = item.get("when") or {}
        if when.get("heading") == "backward" and item.get("between") is None:
            return True
    return False


def has_partial_restriction(access_restrictions: list | None) -> bool:
    if not access_restrictions:
        return False
    return any(item.get("between") is not None for item in access_restrictions)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> Iterator[dict]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _flag_list(road_flags: list | None) -> list[str]:
    if not road_flags:
        return []
    out = []
    for item in road_flags:
        out.extend(item.get("values") or [])
    return out


# ---------------------------------------------------------------------------
# Local planar projection for the remoteness STRtrees (see module docstring §6)
# ---------------------------------------------------------------------------

_M_PER_DEG_LAT = 111_320.0


class LocalProjection:
    """A fixed-scale equirectangular projection, metres, centred on the island.

    Good for the short (a few km) distance comparisons remoteness needs; not used for
    anything reported in kilometres (those use `pyproj.Geod`).
    """

    def __init__(self, ref_lat_deg: float):
        self.ref_lat = ref_lat_deg
        self.m_per_deg_lon = _M_PER_DEG_LAT * math.cos(math.radians(ref_lat_deg))

    def point(self, lon: float, lat: float) -> Point:
        return Point(lon * self.m_per_deg_lon, lat * _M_PER_DEG_LAT)

    def linestring(self, coords: list[tuple[float, float]]) -> LineString:
        return LineString([(lon * self.m_per_deg_lon, lat * _M_PER_DEG_LAT) for lon, lat in coords])


def _nearest_distances(tree: STRtree, query_geoms: list) -> np.ndarray:
    """Vectorised nearest-neighbour distance for every geometry in `query_geoms`.

    Returns metres (or the tree's own unit); `inf` for any query when the tree is empty.
    """
    n = len(query_geoms)
    out = np.full(n, np.inf, dtype=float)
    if len(tree.geometries) == 0 or n == 0:
        return out
    idx, dist = tree.query_nearest(np.array(query_geoms, dtype=object), return_distance=True, all_matches=False)
    out[idx[0]] = dist
    return out


def _bucket(distances_m: np.ndarray, thresholds_km: tuple[float, float, float, float]) -> np.ndarray:
    """Map distances (metres) to remoteness levels 1..5 against 4 ascending km thresholds."""
    km = distances_m / 1000.0
    levels = np.full(km.shape, len(thresholds_km) + 1, dtype=int)
    for level, t in reversed(list(enumerate(thresholds_km, start=1))):
        levels[km < t] = level
    return levels


def parse_thresholds(s: str) -> tuple[float, float, float, float]:
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 4 or list(parts) != sorted(parts):
        raise argparse.ArgumentTypeError("expected 4 ascending comma-separated km values, e.g. '1,2.5,5,8'")
    return tuple(parts)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# DEM-derived edge stats
# ---------------------------------------------------------------------------


def _smooth3(values: list[float]) -> list[float]:
    """Centred 3-sample moving average; short arrays are returned unchanged."""
    n = len(values)
    if n < 3:
        return list(values)
    out = list(values)
    for i in range(1, n - 1):
        out[i] = (values[i - 1] + values[i] + values[i + 1]) / 3.0
    return out


def dem_edge_stats(dem: DEM, coords: list[tuple[float, float]], step_m: float) -> tuple[float, float, float, float]:
    """Return (ascent_m, descent_m, max_grade_pct, mean_elev_m) for one edge's polyline."""
    samples = dem.sample_line(coords, step_m=step_m)
    if not samples:
        return 0.0, 0.0, 0.0, 0.0
    dists = [d for d, _ in samples]
    elevs = [max(0.0, e) if e is not None else 0.0 for _, e in samples]
    mean_elev = statistics.fmean(elevs)
    smoothed = _smooth3(elevs)
    ascent = 0.0
    descent = 0.0
    max_grade = 0.0
    for i in range(1, len(smoothed)):
        dz = smoothed[i] - smoothed[i - 1]
        dx = dists[i] - dists[i - 1]
        if dz > 0:
            ascent += dz
        else:
            descent += -dz
        if dx > 0:
            grade = abs(dz / dx) * 100.0
            if grade > max_grade:
                max_grade = grade
    return ascent, descent, max_grade, mean_elev


# ---------------------------------------------------------------------------
# Graph build
# ---------------------------------------------------------------------------


class Edge:
    __slots__ = (
        "u", "v", "seg", "i", "cls", "sub", "surf", "surf_src",
        "len_m", "asc", "desc", "grade", "elev", "rem", "oneway", "coords",
    )

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def midpoint(self) -> tuple[float, float]:
        line = LineString(self.coords)
        p = line.interpolate(0.5, normalized=True)
        return p.x, p.y


def load_connectors(overture_dir: Path) -> dict[str, tuple[float, float]]:
    conns = {}
    for feat in _read_jsonl(overture_dir / "connector.geojsonl"):
        cid = feat["properties"]["id"]
        lon, lat = feat["geometry"]["coordinates"]
        conns[cid] = (lon, lat)
    return conns


def load_places(overture_dir: Path) -> list[tuple[float, float, str | None]]:
    places = []
    path = overture_dir / "place.geojsonl"
    if not path.exists():
        return places
    for feat in _read_jsonl(path):
        lon, lat = feat["geometry"]["coordinates"]
        places.append((lon, lat, feat["properties"].get("category")))
    return places


def cut_segment_edges(
    seg_id: str,
    coords: list[list[float]],
    connector_ids: list[str],
    connectors: dict[str, tuple[float, float]],
    caveats: Counter,
) -> list[tuple[str, str, LineString]]:
    """Split one segment's LineString into (u, v, piece_geometry) between consecutive
    connectors, reconstructing each connector's `at` fraction from the segment's own
    geometry (see module docstring)."""
    line = LineString(coords)
    n = len(coords)
    if n < 2 or len(connector_ids) < 2:
        return []

    # vertex coordinate -> index, exact match (verified: connectors sit exactly on
    # vertices in this extract).
    vertex_index = {}
    for idx, c in enumerate(coords):
        vertex_index[(c[0], c[1])] = idx

    lons = np.array([c[0] for c in coords])
    lats = np.array([c[1] for c in coords])
    _, _, seg_lengths = GEOD.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
    cum = np.concatenate(([0.0], np.cumsum(seg_lengths)))
    total = cum[-1]
    if total <= 0:
        return []

    n_c = len(connector_ids)
    ats = []
    for k, cid in enumerate(connector_ids):
        pt = connectors.get(cid)
        vidx = vertex_index.get(pt) if pt is not None else None
        if vidx is not None:
            ats.append(cum[vidx] / total)
        elif k == 0:
            ats.append(0.0)
        elif k == n_c - 1:
            ats.append(1.0)
        else:
            caveats["interior_connector_position_approximated"] += 1
            ats.append(k / (n_c - 1))
    # guard against any non-monotonic fallout (should not happen given the above)
    for k in range(1, len(ats)):
        if ats[k] < ats[k - 1]:
            ats[k] = ats[k - 1]

    pieces = []
    for k in range(n_c - 1):
        a, b = ats[k], ats[k + 1]
        if b <= a:
            continue
        piece = substring(line, a, b, normalized=True)
        if piece.is_empty or piece.length == 0:
            continue
        pieces.append((connector_ids[k], connector_ids[k + 1], piece))
    return pieces


def build_edges(
    overture_dir: Path,
    dem: DEM,
    dem_step_m: float,
    caveats: Counter,
) -> tuple[dict[str, tuple[float, float]], list[Edge], dict[str, dict]]:
    """Read segments + connectors, cut them into Edge objects.

    Returns (nodes actually used, list of Edge, per-segment metadata for the web export).
    """
    connectors = load_connectors(overture_dir)
    used_nodes: dict[str, tuple[float, float]] = {}
    edges: list[Edge] = []
    seg_meta: dict[str, dict] = {}
    class_counts: Counter = Counter()
    flagged_counts: Counter = Counter()
    flag_tag_counts: Counter = Counter()
    surface_source_counts: Counter = Counter()
    dropped_ferries = 0
    dropped_other_class = 0

    for feat in _read_jsonl(overture_dir / "segment.geojsonl"):
        props = feat["properties"]
        subtype = props.get("subtype")
        if subtype != "road":
            if subtype == "water":
                dropped_ferries += 1
            continue
        cls = props.get("class")
        if cls not in KEEP_CLASSES:
            dropped_other_class += 1
            continue

        seg_id = props["id"]
        coords = feat["geometry"]["coordinates"]
        connector_ids = props.get("connector_ids") or []
        oneway = is_forward_only(props.get("access_restrictions")) and cls not in {"track", "path"}
        if has_partial_restriction(props.get("access_restrictions")):
            caveats["partial_access_restrictions"] += 1
        surface, surface_source = infer_surface(cls, props.get("road_surface"))
        for flag in _flag_list(props.get("road_flags")):
            flag_tag_counts[flag] += 1

        pieces = cut_segment_edges(seg_id, coords, connector_ids, connectors, caveats)
        if not pieces:
            if connector_ids:
                caveats["segments_with_unresolvable_connectors"] += 1
            continue

        class_counts[cls] += 1
        if cls in FLAGGED_CLASSES:
            flagged_counts[cls] += 1
        surface_source_counts[surface_source] += 1

        seg_km = 0.0
        for i, (u, v, piece) in enumerate(pieces):
            piece_coords = list(piece.coords)
            length_m = GEOD.geometry_length(piece)
            asc, desc, grade, elev = dem_edge_stats(dem, piece_coords, dem_step_m)
            edge = Edge(
                u=u, v=v, seg=seg_id, i=i, cls=cls, sub=props.get("subclass"),
                surf=surface, surf_src=surface_source, len_m=length_m,
                asc=asc, desc=desc, grade=grade, elev=elev, rem=None,
                oneway=oneway, coords=[(round(c[0], 6), round(c[1], 6)) for c in piece_coords],
            )
            edges.append(edge)
            seg_km += length_m / 1000.0

            for node_id, node_pt in ((u, piece_coords[0]), (v, piece_coords[-1])):
                if node_id not in used_nodes:
                    real = connectors.get(node_id)
                    lon, lat = real if real is not None else (node_pt[0], node_pt[1])
                    used_nodes[node_id] = (round(lon, 6), round(lat, 6))

        seg_meta[seg_id] = {
            "class": cls, "subclass": props.get("subclass"), "surface": surface,
            "surface_source": surface_source, "name": props.get("name"),
            "km": seg_km, "n_pieces": len(pieces), "coords": coords,
        }

    caveats["dropped_ferry_segments"] = dropped_ferries
    caveats["dropped_out_of_scope_class_segments"] = dropped_other_class
    return used_nodes, edges, seg_meta, {
        "class_counts": class_counts, "flagged_counts": flagged_counts,
        "flag_tag_counts": flag_tag_counts, "surface_source_counts": surface_source_counts,
    }


def compute_remoteness(
    edges: list[Edge],
    places: list[tuple[float, float, str | None]],
    proj: LocalProjection,
    main_thresholds: tuple[float, float, float, float],
    settlement_thresholds: tuple[float, float, float, float],
) -> None:
    """Set `edge.rem` for every edge in place (see module docstring §6)."""
    main_geoms = [proj.linestring(e.coords) for e in edges if e.cls in MAIN_ROAD_CLASSES]
    residential_geoms = [proj.linestring(e.coords) for e in edges if e.cls == "residential"]
    settlement_geoms = list(residential_geoms)
    for lon, lat, cat in places:
        if cat in _NON_SETTLEMENT_PLACE_CATEGORIES:
            continue
        settlement_geoms.append(proj.point(lon, lat))

    main_tree = STRtree(main_geoms) if main_geoms else STRtree([])
    settlement_tree = STRtree(settlement_geoms) if settlement_geoms else STRtree([])

    midpoints = [proj.point(*e.midpoint()) for e in edges]
    d_main = _nearest_distances(main_tree, midpoints)
    d_settlement = _nearest_distances(settlement_tree, midpoints)

    lvl_main = _bucket(d_main, main_thresholds)
    lvl_settlement = _bucket(d_settlement, settlement_thresholds)
    lvl = np.maximum(lvl_main, lvl_settlement)
    for e, r in zip(edges, lvl):
        e.rem = int(r)


# ---------------------------------------------------------------------------
# Connectivity report
# ---------------------------------------------------------------------------


def connectivity_report(nodes: dict[str, tuple[float, float]], edges: list[Edge]) -> dict:
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(nodes.keys())
    for e in edges:
        g.add_edge(e.u, e.v, len_m=e.len_m, cls=e.cls)

    components = list(nx.connected_components(g))
    components.sort(key=len, reverse=True)
    total_len_km = sum(e.len_m for e in edges) / 1000.0

    def comp_len_km(nodeset: set[str]) -> float:
        return sum(
            data["len_m"] for u, v, data in g.edges(nodeset, data=True) if u in nodeset and v in nodeset
        ) / 1000.0

    giant = components[0] if components else set()
    giant_km = comp_len_km(giant)
    giant_track_path_km = sum(
        e.len_m for e in edges if e.cls in ("track", "path") and e.u in giant and e.v in giant
    ) / 1000.0
    total_track_path_km = sum(e.len_m for e in edges if e.cls in ("track", "path")) / 1000.0

    others = components[1:11]
    other_reports = []
    for comp in others:
        lons = [nodes[n][0] for n in comp]
        lats = [nodes[n][1] for n in comp]
        other_reports.append({
            "n_nodes": len(comp),
            "approx_centre": [round(statistics.fmean(lons), 5), round(statistics.fmean(lats), 5)],
            "total_km": round(comp_len_km(comp), 2),
        })

    return {
        "n_components": len(components),
        "largest_component_n_nodes": len(giant),
        "largest_component_km": round(giant_km, 1),
        "largest_component_share_of_total_km": round(giant_km / total_len_km, 4) if total_len_km else None,
        "track_path_share_of_largest_component_km": round(giant_track_path_km / giant_km, 4) if giant_km else None,
        "largest_component_share_of_all_track_path_km": (
            round(giant_track_path_km / total_track_path_km, 4) if total_track_path_km else None
        ),
        "largest_disconnected_components": other_reports,
    }


# ---------------------------------------------------------------------------
# Regency coverage (lightweight use of --regencies, for the meta report)
# ---------------------------------------------------------------------------


def regency_union(path: Path):
    from shapely.geometry import shape
    from shapely.ops import unary_union

    data = json.loads(path.read_text())
    polys = [shape(f["geometry"]) for f in data["features"]]
    return unary_union(polys)


def regency_coverage(nodes: dict[str, tuple[float, float]], edges: list[Edge], union_geom) -> dict:
    from shapely import points, contains, prepare

    prepare(union_geom)
    ids = list(nodes.keys())
    pts = points([nodes[i] for i in ids])
    inside = contains(union_geom, pts)
    inside_by_id = dict(zip(ids, inside.tolist()))
    total_km = sum(e.len_m for e in edges) / 1000.0
    outside_km = sum(
        e.len_m for e in edges if not (inside_by_id.get(e.u, False) and inside_by_id.get(e.v, False))
    ) / 1000.0
    return {
        "nodes_outside_regency_union": sum(1 for v in inside if not v),
        "km_with_an_endpoint_outside_regency_union": round(outside_km, 1),
        "share_of_total_km": round(outside_km / total_km, 4) if total_km else None,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_graph(out_dir: Path, nodes: dict[str, tuple[float, float]], edges: list[Edge]) -> Path:
    doc = {
        "nodes": {nid: list(xy) for nid, xy in nodes.items()},
        "edges": [
            {
                "u": e.u, "v": e.v, "seg": e.seg, "i": e.i, "cls": e.cls, "sub": e.sub,
                "surf": e.surf, "surf_src": e.surf_src, "len": round(e.len_m, 1),
                "asc": round(e.asc, 1), "desc": round(e.desc, 1), "grade": round(e.grade, 2),
                "elev": round(e.elev, 1), "rem": e.rem, "oneway": e.oneway,
                "coords": [list(c) for c in e.coords],
            }
            for e in edges
        ],
    }
    path = out_dir / "graph.json.gz"
    raw = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(raw)
    return path


def _segment_web_feature(seg_id: str, meta: dict, edges_by_seg: dict[str, list[Edge]]) -> dict:
    seg_edges = edges_by_seg.get(seg_id, [])
    rem_km: Counter = Counter()
    for e in seg_edges:
        rem_km[e.rem] += e.len_m
    remoteness = max(rem_km, key=lambda r: rem_km[r]) if rem_km else None
    coords = [[round(c[0], 5), round(c[1], 5)] for c in meta["coords"]]
    return {
        "type": "Feature",
        "id": seg_id,
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "id": seg_id,
            "class": meta["class"],
            "subclass": meta["subclass"],
            "surface": meta["surface"],
            "surface_source": meta["surface_source"],
            "name": meta["name"],
            "remoteness": remoteness,
            "km": round(meta["km"], 3),
        },
    }


def write_network_web(
    out_dir: Path, seg_meta: dict[str, dict], edges_by_seg: dict[str, list[Edge]],
    max_gzip_bytes: int, caveats: Counter,
) -> dict:
    features = [_segment_web_feature(sid, meta, edges_by_seg) for sid, meta in sorted(seg_meta.items())]
    doc = {"type": "FeatureCollection", "features": features}
    plain_path = out_dir / "network_web.geojson"
    gz_path = out_dir / "network_web.geojson.gz"

    def _write(feats):
        d = {"type": "FeatureCollection", "features": feats}
        text = json.dumps(d, indent=2, sort_keys=False)
        plain_path.write_text(text)
        with gzip.open(gz_path, "wb", compresslevel=9) as f:
            f.write(text.encode("utf-8"))
        return plain_path.stat().st_size, gz_path.stat().st_size

    plain_size, gz_size = _write(features)
    trimmed = False
    if gz_size > max_gzip_bytes:
        kept = [
            f for f in features
            if not (f["properties"]["class"] in ("service", "residential") and f["properties"]["km"] * 1000 < 150)
        ]
        dropped_n = len(features) - len(kept)
        if dropped_n:
            plain_size, gz_size = _write(kept)
            trimmed = True
            caveats["web_export_trimmed_short_service_residential_segments"] = dropped_n

    return {
        "n_features": len(features) if not trimmed else len(kept),
        "plain_bytes": plain_size,
        "gzip_bytes": gz_size,
        "trimmed_for_size": trimmed,
    }


# ---------------------------------------------------------------------------
# load_graph — the interface route_candidates.py imports
# ---------------------------------------------------------------------------


def load_graph(path) -> "networkx.MultiDiGraph":  # noqa: F821 - documented, imported lazily
    """Load `graph.json.gz` (as written by this module) into a `networkx.MultiDiGraph`.

    Nodes carry `pos = (lon, lat)`. Every edge carries, un-abbreviated from the on-disk
    compact keys:
      seg (str), piece (int), cls (str), subclass (str | None), surface (str),
      surface_source ("tag" | "inferred"), length_m (float), ascent_m (float),
      descent_m (float), max_grade_pct (float), mean_elev_m (float), remoteness (int 1-5),
      coords (list[[lon, lat]]).
    An edge is added u -> v always, and v -> u as well *unless* the underlying Overture
    way was one-way (`oneway` in the file) — one-way is ignored (both directions added)
    for `track` and `path` classes, matching build_network.py's own convention, so this
    is really just a safety net: build_network.py already never sets `oneway` for those
    two classes. `ascent_m`/`descent_m` are swapped on the reverse edge (climbing one way
    is descending the other); `length_m`, `max_grade_pct`, `remoteness`, `coords` etc.
    are identical in both directions (`coords` is kept in the original u->v order).
    """
    import networkx as nx

    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            doc = json.load(f)
    else:
        doc = json.loads(path.read_text())

    g = nx.MultiDiGraph()
    for nid, (lon, lat) in doc["nodes"].items():
        g.add_node(nid, pos=(lon, lat))

    for e in doc["edges"]:
        attrs = dict(
            seg=e["seg"], piece=e["i"], cls=e["cls"], subclass=e.get("sub"),
            surface=e["surf"], surface_source=e["surf_src"], length_m=e["len"],
            ascent_m=e["asc"], descent_m=e["desc"], max_grade_pct=e["grade"],
            mean_elev_m=e["elev"], remoteness=e["rem"], coords=e["coords"],
        )
        g.add_edge(e["u"], e["v"], **attrs)
        if not e.get("oneway") or e["cls"] in ("track", "path"):
            rev = dict(attrs, ascent_m=e["desc"], descent_m=e["asc"])
            g.add_edge(e["v"], e["u"], **rev)
    return g


# ---------------------------------------------------------------------------
# Sanity checks (printed + written into graph_meta.json under "sanity")
# ---------------------------------------------------------------------------

_CHECK_TOWNS = {
    "labuan_bajo": (119.888, -8.487),
    "ruteng": (120.469, -8.613),
    "ende": (121.660, -8.845),
    "maumere": (122.212, -8.620),
    "larantuka": (122.98, -8.34),
}


def run_sanity_checks(nodes: dict[str, tuple[float, float]], edges: list[Edge], proj: LocalProjection) -> dict:
    import networkx as nx

    total_km = sum(e.len_m for e in edges) / 1000.0

    g = nx.Graph()
    g.add_nodes_from(nodes.keys())
    for e in edges:
        g.add_edge(e.u, e.v, len_m=e.len_m)
    comp_of: dict[str, int] = {}
    for i, comp in enumerate(nx.connected_components(g)):
        for n in comp:
            comp_of[n] = i

    ids = list(nodes.keys())
    tree = STRtree([proj.point(*nodes[i]) for i in ids])
    snapped = {}
    for name, (lon, lat) in _CHECK_TOWNS.items():
        idx, dist = tree.query_nearest(np.array([proj.point(lon, lat)], dtype=object), return_distance=True)
        if len(idx[0]) and dist[0] <= 1000.0:
            snapped[name] = ids[idx[1][0]]
        else:
            snapped[name] = None

    comps = {name: (comp_of.get(nid) if nid else None) for name, nid in snapped.items()}
    same_component = len({c for c in comps.values() if c is not None}) == 1 and all(
        c is not None for c in comps.values()
    )

    path_km = None
    path_ascent_m = None
    if snapped.get("labuan_bajo") and snapped.get("larantuka"):
        dg = nx.MultiDiGraph()
        for e in edges:
            dg.add_edge(e.u, e.v, len_m=e.len_m, asc=e.asc, desc=e.desc)
            dg.add_edge(e.v, e.u, len_m=e.len_m, asc=e.desc, desc=e.asc)
        try:
            node_path = nx.shortest_path(dg, snapped["labuan_bajo"], snapped["larantuka"], weight="len_m")
            total_len_m = 0.0
            total_asc = 0.0
            for a, b in zip(node_path, node_path[1:]):
                best = min(dg.get_edge_data(a, b).values(), key=lambda d: d["len_m"])
                total_len_m += best["len_m"]
                total_asc += best["asc"]
            path_km = total_len_m / 1000.0
            path_ascent_m = total_asc
        except nx.NetworkXNoPath:
            path_km = None
            path_ascent_m = None

    return {
        "total_road_km_excluding_ferries": round(total_km, 1),
        "snapped_town_nodes": snapped,
        "towns_in_same_component": same_component,
        "labuan_bajo_to_larantuka_km": round(path_km, 1) if path_km is not None else None,
        "labuan_bajo_to_larantuka_ascent_m": round(path_ascent_m, 1) if path_ascent_m is not None else None,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overture-dir", required=True, type=Path, help="dir with segment/connector/place .geojsonl")
    ap.add_argument("--dem-dir", required=True, type=Path, help="dir with SRTM .hgt tiles")
    ap.add_argument("--regencies", required=True, type=Path, help="flores_regencies.geojson (coverage report only)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--dem-step-m", type=float, default=50.0)
    ap.add_argument("--web-max-gzip-mb", type=float, default=12.0)
    ap.add_argument(
        "--remote-main-thresholds", type=parse_thresholds, default=(1.0, 2.5, 5.0, 8.0),
        help="4 ascending km values: distance-to-main-road bucket boundaries for remoteness levels 1-2/2-3/3-4/4-5",
    )
    ap.add_argument(
        "--remote-settlement-thresholds", type=parse_thresholds, default=(1.0, 1.5, 2.0, 3.0),
        help="4 ascending km values: distance-to-settlement bucket boundaries for remoteness levels 1-2/2-3/3-4/4-5",
    )
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    caveats: Counter = Counter()

    print("Loading DEM...", file=sys.stderr)
    dem = DEM(args.dem_dir)

    print("Cutting segments into edges...", file=sys.stderr)
    nodes, edges, seg_meta, tallies = build_edges(args.overture_dir, dem, args.dem_step_m, caveats)
    print(f"  {len(nodes)} nodes, {len(edges)} edges, {len(seg_meta)} source segments", file=sys.stderr)

    ref_lat = statistics.fmean(lat for _, lat in nodes.values()) if nodes else -8.55
    proj = LocalProjection(ref_lat)

    print("Loading places and computing remoteness...", file=sys.stderr)
    places = load_places(args.overture_dir)
    compute_remoteness(edges, places, proj, args.remote_main_thresholds, args.remote_settlement_thresholds)
    remoteness_hist = Counter(e.rem for e in edges)

    print("Connectivity report...", file=sys.stderr)
    conn_report = connectivity_report(nodes, edges)

    print("Regency coverage...", file=sys.stderr)
    try:
        union_geom = regency_union(args.regencies)
        coverage = regency_coverage(nodes, edges, union_geom)
    except Exception as exc:  # pragma: no cover - best-effort report
        coverage = {"error": str(exc)}

    print("Sanity checks...", file=sys.stderr)
    sanity = run_sanity_checks(nodes, edges, proj)

    print("Writing graph.json.gz...", file=sys.stderr)
    graph_path = write_graph(args.out, nodes, edges)

    edges_by_seg: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        edges_by_seg[e.seg].append(e)

    print("Writing network_web.geojson...", file=sys.stderr)
    web_report = write_network_web(
        args.out, seg_meta, edges_by_seg, int(args.web_max_gzip_mb * 1_000_000), caveats,
    )

    km_by_class = Counter()
    for e in edges:
        km_by_class[e.cls] += e.len_m / 1000.0
    km_by_class = {k: round(v, 1) for k, v in km_by_class.items()}

    meta = {
        "counts": {
            "nodes": len(nodes), "edges": len(edges), "source_segments": len(seg_meta),
            "class_counts": dict(tallies["class_counts"]),
            "flagged_class_counts": dict(tallies["flagged_counts"]),
            "surface_source_counts": dict(tallies["surface_source_counts"]),
            "road_flag_tag_counts": dict(tallies["flag_tag_counts"]),
            "oneway_edges": sum(1 for e in edges if e.oneway),
        },
        "km_by_class": km_by_class,
        "total_km": round(sum(e.len_m for e in edges) / 1000.0, 1),
        "remoteness_histogram": {str(k): v for k, v in sorted(remoteness_hist.items())},
        "remoteness_thresholds_km": {
            "main_road": list(args.remote_main_thresholds),
            "settlement": list(args.remote_settlement_thresholds),
        },
        "connectivity": conn_report,
        "regency_coverage": coverage,
        "web_export": web_report,
        "sanity": sanity,
        "caveats": dict(caveats),
        "files": {
            "graph.json.gz": graph_path.stat().st_size,
        },
    }
    meta_path = args.out / "graph_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=False))

    print(json.dumps(meta, indent=2)[:4000], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
