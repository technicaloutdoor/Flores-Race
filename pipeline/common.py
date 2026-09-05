#!/usr/bin/env python3
"""common.py

Shared, small, pure helpers used by every other pipeline stage: GeoJSON I/O with
a stable on-disk format, geodesic and haversine distance, geometry simplification
for the web bundle, Douglas-Peucker decimation for elevation profiles, a thin
wrapper around ``dem.DEM`` that applies the project's "clamp bathymetry to zero"
rule, and a loader for the Flores regency polygons.

Kept dependency-light and GDAL-free (shapely, pyproj, numpy only) so it installs
anywhere, per ARCHITECTURE.md section 6.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from pyproj import Geod, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform

from dem import DEM

# ---------------------------------------------------------------------------
# Number / coordinate formatting
# ---------------------------------------------------------------------------

#: Convention (see docs/data-model.md and the shared brief): GeoJSON coordinates
#: are WGS84, [lon, lat], at most 6 decimal places (~0.11 m at the equator).
COORD_DECIMALS = 6


def round6(value: Union[int, float]) -> float:
    """Round a number to COORD_DECIMALS places, normalising -0.0 to 0.0."""
    r = round(float(value), COORD_DECIMALS)
    return 0.0 if r == 0 else r


def round_coords(coords: Any) -> Any:
    """Recursively round a nested GeoJSON coordinate structure to 6 decimals.

    Works for Point ([lon, lat]), LineString ([[lon, lat], ...]), Polygon,
    MultiPolygon, etc. -- anything JSON/shapely produces as nested lists or
    tuples of numbers.
    """
    if coords is None:
        return None
    if len(coords) == 0:
        return list(coords)
    first = coords[0]
    if isinstance(first, (int, float)):
        return [round6(c) for c in coords]
    return [round_coords(c) for c in coords]


def round_geometry(geometry: dict) -> dict:
    """Return a copy of a GeoJSON geometry dict with coordinates rounded."""
    if geometry is None:
        return None
    out = dict(geometry)
    if "coordinates" in out:
        out["coordinates"] = round_coords(out["coordinates"])
    return out


# ---------------------------------------------------------------------------
# GeoJSON read/write
# ---------------------------------------------------------------------------


def read_geojson(path: Union[str, Path]) -> dict:
    """Read a GeoJSON FeatureCollection from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _feature_id(feature: dict) -> str:
    props = feature.get("properties") or {}
    fid = props.get("id")
    if fid is None:
        # Fall back to the feature's own top-level id if present, else a
        # stable-ish sentinel so sorting doesn't crash on malformed input.
        fid = feature.get("id", "")
    return str(fid)


def write_geojson(path: Union[str, Path], feature_collection: dict) -> None:
    """Write a GeoJSON FeatureCollection: features sorted by id, coordinates
    rounded to 6 decimals, 2-space indent, trailing newline.

    Nobody hand-edits generated files (ARCHITECTURE.md #6), so the format is
    kept deterministic to keep diffs small and reviewable.
    """
    fc = {
        "type": feature_collection.get("type", "FeatureCollection"),
        "features": [],
    }
    features = list(feature_collection.get("features", []))
    features.sort(key=_feature_id)
    for feat in features:
        out_feat = dict(feat)
        if "geometry" in out_feat and out_feat["geometry"] is not None:
            out_feat["geometry"] = round_geometry(out_feat["geometry"])
        fc["features"].append(out_feat)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2, ensure_ascii=False)
        f.write("\n")


