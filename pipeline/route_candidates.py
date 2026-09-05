#!/usr/bin/env python3
"""route_candidates.py — k candidate LineStrings per anchor pair, per cost profile.

Turns the routable graph built by `build_network.py` (`load_graph`) plus a human-chosen
ordered list of anchors (`data/routes.json` -> `<route>.anchors`, or `--anchors` for quick
testing) into `concept` / `overture-route` segment Features, following
`docs/data-model.md` exactly.

PIPELINE
  1. Resolve anchors (either from `--nodes` + `--routes` + `--route-id`, using the route's
     `anchors` node-id list in order, or from `--anchors "lon,lat[,label];..."`), then snap
     each to the nearest node of the loaded graph within `--snap-km` (a plain nearest-
     neighbour search over projected node coordinates -- fast enough with a few dozen
     anchors against tens of thousands of nodes that a KD-tree/STRtree buys nothing).
     An anchor with no graph node within range is "off-network": every pair touching it is
     skipped and the run says so, in the report, loudly.
  2. Precompute a per-metre cost for every edge, once, for each of three tunable profiles
     (see `PROFILES` below): `remote` (favour quiet tracks/paths and remoteness), `rideable`
     (like remote, but wary of narrow/stepped ways a loaded bike cannot use), `direct`
     (shortest path, a small safety penalty on trunk roads). Nothing is *forbidden* --
     bridges are often trunk roads with no alternative -- costs only bias Dijkstra.
  3. For each consecutive anchor pair and each profile: Dijkstra for the shortest (cost-
     wise) path, then up to `--k` alternatives by iterative penalisation of the edges just
     used (multiply their cost, rerun); an alternative is accepted if its Jaccard overlap
     (by `(seg, piece)` edge identity, direction-agnostic) with *every* already-accepted
     candidate for that profile is < 0.6 and its physical length is <= 1.6x the profile's
     first (shortest) candidate.
  4. Candidates from different profiles that turn out to be (near-)the same physical route
     (Jaccard overlap > 0.85) are merged: the representative comes from the more "remote"
     profile (precedence `remote` > `rideable` > `direct`), and every contributing profile
     is recorded.

     Caveat, deliberately handled here rather than skipped: `segments.schema.json` defines
     `route_profile` as a single-value enum (`remote` | `rideable` | `direct`), not a free
     string, and `docs/data-model.md` agrees ("cost profile that produced it"). A literal
     comma-joined multi-profile string would fail schema validation, and this module is
     required to fail loudly on an invalid feature rather than write one. So `route_profile`
     is set to the single most-remote contributing profile (satisfying "keep the one from
     the more remote profile"), and when more than one profile produced the same candidate
     that fact is preserved in `open_questions` instead of silently dropped.
  5. Each surviving candidate becomes one GeoJSON Feature (see `build_feature`): id
     `s-<from>-<to>-<variant>` (node ids without their `n-` prefix, variant lower-cased in
     the id, upper-case in the `variant` property -- matches the `s-ruteng-reo-a` example in
     `docs/data-model.md`), geometry the concatenated, joint-deduplicated, 6-decimal, u->v
     oriented edge coordinates, and every derived field documented next to the function that
     computes it (`compute_character`, `est_hab_km`, `compute_difficulty`, `aggregate_stats`).
     Variant letters for a (from_node, to_node) pair continue after whatever letters are
     already used for that pair in `--existing-segments` (if given) -- so hand-sketched `A`/
     `B` concept corridors keep their letters and computed candidates start at `C`.
  6. `--merge` (into `--existing-segments`, in place with `--in-place` or else to a file
     under `--out`) keeps every existing feature untouched *unless* it is itself a stale,
     regenerable computed candidate (`geometry_source == "overture-route"`,
     `status == "concept"`, no `scouting` entries) for a pair this run actually processed --
     those are replaced. A human's hand trace, a scouted segment, or any pair not in this
     run's anchor list is never touched. Without `--merge`, only the new candidates are
     written to `--out` ("standalone" mode).
  7. `--write-route <route-id>` chains, per pair, the best candidate by profile precedence
     (falling back to the existing variant `A` hand sketch, in `--existing-segments`, when a
     pair produced no candidate at all) into a new route variant alongside the base route
     read via `--route-id`, written to `routes.candidates.json` next to `--out` (or in place
     into `--routes` with `--in-place`).
  8. A per-pair report (straight-line distance, each profile's best length/ascent/track+path
     share, off-network anchors) plus totals for the chained route goes to stdout and
     `<out>/candidates_report.md`.
  9. Every emitted feature is validated against `schemas/segments.schema.json` (with
     `common.schema.json` resolved through a small local registry) before anything is
     written; a validation error aborts the whole run rather than writing a partial file.

This module owns its own small geometry/projection/schema-registry helpers rather than
importing them from `build_network.py` or `pipeline/common.py`, on purpose (see the shared
build brief): the only cross-module import is `build_network.load_graph`.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import networkx as nx
from shapely.geometry import LineString, Point, shape

from build_network import load_graph

PIPELINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PIPELINE_DIR.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"

# Metres per degree of latitude, fixed (matches build_network.py's own LocalProjection);
# adequate for the short (tens of km at most) distances this module ever compares --
# anchor snapping, water-point proximity, and projecting a candidate's own geometry.
_M_PER_DEG_LAT = 111_320.0

OPEN_QUESTION_VERIFY = (
    "Computed on the OpenStreetMap-derived network: verify the track/path sections exist "
    "and are passable with a loaded bike."
)

# ---------------------------------------------------------------------------
# Cost profiles -- tune here, nowhere else. Every multiplier is per metre of edge
# length; the final edge cost is length_m * (product of the factors that apply).
# ---------------------------------------------------------------------------
PROFILES: dict[str, dict[str, Any]] = {
    "remote": {
        "description": (
            "Prefer quiet tracks/paths/footways, then unclassified/residential/service; "
            "penalise tertiary/secondary/primary/trunk increasingly; a remoteness discount "
            "(more remote = cheaper) and a mild penalty for steep + paved edges."
        ),
        # Class tiers. track/path/footway/cycleway/pedestrian/steps are the classes a
        # scout can walk or ride without a fight, so they share the cheapest tier; steps
        # are not forbidden here (a scout can carry a bike) but ARE much costlier under
        # 'rideable', which cares about actually riding.
        "class_multiplier": {
            "track": 1.0, "path": 1.0, "footway": 1.0, "cycleway": 1.0, "pedestrian": 1.0,
            "steps": 1.0,
            "unclassified": 1.2, "residential": 1.2, "service": 1.2, "living_street": 1.2,
            "tertiary": 1.6, "secondary": 3.0, "primary": 4.0, "trunk": 6.0,
        },
        "default_class_multiplier": 1.2,  # unknown/other classes: treat like the middle tier
        "remoteness_coeff": 0.08,  # multiplier *= 1 - coeff * (remoteness - 1)
        "paved_surface_multiplier": 1.3,  # applied when surface == "paved"
        "paved_surface_exempt_classes": ("track", "path"),
        "grade_threshold_pct": 10.0,  # multiplier *= 1 + coeff * max(0, grade - threshold)
        "grade_coeff": 0.02,
    },
    "rideable": {
        "description": (
            "Like 'remote', but a loaded bike is the constraint: path/footway/steps cost "
            "more (steps far more), the remoteness discount is weaker, and pavement is a "
            "mild positive rather than a penalty."
        ),
        "class_multiplier": {
            "track": 1.0, "path": 1.4, "footway": 2.0, "cycleway": 1.0, "pedestrian": 1.0,
            "steps": 4.0,
            "unclassified": 1.2, "residential": 1.2, "service": 1.2, "living_street": 1.2,
            "tertiary": 1.6, "secondary": 3.0, "primary": 4.0, "trunk": 6.0,
        },
        "default_class_multiplier": 1.2,
        "remoteness_coeff": 0.04,
        "surface_multiplier": {"paved": 1.1, "unpaved": 0.9},  # else 1.0 (unknown*)
        "grade_threshold_pct": 10.0,
        "grade_coeff": 0.02,
    },
    "direct": {
        "description": "Plain shortest path; only a small safety penalty on trunk roads.",
        "class_multiplier": {"trunk": 1.2},
        "default_class_multiplier": 1.0,
    },
}

PROFILE_ORDER = ("remote", "rideable", "direct")
PROFILE_PRECEDENCE = {name: i for i, name in enumerate(PROFILE_ORDER)}


def edge_multiplier(profile: str, data: dict) -> float:
    """Per-metre cost multiplier for one graph edge under one `PROFILES` entry.

    Deliberately generic over the `PROFILES` dict shape so tuning the numbers above is
    enough to retune routing -- no other code needs to change.
    """
    spec = PROFILES[profile]
    cls = data["cls"]
    mult = spec["class_multiplier"].get(cls, spec["default_class_multiplier"])

    if "remoteness_coeff" in spec:
        mult *= 1.0 - spec["remoteness_coeff"] * (data["remoteness"] - 1)

    if "paved_surface_multiplier" in spec:
        if data["surface"] == "paved" and cls not in spec["paved_surface_exempt_classes"]:
            mult *= spec["paved_surface_multiplier"]
    if "surface_multiplier" in spec:
        mult *= spec["surface_multiplier"].get(data["surface"], 1.0)

    if "grade_threshold_pct" in spec:
        over = max(0.0, data["max_grade_pct"] - spec["grade_threshold_pct"])
        mult *= 1.0 + over * spec["grade_coeff"]

    return mult


def precompute_costs(G: "nx.MultiDiGraph") -> None:
    """Set `cost_<profile>` on every edge of `G`, once, for every profile in `PROFILES`."""
    for _u, _v, data in G.edges(data=True):
        for profile in PROFILES:
            data[f"cost_{profile}"] = data["length_m"] * edge_multiplier(profile, data)


# ---------------------------------------------------------------------------
# Small local geometry helpers (no shared code with build_network.py on purpose)
# ---------------------------------------------------------------------------


def _lon_scale(ref_lat_deg: float) -> float:
    return _M_PER_DEG_LAT * math.cos(math.radians(ref_lat_deg))


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in km. Used only for the report's straight-line column."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    s = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return s or "anchor"


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------


@dataclass
class Anchor:
    label: str
    node_id: str  # "n-..." identity used in from_node/to_node and the segment id
    lon: float
    lat: float
    graph_node: Optional[str] = None
    snap_km: Optional[float] = None


def parse_anchors_arg(spec: str) -> list[tuple[str, float, float]]:
    """Parse `--anchors "lon,lat[,label];lon,lat[,label];..."` -> [(label, lon, lat), ...]."""
    out = []
    for i, part in enumerate(spec.split(";")):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split(",")]
        if len(bits) < 2:
            raise ValueError(f"bad --anchors entry: {part!r} (expected lon,lat[,label])")
        lon, lat = float(bits[0]), float(bits[1])
        label = bits[2] if len(bits) > 2 and bits[2] else f"anchor{i + 1}"
        out.append((label, lon, lat))
    return out


def anchors_from_arg(spec: str) -> list[Anchor]:
    return [
        Anchor(label=label, node_id="n-" + slugify(label), lon=lon, lat=lat)
        for label, lon, lat in parse_anchors_arg(spec)
    ]


def anchors_from_route(nodes_path: Path, routes_path: Path, route_id: str) -> tuple[list[Anchor], dict]:
    """Anchors from `<route_id>.anchors` in `--routes`, resolved against `--nodes`.

    Returns (anchors, base_route_dict) -- the base route is also what `--write-route`
    copies `name`/`audience`/`target_km_range` from.
    """
    nodes_doc = json.loads(Path(nodes_path).read_text())
    by_id: dict[str, tuple[str, float, float]] = {}
    for feat in nodes_doc["features"]:
        pid = feat["properties"]["id"]
        lon, lat = feat["geometry"]["coordinates"][:2]
        by_id[pid] = (feat["properties"].get("name", pid), lon, lat)

    routes_doc = json.loads(Path(routes_path).read_text())
    route = next((r for r in routes_doc if r.get("id") == route_id), None)
    if route is None:
        raise SystemExit(f"route id {route_id!r} not found in {routes_path}")

    anchors = []
    for nid in route["anchors"]:
        if nid not in by_id:
            raise SystemExit(f"anchor node {nid!r} (route {route_id!r}) not found in {nodes_path}")
        name, lon, lat = by_id[nid]
        anchors.append(Anchor(label=name, node_id=nid, lon=lon, lat=lat))
    return anchors, route


def snap_anchors(G: "nx.MultiDiGraph", anchors: list[Anchor], snap_km: float) -> None:
    """Set `.graph_node` / `.snap_km` on each anchor, in place, from the nearest graph node.

    Plain nearest-neighbour search (no KD-tree/STRtree): a few dozen anchors against tens
    of thousands of nodes is fast enough without one, and it keeps this module's only
    external geometry dependency to shapely (used for water points and path geometry).
    """
    node_ids = list(G.nodes())
    if not node_ids:
        for a in anchors:
            a.graph_node, a.snap_km = None, None
        return

    lats = [G.nodes[n]["pos"][1] for n in node_ids]
    ref_lat = sum(lats) / len(lats)
    lon_scale = _lon_scale(ref_lat)
    xs = [G.nodes[n]["pos"][0] * lon_scale for n in node_ids]
    ys = [lat * _M_PER_DEG_LAT for lat in lats]

    for a in anchors:
        ax, ay = a.lon * lon_scale, a.lat * _M_PER_DEG_LAT
        best_i, best_d2 = 0, math.inf
        for i in range(len(node_ids)):
            d2 = (xs[i] - ax) ** 2 + (ys[i] - ay) ** 2
            if d2 < best_d2:
                best_i, best_d2 = i, d2
        dist_km = math.sqrt(best_d2) / 1000.0
        a.snap_km = dist_km
        a.graph_node = node_ids[best_i] if dist_km <= snap_km else None


# ---------------------------------------------------------------------------
# Routing: per-profile shortest path + alternatives by iterative penalisation
# ---------------------------------------------------------------------------


@dataclass
class RawCandidate:
    profile: str
    path: list[str]
    edges: list[tuple]  # (u, v, key, data), in traversal order
    length_m: float

    def edge_id_set(self) -> set:
        return {(d["seg"], d["piece"]) for (_u, _v, _k, d) in self.edges}


def path_edges(G: "nx.MultiDiGraph", path: list[str], cost_fn) -> list[tuple]:
    """The minimum-`cost_fn` parallel edge for each hop of `path`, as (u, v, key, data)."""
    out = []
    for u, v in zip(path[:-1], path[1:]):
        parallel = G[u][v]
        best_key = min(parallel, key=lambda k: cost_fn(parallel[k]))
        out.append((u, v, best_key, parallel[best_key]))
    return out


def find_profile_candidates(
    G: "nx.MultiDiGraph",
    s: str,
    t: str,
    profile: str,
    k: int,
    length_factor: float = 1.6,
    jaccard_max: float = 0.6,
    penalty_step: float = 2.5,
    max_attempts: Optional[int] = None,
) -> list[RawCandidate]:
    """Up to `k` accepted candidates for one (s, t, profile): the Dijkstra shortest path,
    then alternatives found by repeatedly multiplying the cost of the edges just used by
    `penalty_step` and rerouting, accepted when the new path's Jaccard overlap (by
    `(seg, piece)` edge identity) with *every* already-accepted candidate is < `jaccard_max`
    and its physical length is <= `length_factor` x the first candidate's length.
    """
    if s == t:
        return [RawCandidate(profile=profile, path=[s], edges=[], length_m=0.0)]

    cost_key = f"cost_{profile}"
    penalty: dict[tuple, float] = {}

    def cost_fn(data: dict) -> float:
        return data[cost_key] * penalty.get((data["seg"], data["piece"]), 1.0)

    def weight_fn(_u, _v, d):
        return min(cost_fn(attrs) for attrs in d.values())

    if max_attempts is None:
        max_attempts = max(6, k * 3)

    try:
        path = nx.dijkstra_path(G, s, t, weight=weight_fn)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

    edges = path_edges(G, path, cost_fn)
    first = RawCandidate(profile=profile, path=path, edges=edges, length_m=sum(d["length_m"] for *_, d in edges))
    accepted = [first]
    edge_sets = [first.edge_id_set()]

    last_path = path
    attempts = 0
    while len(accepted) < k and attempts < max_attempts:
        attempts += 1
        for (_u, _v, _key, d) in path_edges(G, last_path, cost_fn):
            eid = (d["seg"], d["piece"])
            penalty[eid] = penalty.get(eid, 1.0) * penalty_step
        try:
            path = nx.dijkstra_path(G, s, t, weight=weight_fn)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            break
        last_path = path
        edges = path_edges(G, path, cost_fn)
        length_m = sum(d["length_m"] for *_, d in edges)
        if length_m > first.length_m * length_factor:
            continue  # still explore further next iteration; just don't accept this one
        cand = RawCandidate(profile=profile, path=path, edges=edges, length_m=length_m)
        eset = cand.edge_id_set()
        if all(jaccard(eset, other) < jaccard_max for other in edge_sets):
            accepted.append(cand)
            edge_sets.append(eset)
    return accepted


@dataclass
class Cluster:
    representative: RawCandidate
    profiles: set

    def edge_id_set(self) -> set:
        return self.representative.edge_id_set()


def dedupe_candidates(raw: list[RawCandidate], overlap_threshold: float = 0.85) -> list[Cluster]:
    """Merge candidates (possibly from several profiles) that are essentially the same
    physical route (edge-set Jaccard overlap > `overlap_threshold`). The representative of
    each cluster is the one from the most 'remote' contributing profile (ties broken by
    shorter length); every profile that produced a matching candidate is recorded.
    """
    ordered = sorted(raw, key=lambda c: (PROFILE_PRECEDENCE[c.profile], c.length_m))
    clusters: list[Cluster] = []
    for cand in ordered:
        eset = cand.edge_id_set()
        match = next((cl for cl in clusters if jaccard(eset, cl.edge_id_set()) > overlap_threshold), None)
        if match is not None:
            match.profiles.add(cand.profile)
        else:
            clusters.append(Cluster(representative=cand, profiles={cand.profile}))
    return clusters


def next_letters(used: Iterable[str], n: int) -> list[str]:
    """`n` fresh variant letters continuing after the highest letter in `used`.

    Raises ``ValueError`` rather than emitting characters past ``'Z'`` -- the ``variant`` field
    is constrained to ``^[A-Z]$`` by ``schemas/segments.schema.json``, so silently returning e.g.
    ``'['`` would only surface later as an opaque schema-validation failure in `validate_features`.
    """
    start = 0
    for u in used:
        if u:
            start = max(start, ord(u[0].upper()) - ord("A") + 1)
    if start + n > 26:
        raise ValueError(
            f"cannot allocate {n} variant letter(s) starting from "
            f"{chr(ord('A') + start)!r}: only 26 letters (A-Z) exist"
        )
    return [chr(ord("A") + start + i) for i in range(n)]


# ---------------------------------------------------------------------------
# Per-candidate derived fields
# ---------------------------------------------------------------------------


def _node_pos(G: "nx.MultiDiGraph", n: str) -> tuple[float, float]:
    return G.nodes[n]["pos"]


def _orient_hop_coords(G: "nx.MultiDiGraph", u: str, v: str, data: dict) -> list[list[float]]:
    """`data["coords"]` is stored in the parent way's original order regardless of which
    direction this (u, v) edge represents (see `build_network.load_graph`'s docstring) --
    reverse it here when needed so it actually runs u -> v.
    """
    coords = data["coords"]
    pu, pv = _node_pos(G, u), _node_pos(G, v)
    start = coords[0]
    d_start_u = (start[0] - pu[0]) ** 2 + (start[1] - pu[1]) ** 2
    d_start_v = (start[0] - pv[0]) ** 2 + (start[1] - pv[1]) ** 2
    return list(reversed(coords)) if d_start_v < d_start_u else coords


def build_geometry(G: "nx.MultiDiGraph", edges: list[tuple]) -> list[list[float]]:
    """Concatenated, joint-deduplicated, 6-decimal coordinates, oriented start -> end."""
    out: list[list[float]] = []
    for (u, v, _key, data) in edges:
        pts = [[round(x, 6), round(y, 6)] for x, y in _orient_hop_coords(G, u, v, data)]
        if out and out[-1] == pts[0]:
            pts = pts[1:]
        out.extend(pts)
    return out


def aggregate_stats(edges: list[tuple]) -> dict:
    """Length/ascent/descent/elevation/surface+class mix/remoteness/track+path share from
    the edges of one candidate. `min_elev_m`/`max_elev_m` are the min/max of each edge's
    `mean_elev_m` (the only per-edge elevation `build_network.py` keeps) -- a coarse proxy;
    `build_profiles.py` recomputes both precisely from the DEM once a segment is accepted.
    """
    length_m = sum(d["length_m"] for *_, d in edges)
    ascent_m = sum(d["ascent_m"] for *_, d in edges)
    descent_m = sum(d["descent_m"] for *_, d in edges)
    elevs = [d["mean_elev_m"] for *_, d in edges]
    min_elev_m = min(elevs) if elevs else 0.0
    max_elev_m = max(elevs) if elevs else 0.0

    surface_mix: dict[str, float] = {}
    class_mix: dict[str, float] = {}
    for *_, d in edges:
        km = d["length_m"] / 1000.0
        surface_mix[d["surface"]] = surface_mix.get(d["surface"], 0.0) + km
        class_mix[d["cls"]] = class_mix.get(d["cls"], 0.0) + km

    unpaved_m = sum(d["length_m"] for *_, d in edges if d["surface"] != "paved")
    unpaved_pct = (unpaved_m / length_m * 100.0) if length_m else 0.0

    remoteness = 1
    if length_m:
        remoteness = round(sum(d["remoteness"] * d["length_m"] for *_, d in edges) / length_m)
        remoteness = max(1, min(5, remoteness))

    track_path_m = sum(d["length_m"] for *_, d in edges if d["cls"] in ("track", "path"))
    track_path_pct = (track_path_m / length_m * 100.0) if length_m else 0.0

    return {
        "length_m": length_m,
        "ascent_m": ascent_m,
        "descent_m": descent_m,
        "min_elev_m": min_elev_m,
        "max_elev_m": max_elev_m,
        "surface_mix": {k: round(v, 2) for k, v in surface_mix.items()},
        "class_mix": {k: round(v, 2) for k, v in class_mix.items()},
        "unpaved_pct": round(unpaved_pct, 1),
        "remoteness": remoteness,
        "track_path_pct": round(track_path_pct, 1),
    }


def est_hab_km(edges: list[tuple]) -> float:
    """Estimated hike-a-bike km, a documented heuristic (no field data yet):
    the full length of path/footway/steps steeper than 15% max grade, plus half the
    length of path/footway that is *not* that steep (steps below 15% are rare and not
    counted here -- see the module docstring's field-by-field notes for context).
    """
    hab = 0.0
    for *_, d in edges:
        km = d["length_m"] / 1000.0
        if d["cls"] in ("path", "footway", "steps") and d["max_grade_pct"] > 15:
            hab += km
        elif d["cls"] in ("path", "footway"):
            hab += km * 0.5
    return round(hab, 2)


# Difficulty table (documented heuristic): points from climbing rate (m of ascent per km)
# and from hike-a-bike share of the candidate's length, each 0-4, summed and halved (so the
# two contribute equally), +1, clamped to 1..5. Bands are "at least this value -> this many
# points"; the highest matching band wins.
_ASCENT_BANDS = ((0.0, 0), (15.0, 1), (30.0, 2), (50.0, 3), (80.0, 4))
_HAB_SHARE_BANDS = ((0.0, 0), (2.0, 1), (8.0, 2), (20.0, 3), (40.0, 4))


def _band_points(value: float, bands: tuple[tuple[float, int], ...]) -> int:
    points = bands[0][1]
    for threshold, p in bands:
        if value >= threshold:
            points = p
    return points


def compute_difficulty(length_km: float, ascent_m: float, hab_km: float) -> int:
    ascent_per_km = ascent_m / length_km if length_km else 0.0
    hab_share_pct = (hab_km / length_km * 100.0) if length_km else 0.0
    points = _band_points(ascent_per_km, _ASCENT_BANDS) + _band_points(hab_share_pct, _HAB_SHARE_BANDS)
    return max(1, min(5, 1 + round(points / 2)))


def compute_character(edges: list[tuple]) -> str:
    """Dominant surface/class bucket, by km: `singletrack` (path/footway), `paved`
    (surface paved or "likely paved"), `gravel` (track class, otherwise unpaved/unknown),
    `dirt` (everything else unpaved/unknown-surface). `mixed` if no bucket exceeds 60%.
    `hab` is a scouted-only character (data-model.md); a computed candidate never claims it.
    """
    buckets = {"singletrack": 0.0, "paved": 0.0, "gravel": 0.0, "dirt": 0.0}
    total = 0.0
    for *_, d in edges:
        km = d["length_m"] / 1000.0
        total += km
        if d["cls"] in ("path", "footway"):
            buckets["singletrack"] += km
        elif d["surface"] in ("paved", "unknown_likely_paved"):
            buckets["paved"] += km
        elif d["cls"] == "track":
            buckets["gravel"] += km
        else:
            buckets["dirt"] += km
    if total <= 0:
        return "unknown"
    label, km = max(buckets.items(), key=lambda kv: kv[1])
    return label if km / total > 0.6 else "mixed"


# ---------------------------------------------------------------------------
# Water points
# ---------------------------------------------------------------------------

_WATER_KIND_LABEL = {"spring": "spring", "hot_spring": "hot spring", "waterfall": "waterfall"}


def load_water_points(path: Optional[Path]) -> list[tuple[str, float, float]]:
    """(`class`, lon, lat) for spring/hot_spring/waterfall features in an Overture
    `water.geojsonl` extract. A feature's centroid stands in for its location -- most are
    already points, a handful of `spring` features are small polygons.
    """
    if path is None:
        return []
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            feat = json.loads(line)
            cls = feat.get("properties", {}).get("class")
            if cls not in _WATER_KIND_LABEL:
                continue
            centroid = shape(feat["geometry"]).centroid
            out.append((cls, centroid.x, centroid.y))
    return out


def find_water_points(
    geometry_coords: list[list[float]],
    water_points: list[tuple[str, float, float]],
    within_m: float = 250.0,
) -> list[str]:
    """`["spring ~ km 12.4 (OSM, unverified)", ...]` for water points within `within_m` of
    the candidate's own geometry, ordered by distance along it.
    """
    if not water_points or len(geometry_coords) < 2:
        return []
    ref_lat = sum(y for _x, y in geometry_coords) / len(geometry_coords)
    lon_scale = _lon_scale(ref_lat)
    line = LineString([(x * lon_scale, y * _M_PER_DEG_LAT) for x, y in geometry_coords])
    hits = []
    for cls, lon, lat in water_points:
        pt = Point(lon * lon_scale, lat * _M_PER_DEG_LAT)
        if line.distance(pt) <= within_m:
            km = line.project(pt) / 1000.0
            hits.append((km, f"{_WATER_KIND_LABEL[cls]} ~ km {km:.1f} (OSM, unverified)"))
    hits.sort(key=lambda t: t[0])
    return [s for _km, s in hits]


# ---------------------------------------------------------------------------
# Feature assembly
# ---------------------------------------------------------------------------


def _strip_n_prefix(node_id: str) -> str:
    return node_id[2:] if node_id.startswith("n-") else node_id


def build_feature(
    anchor_from: Anchor,
    anchor_to: Anchor,
    variant: str,
    profiles_used: set,
    edges: list[tuple],
    G: "nx.MultiDiGraph",
    water_points: list[tuple[str, float, float]],
) -> tuple[dict, dict]:
    stats = aggregate_stats(edges)
    length_km = stats["length_m"] / 1000.0
    hab_km = est_hab_km(edges)
    difficulty = compute_difficulty(length_km, stats["ascent_m"], hab_km)
    character = compute_character(edges)
    geometry_coords = build_geometry(G, edges)
    wpts = find_water_points(geometry_coords, water_points)

    seg_id = f"s-{_strip_n_prefix(anchor_from.node_id)}-{_strip_n_prefix(anchor_to.node_id)}-{variant.lower()}"
    primary_profile = min(profiles_used, key=lambda p: PROFILE_PRECEDENCE[p])

    open_questions = [OPEN_QUESTION_VERIFY]
    others = [p for p in PROFILE_ORDER if p in profiles_used and p != primary_profile]
    if others:
        open_questions.append(
            "Also the shortest path found under the "
            + " and ".join(f"'{p}'" for p in others)
            + " profile(s) (merged into this candidate; route_profile records only the "
            "most-remote one because the schema allows a single value)."
        )

    feature = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": geometry_coords},
        "properties": {
            "id": seg_id,
            "name": f"{anchor_from.label} → {anchor_to.label}",
            "from_node": anchor_from.node_id,
            "to_node": anchor_to.node_id,
            "variant": variant,
            "status": "concept",
            "geometry_source": "overture-route",
            "character": character,
            "est_hab_km": hab_km,
            "difficulty": difficulty,
            "remoteness": stats["remoteness"],
            "water_points": wpts,
            "hazards": [],
            "cultural_notes": "",
            "open_questions": open_questions,
            "stats": {
                "length_km": round(length_km, 2),
                "ascent_m": round(stats["ascent_m"], 1),
                "descent_m": round(stats["descent_m"], 1),
                "min_elev_m": round(stats["min_elev_m"], 1),
                "max_elev_m": round(stats["max_elev_m"], 1),
                "unpaved_pct": stats["unpaved_pct"],
            },
            "surface_mix": stats["surface_mix"],
            "class_mix": stats["class_mix"],
            "route_profile": primary_profile,
            "public": False,
            "sources": ["map:overture"],
        },
    }
    return feature, stats


# ---------------------------------------------------------------------------
# Schema validation (local registry, no import from validate.py)
# ---------------------------------------------------------------------------


def build_schema_registry(schemas_dir: Path):
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resources = []
    for schema_path in sorted(Path(schemas_dir).glob("*.schema.json")):
        contents = json.loads(schema_path.read_text())
        schema_id = contents.get("$id", schema_path.name)
        resources.append((schema_id, Resource.from_contents(contents, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


def validate_features(features: list[dict], schemas_dir: Path = SCHEMAS_DIR) -> list[str]:
    """Validate a list of segment Features against `segments.schema.json`, wrapped as a
    FeatureCollection so the schema (which describes the whole collection) applies.
    Returns human-readable error strings; empty means every feature is valid.
    """
    from jsonschema import Draft202012Validator

    registry = build_schema_registry(schemas_dir)
    schema = json.loads((Path(schemas_dir) / "segments.schema.json").read_text())
    instance = {"type": "FeatureCollection", "features": features}
    validator = Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    out = []
    for err in errors:
        loc = "/".join(str(p) for p in err.path) or "<root>"
        out.append(f"{loc}: {err.message}")
    return out


# ---------------------------------------------------------------------------
# Existing-segments handling (variant lettering + merge freeze rule)
# ---------------------------------------------------------------------------


def load_existing_segments(path: Optional[Path]) -> list[dict]:
    if path is None:
        return []
    doc = json.loads(Path(path).read_text())
    return doc.get("features", [])


def used_letters_for_pair(existing_features: list[dict], from_node: str, to_node: str) -> set[str]:
    out = set()
    for f in existing_features:
        p = f["properties"]
        if p.get("from_node") == from_node and p.get("to_node") == to_node:
            v = p.get("variant")
            if v:
                out.add(v)
    return out


def is_regenerable(feature: dict) -> bool:
    """A stale computed candidate: safe to replace on a re-run. Never true for anything a
    human touched (a different `geometry_source`/`status`, or any recorded scouting)."""
    p = feature["properties"]
    return (
        p.get("geometry_source") == "overture-route"
        and p.get("status") == "concept"
        and not p.get("scouting")
    )


def existing_variant(existing_features: list[dict], from_node: str, to_node: str, variant: str) -> Optional[dict]:
    for f in existing_features:
        p = f["properties"]
        if p.get("from_node") == from_node and p.get("to_node") == to_node and p.get("variant") == variant:
            return f
    return None


# ---------------------------------------------------------------------------
# Per-pair orchestration
# ---------------------------------------------------------------------------


@dataclass
class PairResult:
    anchor_from: Anchor
    anchor_to: Anchor
    straight_km: float
    off_network: bool
    no_path: bool
    profile_summary: dict  # profile -> {"length_km","ascent_m","track_path_pct"} | None
    features: list[dict]  # already-lettered, in cluster (precedence) order


def generate_pair(
    G: "nx.MultiDiGraph",
    anchor_from: Anchor,
    anchor_to: Anchor,
    k: int,
    existing_features: list[dict],
    water_points: list[tuple[str, float, float]],
) -> PairResult:
    straight_km = haversine_km(anchor_from.lon, anchor_from.lat, anchor_to.lon, anchor_to.lat)

    if anchor_from.graph_node is None or anchor_to.graph_node is None:
        return PairResult(anchor_from, anchor_to, straight_km, True, False, {p: None for p in PROFILE_ORDER}, [])

    raw_all: list[RawCandidate] = []
    summary: dict[str, Optional[dict]] = {}
    for profile in PROFILE_ORDER:
        cands = find_profile_candidates(G, anchor_from.graph_node, anchor_to.graph_node, profile, k)
        if cands:
            best = min(cands, key=lambda c: c.length_m)
            best_stats = aggregate_stats(best.edges)
            summary[profile] = {
                "length_km": best_stats["length_m"] / 1000.0,
                "ascent_m": best_stats["ascent_m"],
                "track_path_pct": best_stats["track_path_pct"],
            }
        else:
            summary[profile] = None
        raw_all.extend(cands)

    no_path = not raw_all
    clusters = dedupe_candidates(raw_all)
    try:
        letters = next_letters(
            used_letters_for_pair(existing_features, anchor_from.node_id, anchor_to.node_id),
            len(clusters),
        )
    except ValueError as exc:
        raise SystemExit(
            f"more than 26 variants for pair {anchor_from.node_id}→{anchor_to.node_id}, "
            f"aborting ({exc})"
        ) from exc

    features = []
    for cluster, letter in zip(clusters, letters):
        feat, _stats = build_feature(
            anchor_from, anchor_to, letter, cluster.profiles, cluster.representative.edges, G, water_points
        )
        features.append(feat)

    return PairResult(anchor_from, anchor_to, straight_km, False, no_path, summary, features)


# ---------------------------------------------------------------------------
# Route chain (--write-route) and report
# ---------------------------------------------------------------------------


def choose_route_segment(pair: PairResult, existing_features: list[dict]) -> tuple[Optional[str], str]:
    """The segment id to use for one pair in the computed route chain, and a short note.
    Cluster order already follows profile precedence then length (see `dedupe_candidates`),
    so the first feature is the best 'remote' candidate, or the best 'rideable'/'direct' one
    if 'remote' produced nothing for this pair.
    """
    if pair.features:
        best = pair.features[0]
        return best["properties"]["id"], f"computed ({best['properties']['route_profile']})"
    fallback = existing_variant(existing_features, pair.anchor_from.node_id, pair.anchor_to.node_id, "A")
    if fallback is not None:
        return fallback["properties"]["id"], "existing hand-sketch variant A (no computed candidate)"
    return None, "GAP: no computed candidate and no existing variant A"


def route_chain_stats(pairs: list[PairResult], chosen_ids: list[Optional[str]]) -> dict:
    """Roll up length/ascent/descent/unpaved/hab for the chosen chain, from the features
    that were actually generated this run (existing hand-sketch fallbacks are not
    re-summed here -- their stats are whatever build_profiles.py last computed for them,
    outside this module's reach).
    """
    by_id = {f["properties"]["id"]: f for pair in pairs for f in pair.features}
    length_km = ascent_m = descent_m = hab_km = unpaved_km = 0.0
    for sid in chosen_ids:
        if sid is None or sid not in by_id:
            continue
        p = by_id[sid]["properties"]
        length_km += p["stats"]["length_km"]
        ascent_m += p["stats"]["ascent_m"]
        descent_m += p["stats"]["descent_m"]
        hab_km += p["est_hab_km"]
        unpaved_km += p["stats"]["length_km"] * p["stats"]["unpaved_pct"] / 100.0
    unpaved_pct = (unpaved_km / length_km * 100.0) if length_km else 0.0
    return {
        "length_km": round(length_km, 1),
        "ascent_m": round(ascent_m, 0),
        "descent_m": round(descent_m, 0),
        "unpaved_pct": round(unpaved_pct, 1),
        "hab_km": round(hab_km, 1),
    }


def render_report(
    pairs: list[PairResult],
    off_network_anchors: list[tuple[str, float]],
    chosen: list[tuple[Optional[str], str]],
    route_totals: dict,
) -> str:
    lines = ["# Route candidate report", ""]

    if off_network_anchors:
        lines.append("## Anchors off-network")
        lines.append("")
        for label, dist_km in off_network_anchors:
            lines.append(f"- **{label}**: nearest graph node is {dist_km:.2f} km away (beyond --snap-km)")
        lines.append("")

    lines.append("## Per-pair candidates")
    lines.append("")
    lines.append("| Pair | Straight-line km | Remote: km / asc m / track+path % | Rideable | Direct | Notes |")
    lines.append("|---|---|---|---|---|---|")

    def cell(s):
        if s is None:
            return "no path"
        return f"{s['length_km']:.1f} / {s['ascent_m']:.0f} / {s['track_path_pct']:.0f}%"

    for pair in pairs:
        notes = []
        if pair.off_network:
            notes.append("anchor off-network, skipped")
        elif pair.no_path:
            notes.append("no path found (disconnected network component)")
        lines.append(
            f"| {pair.anchor_from.label} → {pair.anchor_to.label} | {pair.straight_km:.1f} | "
            f"{cell(pair.profile_summary.get('remote'))} | {cell(pair.profile_summary.get('rideable'))} | "
            f"{cell(pair.profile_summary.get('direct'))} | {'; '.join(notes)} |"
        )
    lines.append("")

    lines.append("## Computed route (best remote, fallback rideable/direct per pair)")
    lines.append("")
    for pair, (sid, note) in zip(pairs, chosen):
        label = sid or "(none)"
        lines.append(f"- {pair.anchor_from.label} → {pair.anchor_to.label}: `{label}` -- {note}")
    lines.append("")
    lines.append(
        f"**Totals:** {route_totals['length_km']:.1f} km, +{route_totals['ascent_m']:.0f} m / "
        f"-{route_totals['descent_m']:.0f} m, {route_totals['unpaved_pct']:.0f}% unpaved, "
        f"~{route_totals['hab_km']:.1f} km estimated hike-a-bike "
        f"(computed pairs only; existing hand-sketch fallbacks are not included in these totals)."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Merge / write
# ---------------------------------------------------------------------------


def merge_segments(
    existing_features: list[dict], processed_pairs: list[tuple[str, str]], new_features: list[dict]
) -> tuple[list[dict], dict]:
    """Combine `existing_features` with `new_features`: every existing feature survives
    untouched unless it is `is_regenerable` *and* its (from_node, to_node) is one of
    `processed_pairs` -- those are dropped, replaced by whatever `new_features` produced
    for that pair (possibly nothing, if this run found no path).
    """
    processed = set(processed_pairs)
    kept, dropped = [], []
    for f in existing_features:
        p = f["properties"]
        pair = (p.get("from_node"), p.get("to_node"))
        if pair in processed and is_regenerable(f):
            dropped.append(f)
        else:
            kept.append(f)
    merged = kept + new_features
    merged.sort(key=lambda f: f["properties"]["id"])
    report = {"kept": len(kept), "dropped": len(dropped), "added": len(new_features)}
    return merged, report


def write_geojson(features: list[dict], path: Path) -> None:
    features = sorted(features, key=lambda f: f["properties"]["id"])
    doc = {"type": "FeatureCollection", "features": features}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")


def build_route_variant(
    base_route: dict, write_route_id: str, pairs: list[PairResult], existing_features: list[dict]
) -> tuple[dict, list[str]]:
    chosen = [choose_route_segment(pair, existing_features) for pair in pairs]
    segment_ids = [sid for sid, _note in chosen if sid is not None]
    gap_notes = [
        f"{pair.anchor_from.label} → {pair.anchor_to.label}: {note}"
        for pair, (sid, note) in zip(pairs, chosen)
        if sid is None
    ]
    notes = (
        "Generated by route_candidates.py: chains the shortest 'remote' candidate per anchor "
        "pair (falling back to 'rideable', then 'direct', then the existing hand-sketch "
        "variant A where no computed candidate exists). A machine proposal, not a decision -- "
        "verify before scouting."
    )
    if gap_notes:
        notes += " Gaps: " + "; ".join(gap_notes)

    route = {
        "id": write_route_id,
        "name": f"{base_route['name']} (computed, remote profile)",
        "tagline": (
            "Shortest 'remote' path on the OpenStreetMap-derived track network; "
            "a machine proposal, not a route"
        ),
        "audience": ["stakeholder", "scout"],
        "anchors": list(base_route["anchors"]),
        "segments": segment_ids,
        "status": "concept",
        "target_km_range": list(base_route["target_km_range"]),
        "notes": notes,
    }
    return route, [note for _sid, note in chosen]


def write_routes(routes_arr: list[dict], new_route: dict, path: Path) -> None:
    out = [r for r in routes_arr if r.get("id") != new_route["id"]]
    out.append(new_route)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", required=True, type=Path, help="graph.json.gz from build_network.py")
    ap.add_argument("--nodes", type=Path, help="data/nodes.geojson (with --routes and --route-id)")
    ap.add_argument("--routes", type=Path, help="data/routes.json (with --nodes and --route-id)")
    ap.add_argument("--route-id", help="route id in --routes whose 'anchors' to use")
    ap.add_argument("--anchors", help='testing: "lon,lat[,label];lon,lat[,label];..."')
    ap.add_argument("--water", type=Path, help="Overture water.geojsonl, for water_points")
    ap.add_argument("--snap-km", type=float, default=2.5)
    ap.add_argument("--k", type=int, default=2, help="alternatives per profile per pair")
    ap.add_argument("--existing-segments", type=Path, help="segments.geojson to read variant letters from (and merge into, with --merge)")
    ap.add_argument("--merge", action="store_true", help="merge new candidates into --existing-segments")
    ap.add_argument("--in-place", action="store_true", help="overwrite --existing-segments / --routes instead of writing under --out")
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--write-route", metavar="ROUTE_ID", help="also write a chained route variant with this id")
    return ap


def resolve_anchors(args) -> tuple[list[Anchor], Optional[dict]]:
    if args.anchors:
        if args.nodes or args.routes or args.route_id:
            raise SystemExit("pass either --anchors or --nodes/--routes/--route-id, not both")
        return anchors_from_arg(args.anchors), None
    if args.nodes and args.routes and args.route_id:
        return anchors_from_route(args.nodes, args.routes, args.route_id)
    raise SystemExit("need --anchors, or --nodes + --routes + --route-id")


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.merge and not args.existing_segments:
        raise SystemExit("--merge requires --existing-segments")

    anchors, base_route = resolve_anchors(args)
    if args.write_route and base_route is None:
        raise SystemExit("--write-route requires --nodes/--routes/--route-id anchor mode (needs a base route)")

    G = load_graph(args.graph)
    precompute_costs(G)
    snap_anchors(G, anchors, args.snap_km)

    existing_features = load_existing_segments(args.existing_segments)
    water_points = load_water_points(args.water)

    off_network = [(a.label, a.snap_km) for a in anchors if a.graph_node is None]

    pairs: list[PairResult] = []
    for a_from, a_to in zip(anchors[:-1], anchors[1:]):
        pairs.append(generate_pair(G, a_from, a_to, args.k, existing_features, water_points))

    new_features = [f for pair in pairs for f in pair.features]

    errors = validate_features(new_features)
    if errors:
        print("SCHEMA VALIDATION FAILED -- aborting, nothing written:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)

    if args.merge:
        processed_pairs = [(p.anchor_from.node_id, p.anchor_to.node_id) for p in pairs if not p.off_network]
        merged, merge_report = merge_segments(existing_features, processed_pairs, new_features)
        out_path = args.existing_segments if args.in_place else (args.out / "segments.candidates.geojson")
        write_geojson(merged, out_path)
        print(
            f"merge: kept {merge_report['kept']} existing feature(s) untouched, "
            f"replaced {merge_report['dropped']} stale computed candidate(s), "
            f"added {merge_report['added']} new candidate(s) -> {out_path}"
        )
    else:
        out_path = args.out / "segments.candidates.geojson"
        write_geojson(new_features, out_path)
        print(f"standalone: wrote {len(new_features)} candidate(s) -> {out_path}")

    chosen = [choose_route_segment(pair, existing_features) for pair in pairs]
    route_totals = route_chain_stats(pairs, [sid for sid, _n in chosen])

    if args.write_route:
        route, _notes = build_route_variant(base_route, args.write_route, pairs, existing_features)
        routes_arr = json.loads(Path(args.routes).read_text())
        routes_out_path = args.routes if args.in_place else (args.out / "routes.candidates.json")
        write_routes(routes_arr, route, routes_out_path)
        print(f"wrote route variant {args.write_route!r} -> {routes_out_path}")

    report = render_report(pairs, off_network, chosen, route_totals)
    report_path = args.out / "candidates_report.md"
    report_path.write_text(report)
    print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