def read_json(path: Union[str, Path]) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Union[str, Path], obj: Any) -> None:
    """Write plain JSON (sections.json, routes.json, profiles.json, meta.json)
    with 2-space indent and a trailing newline. Order of arrays/objects is
    preserved as given by the caller -- these files carry meaningful order
    (sections by ``order``, routes as authored) that must not be reshuffled.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Distances
# ---------------------------------------------------------------------------

_GEOD = Geod(ellps="WGS84")

#: Mean earth radius used for the haversine approximation (metres). Matches
#: the value commonly used by GIS libraries (IUGG mean radius).
_EARTH_RADIUS_M = 6371008.8


def geodesic_length_m(coords: Sequence[Sequence[float]]) -> float:
    """Geodesic (ellipsoidal) length of a [lon, lat] polyline, in metres.

    Uses pyproj's ``Geod.line_length``, which is exact on the WGS84 ellipsoid
    (not a flat-earth approximation), matching what a GPS device or a proper
    GIS would report.
    """
    if coords is None or len(coords) < 2:
        return 0.0
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return float(_GEOD.line_length(lons, lats))


def geodesic_length_km(coords: Sequence[Sequence[float]]) -> float:
    return geodesic_length_m(coords) / 1000.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two points, in metres.

    A cheap approximation (spherical, not ellipsoidal) used for lightweight
    checks such as "is this segment endpoint near its node" where sub-metre
    precision does not matter. For anything that ends up in a Stats.length_km
    field, use ``geodesic_length_m`` instead.
    """
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


# ---------------------------------------------------------------------------
# Geometry simplification (web bundle)
# ---------------------------------------------------------------------------

#: Local projected CRS used purely as a flat, metric working space for
#: simplification tolerances. UTM zone 51S covers most of Flores; treating the
#: whole island with one zone introduces a small, uniform distortion that is
#: irrelevant at the tolerances we simplify to (5-30 m) -- see BRIEF/ARCHITECTURE.
_UTM_CRS = "EPSG:32751"
_WGS84_CRS = "EPSG:4326"

_TO_UTM = Transformer.from_crs(_WGS84_CRS, _UTM_CRS, always_xy=True)
_FROM_UTM = Transformer.from_crs(_UTM_CRS, _WGS84_CRS, always_xy=True)


def simplify_geometry(geometry: dict, tolerance_m: float) -> dict:
    """Simplify a GeoJSON geometry by reprojecting to a local metric CRS,
    running shapely's Douglas-Peucker simplify with the given tolerance in
    metres, and reprojecting back to WGS84.

    Points are returned unchanged (rounded only). A non-positive tolerance is
    a no-op (still rounds coordinates), so callers can pass 0 to mean "don't
    simplify".
    """
    if geometry is None:
        return None
    if geometry.get("type") == "Point" or tolerance_m is None or tolerance_m <= 0:
        return round_geometry(geometry)

    geom = shape(geometry)
    geom_utm = shapely_transform(_TO_UTM.transform, geom)
    simplified_utm = geom_utm.simplify(tolerance_m, preserve_topology=True)
    simplified_wgs84 = shapely_transform(_FROM_UTM.transform, simplified_utm)
    result = mapping(simplified_wgs84)
    result["coordinates"] = round_coords(result["coordinates"])
    return result


# ---------------------------------------------------------------------------
# Douglas-Peucker decimation for elevation profiles
# ---------------------------------------------------------------------------


def _perp_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    norm = math.hypot(dx, dy)
    if norm == 0:
        return math.hypot(px - x1, py - y1)
    return abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm


def douglas_peucker(points: Sequence[Sequence[float]], epsilon: float) -> list:
    """Ramer-Douglas-Peucker simplification of a 2D polyline (e.g. [km, m]
    or [distance_m, elevation_m] pairs). Iterative (explicit stack), not
    recursive, so it is safe on the long, noisy point lists a raw 50 m DEM
    sample produces.

    Returns the kept points, endpoints always included, in original order.
    """
    n = len(points)
    if n < 3 or epsilon <= 0:
        return [list(p) for p in points]

    keep = [False] * n
    keep[0] = True
    keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        x1, y1 = points[start][0], points[start][1]
        x2, y2 = points[end][0], points[end][1]
        max_dist = -1.0
        max_idx = -1
        for i in range(start + 1, end):
            px, py = points[i][0], points[i][1]
            d = _perp_distance(px, py, x1, y1, x2, y2)
            if d > max_dist:
                max_dist = d
                max_idx = i
        if max_dist > epsilon:
            keep[max_idx] = True
            stack.append((start, max_idx))
            stack.append((max_idx, end))

    return [list(points[i]) for i in range(n) if keep[i]]


def decimate_profile(
    points: Sequence[Sequence[float]],
    max_points: int = 400,
    initial_epsilon: float = 1.0,
    growth: float = 1.6,
    max_iterations: int = 60,
) -> list:
    """Decimate a profile (list of [x, y] pairs, e.g. [distance_m, elev_m])
    with Douglas-Peucker until it has at most ``max_points`` points.

    Epsilon grows geometrically until the target is met or ``max_iterations``
    is exhausted (returning the best -- smallest -- result found so far
    rather than looping forever on pathological input).
    """
    if len(points) <= max_points:
        return [list(p) for p in points]

    epsilon = initial_epsilon
    result = douglas_peucker(points, epsilon)
    tries = 0
    while len(result) > max_points and tries < max_iterations:
        epsilon *= growth
        result = douglas_peucker(points, epsilon)
        tries += 1
    return result


# ---------------------------------------------------------------------------
# DEM loading with the project's clamp-below-zero rule
# ---------------------------------------------------------------------------


def load_dem(dem_dir: Union[str, Path]) -> DEM:
    """Load the SRTM DEM sampler from a directory of .hgt tiles.

    Thin passthrough to ``dem.DEM`` -- kept here so every pipeline stage
    loads the DEM the same way and so the clamp helpers below live next to
    the thing they clamp.
    """
    return DEM(dem_dir)


def clamp_elevation(elevation: Optional[float]) -> float:
    """Apply the project's bathymetry rule: SRTM tiles include sea-floor
    depth as negative values, and voids come back as None from ``DEM``.
    Both cases mean "at or below sea level for our purposes", so both
    become 0.0 (see BRIEF.md / ARCHITECTURE.md section 6).
    """
    if elevation is None:
        return 0.0
    return max(0.0, float(elevation))


def sample_line_clamped(dem: DEM, coords: Sequence[Sequence[float]], step_m: float = 50) -> list:
    """Sample elevation along a [lon, lat] polyline every ``step_m`` metres,
    applying ``clamp_elevation`` to every sample.

    Returns a list of (distance_m, elevation_m) tuples, distance_m being the
    cumulative planar distance along the line as computed by
    ``dem.DEM.sample_line`` (straight-line segments between vertices; fine at
    the 50 m sampling step used here).
    """
    raw = dem.sample_line([tuple(c[:2]) for c in coords], step_m=step_m)
    return [(dist, clamp_elevation(elev)) for dist, elev in raw]


# ---------------------------------------------------------------------------
# Regencies
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Lowercase, kebab-case a display name for use as an id fragment."""
    out = []
    prev_dash = False
    for ch in text.strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")
    return slug


def load_regencies(path: Union[str, Path]) -> dict:
    """Load the raw geoBoundaries Flores regency extract and normalise it to
    the shape the rest of the pipeline and the app expect: a FeatureCollection
    of Polygon/MultiPolygon features whose properties are reduced to a stable
    ``id`` (``reg-<slug>``) and a display ``name`` (from ``shapeName``).

    Geometry is left at full resolution here; callers that need a simplified
    copy (e.g. build_web_data.py for the web bundle) simplify afterwards with
    ``simplify_geometry``.
    """
    raw = read_geojson(path)
    features = []
    for feat in raw.get("features", []):
        props = feat.get("properties", {})
        name = props.get("shapeName") or props.get("name") or "unknown"
        reg_id = f"reg-{slugify(name)}"
        features.append(
            {
                "type": "Feature",
                "geometry": feat.get("geometry"),
                "properties": {"id": reg_id, "name": name},
            }
        )
    return {"type": "FeatureCollection", "features": features}
