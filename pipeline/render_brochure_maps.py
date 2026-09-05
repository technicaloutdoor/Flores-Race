#!/usr/bin/env python3
"""Render brochure cartography for the Flores Race, fully offline.

Produces, under --out:
  maps/overview.png, maps/overview-clean.png
  maps/sec-01.png .. sec-10.png
  maps/opt-<id>.png (one per exports/brochure_config.json option)
and, reading JSON profiles from --profiles-dir:
  profiles/<id>.png

All relief comes from local SRTM .hgt tiles, all coastline/lake/road vectors
from a local Overture Maps extract; no network access is made. See
pipeline/README.md and docs/data-model.md for the data contract this reads.
"""
from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LightSource
from matplotlib.collections import LineCollection
from matplotlib.patches import Polygon as MplPolygon, Circle, RegularPolygon, FancyArrow
from matplotlib.patheffects import withStroke
from pyproj import Transformer
from scipy.ndimage import map_coordinates

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("render_brochure_maps")

matplotlib.rcParams["font.family"] = "DejaVu Sans"

TO_MERC = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

# ---------------------------------------------------------------------------
# Small fixed palette, stable per option id across every map that draws it.
OPTION_PALETTE = ["#1b998b", "#e09f3e", "#6f4a8e", "#6b8e23", "#4a6fa5", "#9c4a1a", "#5c7f8a"]
MAIN_COLOR = "#c8102e"
ISLAND_BBOX = (119.75, -9.0, 123.15, -8.0)
NAMED_TOWNS = ["Labuan Bajo", "Ruteng", "Bajawa", "Ende", "Maumere", "Larantuka", "Riung", "Reo", "Mbay"]
VOLCANO_LABELS = ["Inerie", "Ebulobo", "Kelimutu", "Egon", "Lewotobi Laki-laki", "Ile Mandiri",
                  "Poco Mandasawu", "Wai Sano"]
POI_CATEGORY_COLOR = {
    "volcano": "#a3341f", "crater-lake": "#1a7fa0", "waterfall": "#1a6fa0", "beach": "#c99a3a",
    "traditional-village": "#8a5a2b", "heritage": "#6f4a8e", "religious": "#6f4a8e",
    "weaving": "#8a5a2b", "viewpoint": "#2c7a6b", "hot-spring": "#c9601a", "cave": "#5a5a5a",
    "market": "#333333", "rice-terrace": "#4a7a2b", "national-park": "#2c7a3b",
    "airport": "#333333", "port": "#1a5a8a", "savanna": "#a68a4a", "forest": "#2c7a3b",
    "other": "#666666",
}
ROAD_STYLE = {  # class -> (color, linewidth, dash)
    "trunk": ("#8a8a86", 1.6, None),
    "primary": ("#8a8a86", 1.3, None),
    "secondary": ("#9a9a96", 1.0, None),
    "tertiary": ("#b3b0a8", 0.7, None),
    "unclassified": ("#b3b0a8", 0.6, None),
    "track": ("#8a6a4a", 0.6, (1, 1.6)),
    "path": ("#8a6a4a", 0.5, (1, 1.6)),
}


def dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def geod_cum_km(coords):
    """Cumulative distance in km along a lon/lat polyline, planar-equirect approx at local lat."""
    if len(coords) < 2:
        return np.zeros(len(coords))
    arr = np.asarray(coords, dtype=float)
    lat0 = np.radians(np.mean(arr[:, 1]))
    dx = (arr[1:, 0] - arr[:-1, 0]) * 111.32 * np.cos(lat0)
    dy = (arr[1:, 1] - arr[:-1, 1]) * 110.57
    seglen = np.hypot(dx, dy)
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    return cum


def to_merc(coords):
    arr = np.asarray(coords, dtype=float)
    x, y = TO_MERC.transform(arr[:, 0], arr[:, 1])
    return np.column_stack([x, y])


def bbox_of(coords):
    arr = np.asarray(coords, dtype=float)
    return arr[:, 0].min(), arr[:, 1].min(), arr[:, 0].max(), arr[:, 1].max()


def split_on_jumps(arr, max_jump_deg=0.03):
    """Split a polyline wherever consecutive vertices jump implausibly far.

    Some Overture land-cover polygons carry seam artifacts from their source tiling: a ring
    that runs straight along an exact integer-degree line for a long stretch before jumping
    back. Left whole, that draws as a bogus straight line across the map; split at the jump
    so each real piece still renders as a plain polyline.
    """
    if len(arr) < 2:
        return [arr]
    d = np.hypot(np.diff(arr[:, 0]), np.diff(arr[:, 1]))
    cut_idx = np.nonzero(d > max_jump_deg)[0]
    if len(cut_idx) == 0:
        return [arr]
    pieces = []
    start = 0
    for c in cut_idx:
        if c + 1 - start >= 2:
            pieces.append(arr[start:c + 1])
        start = c + 1
    if len(arr) - start >= 2:
        pieces.append(arr[start:])
    return pieces


def pad_bbox(bbox, frac, min_width_km=None):
    lon0, lat0, lon1, lat1 = bbox
    lat_c = (lat0 + lat1) / 2
    w = lon1 - lon0
    h = lat1 - lat0
    if min_width_km:
        min_w_deg = min_width_km / (111.32 * np.cos(np.radians(lat_c)))
        if w < min_w_deg:
            cx = (lon0 + lon1) / 2
            lon0, lon1 = cx - min_w_deg / 2, cx + min_w_deg / 2
            w = min_w_deg
    px, py = w * frac, h * frac
    return (lon0 - px, lat0 - py, lon1 + px, lat1 + py)


def merc_bbox(bbox):
    lon0, lat0, lon1, lat1 = bbox
    x0, y0 = TO_MERC.transform(lon0, lat0)
    x1, y1 = TO_MERC.transform(lon1, lat1)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def fit_aspect(bbox, target_wh):
    """Expand a lon/lat bbox (in its own Mercator projection) to match target width/height ratio."""
    x0, y0, x1, y1 = merc_bbox(bbox)
    w, h = x1 - x0, y1 - y0
    target = target_wh[0] / target_wh[1]
    cur = w / h
    if cur < target:
        new_w = h * target
        cx = (x0 + x1) / 2
        x0, x1 = cx - new_w / 2, cx + new_w / 2
    else:
        new_h = w / target
        cy = (y0 + y1) / 2
        y0, y1 = cy - new_h / 2, cy + new_h / 2
    lon0, lat0 = TO_MERC.transform(x0, y0, direction="INVERSE")
    lon1, lat1 = TO_MERC.transform(x1, y1, direction="INVERSE")
    return (lon0, lat0, lon1, lat1), (x0, y0, x1, y1)


# ---------------------------------------------------------------------------
# DEM mosaic + relief basemap, cached in the scratch dir.

def load_dem_mosaic(dem_dir: Path, cache_dir: Path):
    npy = cache_dir / "dem_mosaic.npy"
    meta_p = cache_dir / "dem_mosaic_meta.json"
    if npy.exists() and meta_p.exists():
        return np.load(npy, mmap_mode="r"), json.loads(meta_p.read_text())
    lat_tiles = [-8, -9]  # north row first (S08: -8..-7), then south row (S09: -9..-8)
    lon_tiles = [119, 120, 121, 122]
    row_blocks = []
    for li, lat0 in enumerate(lat_tiles):
        col_blocks = []
        for lj, lon0 in enumerate(lon_tiles):
            name = f"S{abs(lat0):02d}E{lon0:03d}"
            fp = dem_dir / f"{name}.hgt"
            if fp.exists():
                tile = np.frombuffer(fp.read_bytes(), dtype=">i2").reshape(3601, 3601).astype(np.float32)
            else:
                log.warning("missing DEM tile %s, filling with 0", name)
                tile = np.zeros((3601, 3601), dtype=np.float32)
            tile = np.where(tile == -32768, 0.0, tile)
            keep_cols = 3600 if lj < len(lon_tiles) - 1 else 3601
            col_blocks.append(tile[:, :keep_cols])
        row = np.concatenate(col_blocks, axis=1)
        keep_rows = 3600 if li < len(lat_tiles) - 1 else 3601
        row_blocks.append(row[:keep_rows, :])
    mosaic = np.concatenate(row_blocks, axis=0)
    meta = {"lon_min": 119.0, "lat_max": -7.0, "pixel_deg": 1.0 / 3600.0,
            "height": mosaic.shape[0], "width": mosaic.shape[1]}
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(npy, mosaic.astype(np.float32))
    meta_p.write_text(json.dumps(meta))
    return np.load(npy, mmap_mode="r"), meta


def crop_indices(meta: dict, bbox, margin_px: int = 60):
    lon0, lat0, lon1, lat1 = bbox
    col0 = int(np.floor((lon0 - meta["lon_min"]) / meta["pixel_deg"])) - margin_px
    col1 = int(np.ceil((lon1 - meta["lon_min"]) / meta["pixel_deg"])) + margin_px
    row0 = int(np.floor((meta["lat_max"] - lat1) / meta["pixel_deg"])) - margin_px
    row1 = int(np.ceil((meta["lat_max"] - lat0) / meta["pixel_deg"])) + margin_px
    col0, row0 = max(0, col0), max(0, row0)
    col1, row1 = min(meta["width"], col1), min(meta["height"], row1)
    return row0, row1, col0, col1


def crop_elev_auto(dem: np.ndarray, meta: dict, bbox, margin_px: int = 60, max_pixels: int = 6_000_000):
    """Slice the DEM mosaic memmap to bbox, downsampling just enough to keep the crop small.

    Building relief on the whole island at native (~30 m) resolution needs many float64
    temporaries and does not fit in a few GB of RAM; every map only ever needs a crop.
    """
    row0, row1, col0, col1 = crop_indices(meta, bbox, margin_px)
    rows, cols = max(1, row1 - row0), max(1, col1 - col0)
    factor = 1
    while (rows / factor) * (cols / factor) > max_pixels:
        factor += 1
    sub = np.array(dem[row0:row1:factor, col0:col1:factor], dtype=np.float32)
    sub_meta = {
        "lon_min": meta["lon_min"] + col0 * meta["pixel_deg"],
        "lat_max": meta["lat_max"] - row0 * meta["pixel_deg"],
        "pixel_deg": meta["pixel_deg"] * factor,
        "height": sub.shape[0], "width": sub.shape[1],
    }
    return sub, sub_meta


def build_relief_rgba(elev: np.ndarray, meta: dict) -> np.ndarray:
    """Hillshade (matplotlib LightSource) blended with a hypsometric tint, for one crop."""
    land_stops = np.array([0, 50, 300, 700, 1200, 1800, 2400, 3200])
    land_colors = np.array([
        [231, 223, 192], [219, 210, 160], [199, 193, 126], [163, 164, 90],
        [138, 122, 84], [141, 128, 118], [176, 166, 154], [225, 219, 210],
    ], dtype=np.float32)
    elev_c = np.clip(elev, 0, land_stops[-1])
    rgb = np.stack([np.interp(elev_c, land_stops, land_colors[:, c]) for c in range(3)], axis=-1)
    sea_base = np.array([63, 96, 110], dtype=np.float32)
    depth_norm = np.clip(-elev, 0, 3000) / 3000.0
    sea_factor = (0.78 + 0.22 * (1 - depth_norm))[..., None]
    sea_rgb = sea_base[None, None, :] * sea_factor
    is_sea = elev <= 0
    rgb = np.where(is_sea[..., None], sea_rgb, rgb) / 255.0

    lat_c = np.radians((meta["lat_max"] + (meta["lat_max"] - meta["height"] * meta["pixel_deg"])) / 2)
    dx_m = meta["pixel_deg"] * 111320.0 * np.cos(lat_c)
    dy_m = meta["pixel_deg"] * 110540.0
    ls = LightSource(azdeg=315, altdeg=45)
    shaded = ls.shade_rgb(rgb, elev, blend_mode="soft", vert_exag=2.0, dx=dx_m, dy=dy_m)
    rgba = np.concatenate([np.clip(shaded, 0, 1), np.ones(shaded.shape[:2] + (1,), dtype=np.float32)], axis=-1)
    return (rgba * 255).astype(np.uint8)


def sample_basemap(basemap: np.ndarray, meta: dict, bbox, out_w: int, out_h: int):
    lon0, lat0, lon1, lat1 = bbox
    xs = np.linspace(lon0, lon1, out_w)
    ys = np.linspace(lat1, lat0, out_h)  # top row = north
    lon_grid, lat_grid = np.meshgrid(xs, ys)
    col = (lon_grid - meta["lon_min"]) / meta["pixel_deg"]
    row = (meta["lat_max"] - lat_grid) / meta["pixel_deg"]
    col = np.clip(col, 0, meta["width"] - 1)
    row = np.clip(row, 0, meta["height"] - 1)
    chans = []
    for c in range(4):
        chans.append(map_coordinates(basemap[:, :, c], [row, col], order=1, mode="nearest"))
    img = np.stack(chans, axis=-1).astype(np.uint8)
    return img


# ---------------------------------------------------------------------------
# Overture vector caches (lon/lat, prefiltered to the island + a buffer).

def load_overture_vectors(overture_dir: Path, cache_dir: Path, bbox):
    cache_p = cache_dir / "overture_vectors.pkl"
    if cache_p.exists():
        with open(cache_p, "rb") as f:
            return pickle.load(f)
    lon0, lat0, lon1, lat1 = bbox
    log.info("streaming Overture extract (roads/land/water) once...")
    coastline_rings = []
    lp = overture_dir / "land.geojsonl"
    if lp.exists():
        with open(lp) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("properties", {}).get("subtype") != "land":
                    continue
                geom = d.get("geometry") or {}
                if geom.get("type") not in ("Polygon", "MultiPolygon"):
                    continue
                polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
                for poly in polys:
                    for ring in poly:
                        if not ring or len(ring) < 2:
                            continue
                        arr = np.asarray(ring, dtype=float)
                        if arr.ndim != 2 or arr.shape[1] != 2:
                            continue
                        bx0, by0, bx1, by1 = bbox_of(arr)
                        if bx1 < lon0 or bx0 > lon1 or by1 < lat0 or by0 > lat1:
                            continue
                        for piece in split_on_jumps(arr):
                            pbx0, pby0, pbx1, pby1 = bbox_of(piece)
                            coastline_rings.append((pbx0, pby0, pbx1, pby1, piece))
    else:
        log.warning("no land.geojsonl found under %s", overture_dir)

    lakes = []
    wp = overture_dir / "water.geojsonl"
    if wp.exists():
        with open(wp) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("properties", {}).get("subtype") not in ("lake", "reservoir", "pond"):
                    continue
                geom = d.get("geometry") or {}
                if geom.get("type") not in ("Polygon", "MultiPolygon"):
                    continue
                polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
                for poly in polys:
                    if not poly or not poly[0] or len(poly[0]) < 2:
                        continue
                    ring = np.asarray(poly[0], dtype=float)
                    if ring.ndim != 2 or ring.shape[1] != 2:
                        continue
                    bx0, by0, bx1, by1 = bbox_of(ring)
                    if bx1 < lon0 or bx0 > lon1 or by1 < lat0 or by0 > lat1:
                        continue
                    if len(split_on_jumps(ring)) > 1:
                        continue  # seam artifact; not a well-formed polygon to fill
                    lakes.append((bx0, by0, bx1, by1, ring))
    else:
        log.warning("no water.geojsonl found under %s", overture_dir)

    roads = {cls: [] for cls in ROAD_STYLE}
    sp = overture_dir / "segment.geojsonl"
    if sp.exists():
        with open(sp) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cls = d.get("properties", {}).get("class")
                if cls not in ROAD_STYLE:
                    continue
                geom = d.get("geometry") or {}
                coords = geom.get("coordinates")
                if geom.get("type") != "LineString" or not coords or len(coords) < 2:
                    continue
                arr = np.asarray(coords, dtype=float)
                if arr.ndim != 2 or arr.shape[1] != 2:
                    continue
                bx0, by0, bx1, by1 = bbox_of(arr)
                if bx1 < lon0 or bx0 > lon1 or by1 < lat0 or by0 > lat1:
                    continue
                for piece in split_on_jumps(arr):
                    pbx0, pby0, pbx1, pby1 = bbox_of(piece)
                    roads[cls].append((pbx0, pby0, pbx1, pby1, piece))
    else:
        log.warning("no segment.geojsonl found under %s", overture_dir)

    data = {"coastline": coastline_rings, "lakes": lakes, "roads": roads}
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(cache_p, "wb") as f:
        pickle.dump(data, f)
    log.info("cached %d coastline rings, %d lakes, %d road classes",
              len(coastline_rings), len(lakes), len(roads))
    return data


def select_in_bbox(items, bbox):
    lon0, lat0, lon1, lat1 = bbox
    out = []
    for bx0, by0, bx1, by1, arr in items:
        if bx1 < lon0 or bx0 > lon1 or by1 < lat0 or by0 > lat1:
            continue
        out.append(arr)
    return out


# ---------------------------------------------------------------------------
# Race data.

def load_race_data(data_dir: Path):
    nodes = json.loads((data_dir / "nodes.geojson").read_text())
    pois = json.loads((data_dir / "pois.geojson").read_text())
    segs = json.loads((data_dir / "segments.geojson").read_text())
    sections = json.loads((data_dir / "sections.json").read_text())
    routes = json.loads((data_dir / "routes.json").read_text())

    node_coord = {}
    node_props = {}
    for f in nodes["features"]:
        p = f["properties"]
        node_coord[p["id"]] = tuple(f["geometry"]["coordinates"])
        node_props[p["id"]] = p

    poi_list = []
    for f in pois["features"]:
        p = f["properties"]
        poi_list.append({**p, "coord": tuple(f["geometry"]["coordinates"])})

    seg_geom = {}
    for f in segs["features"]:
        seg_geom[f["properties"]["id"]] = [tuple(c) for c in f["geometry"]["coordinates"]]

    routes_by_id = {r["id"]: r for r in routes}
    return {
        "node_coord": node_coord, "node_props": node_props, "pois": poi_list,
        "seg_geom": seg_geom, "sections": sections, "routes": routes_by_id,
    }


def chain_segments(seg_ids, seg_geom):
    """Generic chain: orient each segment to continue from the previous end point."""
    coords = []
    prev_end = None
    for sid in seg_ids:
        line = seg_geom.get(sid)
        if line is None:
            log.warning("missing segment %s, skipping", sid)
            continue
        if prev_end is not None:
            if dist2(line[-1], prev_end) < dist2(line[0], prev_end):
                line = list(reversed(line))
            if coords and dist2(coords[-1], line[0]) < 1e-10:
                line = line[1:]
        coords.extend(line)
        if coords:
            prev_end = coords[-1]
    return coords


def build_master_chain(anchor_ids, seg_ids, seg_geom, node_coord):
    """Chain the main route in anchor order; return coords, cumulative km, and per-anchor index."""
    coords = []
    boundary_idx = {anchor_ids[0]: 0}
    for i, sid in enumerate(seg_ids):
        a_to = anchor_ids[i + 1]
        line = seg_geom.get(sid)
        if line is None:
            log.warning("missing main-route segment %s, skipping", sid)
            continue
        target = node_coord.get(a_to)
        if target is not None and dist2(line[-1], target) > dist2(line[0], target):
            line = list(reversed(line))
        if coords and dist2(coords[-1], line[0]) < 1e-10:
            line = line[1:]
        coords.extend(line)
        boundary_idx[a_to] = len(coords) - 1
    cum = geod_cum_km(coords)
    return coords, cum, boundary_idx


# ---------------------------------------------------------------------------
# Drawing helpers.

_RELIEF_CACHE: dict = {}


def relief_for_bbox(dem, dem_meta, bbox, margin_px=60):
    """Build (or reuse) a relief RGBA crop for this bbox; cheap enough to call per map."""
    key = tuple(round(v, 4) for v in bbox)
    cached = _RELIEF_CACHE.get(key)
    if cached is not None:
        return cached
    elev, crop_meta = crop_elev_auto(dem, dem_meta, bbox, margin_px=margin_px)
    rgba = build_relief_rgba(elev, crop_meta)
    _RELIEF_CACHE.clear()  # only ever need the most recent crop at a time
    _RELIEF_CACHE[key] = (rgba, crop_meta)
    return rgba, crop_meta


def draw_basemap(ax, dem, dem_meta, bbox, out_w, out_h):
    rgba, crop_meta = relief_for_bbox(dem, dem_meta, bbox)
    img = sample_basemap(rgba, crop_meta, bbox, out_w, out_h)
    mx0, my0, mx1, my1 = merc_bbox(bbox)
    ax.imshow(img, extent=(mx0, mx1, my0, my1), origin="upper", interpolation="bilinear", zorder=0)


def draw_coastline(ax, coastline_rings, bbox):
    rings = select_in_bbox(coastline_rings, pad_bbox(bbox, 0.02))
    segs = [to_merc(r) for r in rings]
    if segs:
        ax.add_collection(LineCollection(segs, colors="#2b2b28", linewidths=0.7, zorder=3))


def draw_lakes(ax, lakes, bbox):
    rings = select_in_bbox(lakes, pad_bbox(bbox, 0.02))
    for r in rings:
        m = to_merc(r)
        ax.add_patch(MplPolygon(m, closed=True, facecolor="#5b8fa8", edgecolor="#2b6a86",
                                 linewidth=0.4, zorder=2))


def draw_roads(ax, roads, bbox, classes):
    for cls in classes:
        color, lw, dash = ROAD_STYLE[cls]
        lines = select_in_bbox(roads.get(cls, []), pad_bbox(bbox, 0.02))
        if not lines:
            continue
        segs = [to_merc(l) for l in lines]
        lc = LineCollection(segs, colors=color, linewidths=lw, zorder=2.5)
        if dash:
            lc.set_linestyle((0, dash))
        ax.add_collection(lc)


def draw_route(ax, coords, color, lw=2.6, dashed=False, halo=True, zorder=5, alpha=1.0):
    if len(coords) < 2:
        return
    m = to_merc(coords)
    effects = [withStroke(linewidth=lw + 1.8, foreground="white")] if halo else None
    kwargs = dict(color=color, linewidth=lw, zorder=zorder, alpha=alpha,
                  solid_capstyle="round", dash_capstyle="round", path_effects=effects)
    if dashed:
        kwargs["dashes"] = (4, 2.5)
    ax.plot(m[:, 0], m[:, 1], **kwargs)


def label_text(ax, x, y, text, size=8, color="#1a1a1a", weight="normal", ha="center", va="center",
               zorder=10, dy=0, dx=0):
    ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points", fontsize=size,
                color=color, weight=weight, ha=ha, va=va, zorder=zorder,
                path_effects=[withStroke(linewidth=2.6, foreground="white")])


class LabelPlacer:
    """Greedy, approximate collision avoidance for point labels (pixel-space heuristic)."""

    def __init__(self, ax, fig):
        self.ax = ax
        self.fig = fig
        self.placed = []  # list of (x0,y0,x1,y1) in display px

    def _bbox_px(self, x, y, text, size, dx, dy):
        # approx char width ~ 0.55*size px, height ~1.15*size px; text is ha=va='center'
        w = max(1, len(text)) * size * 0.55
        h = size * 1.15
        px, py = self.ax.transData.transform((x, y))
        px += dx
        py += dy
        return (px - w / 2 - 2, py - h / 2 - 2, px + w / 2 + 2, py + h / 2 + 2)

    def _overlap_area(self, box):
        total = 0.0
        for o in self.placed:
            ox = max(0, min(box[2], o[2]) - max(box[0], o[0]))
            oy = max(0, min(box[3], o[3]) - max(box[1], o[1]))
            total += ox * oy
        return total

    def _overlaps(self, box):
        return self._overlap_area(box) > 0

    def place(self, x, y, text, size=8, color="#1a1a1a", weight="normal", dy=9, force=False):
        w = max(1, len(text)) * size * 0.55
        far = w * 0.75 + 30
        candidates = [(0, dy), (0, dy + 11), (0, dy - 11), (0, -dy),
                      (far, dy), (-far, dy), (far, -dy), (-far, -dy),
                      (far * 1.6, 0), (-far * 1.6, 0), (0, dy + 22), (0, -dy - 22)]
        best_box, best_dx, best_dy, best_area = None, 0, dy, None
        for cand_dx, cand_dy in candidates:
            box = self._bbox_px(x, y, text, size, cand_dx, cand_dy)
            area = self._overlap_area(box)
            if area == 0:
                self.placed.append(box)
                label_text(self.ax, x, y, text, size=size, color=color, weight=weight,
                           dx=cand_dx, dy=cand_dy)
                return True
            if best_area is None or area < best_area:
                best_area, best_box, best_dx, best_dy = area, box, cand_dx, cand_dy
        if force:
            self.placed.append(best_box)
            label_text(self.ax, x, y, text, size=size, color=color, weight=weight,
                       dx=best_dx, dy=best_dy)
            return True
        return False

    def block(self, x, y, radius_px):
        """Reserve a circular area (e.g. a badge) so later labels are nudged around it."""
        px, py = self.ax.transData.transform((x, y))
        self.placed.append((px - radius_px, py - radius_px, px + radius_px, py + radius_px))


def draw_scale_bar(ax, bbox, mbbox, km=50):
    lon0, lat0, lon1, lat1 = bbox
    mx0, my0, mx1, my1 = mbbox
    lat_c = (lat0 + lat1) / 2
    bar_m = km * 1000.0 / np.cos(np.radians(lat_c))
    x0 = mx0 + (mx1 - mx0) * 0.04
    y0 = my0 + (my1 - my0) * 0.05
    ax.plot([x0, x0 + bar_m], [y0, y0], color="black", linewidth=2.5, zorder=20,
            solid_capstyle="butt")
    for xe in (x0, x0 + bar_m):
        ax.plot([xe, xe], [y0 - (my1 - my0) * 0.006, y0 + (my1 - my0) * 0.006], color="black",
                linewidth=1.4, zorder=20)
    label_text(ax, x0 + bar_m / 2, y0, f"{km} km", size=8, weight="bold", dy=10)


def draw_north_arrow(ax, bbox, mbbox):
    mx0, my0, mx1, my1 = mbbox
    x = mx1 - (mx1 - mx0) * 0.045
    y0 = my1 - (my1 - my0) * 0.13
    y1 = my1 - (my1 - my0) * 0.05
    ax.annotate("", xy=(x, y1), xytext=(x, y0),
                arrowprops=dict(arrowstyle="-|>", color="#1a1a1a", linewidth=1.6), zorder=20)
    label_text(ax, x, y1, "N", size=10, weight="bold", dy=10)


def draw_attribution(ax, mbbox, text="Terrain: SRTM (USGS) · roads and coastline: "
                                     "© OpenStreetMap contributors via Overture Maps"):
    mx0, my0, mx1, my1 = mbbox
    ax.annotate(text, xy=(0.5, 0.012), xycoords="axes fraction", fontsize=6.5, color="#444",
                ha="center", va="bottom", zorder=20)


def new_figure(out_w, out_h, mbbox):
    dpi = 200
    fig = plt.figure(figsize=(out_w / dpi, out_h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(mbbox[0], mbbox[2])
    ax.set_ylim(mbbox[1], mbbox[3])
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def save_fig(fig, out_path, out_w, out_h):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    log.info("wrote %s (%dx%d)", out_path, out_w, out_h)


def point_at_km(coords, cum, target):
    if target <= cum[0]:
        return coords[0], 0
    if target >= cum[-1]:
        return coords[-1], max(0, len(coords) - 2)
    idx = int(np.searchsorted(cum, target)) - 1
    idx = max(0, min(idx, len(coords) - 2))
    span = cum[idx + 1] - cum[idx]
    t = (target - cum[idx]) / span if span > 1e-9 else 0.0
    lon = coords[idx][0] + t * (coords[idx + 1][0] - coords[idx][0])
    lat = coords[idx][1] + t * (coords[idx + 1][1] - coords[idx][1])
    return (lon, lat), idx


def draw_km_ticks(ax, coords, cum, step, mbbox, size_frac=0.012, placer=None):
    tick_len = (mbbox[2] - mbbox[0]) * size_frac
    start = int(np.ceil(cum[0] / step)) * step
    for target in np.arange(start, cum[-1] - 1e-6, step):
        (lon, lat), idx = point_at_km(coords, cum, float(target))
        x, y = TO_MERC.transform(lon, lat)
        x0, y0 = TO_MERC.transform(*coords[idx])
        x1, y1 = TO_MERC.transform(*coords[idx + 1])
        dxs, dys = x1 - x0, y1 - y0
        norm = np.hypot(dxs, dys) or 1.0
        pxn, pyn = -dys / norm, dxs / norm
        ax.plot([x - pxn * tick_len / 2, x + pxn * tick_len / 2],
                 [y - pyn * tick_len / 2, y + pyn * tick_len / 2],
                 color="#2a2a2a", linewidth=1.0, zorder=9)
        tx, ty = x + pxn * tick_len * 1.6, y + pyn * tick_len * 1.6
        text = f"{int(round(target))}"
        if placer is not None:
            placer.place(tx, ty, text, size=6, dy=0, force=True)
        else:
            label_text(ax, tx, ty, text, size=6, dy=0)


def nice_scale_km(bbox):
    lon0, lat0, lon1, lat1 = bbox
    width_km = (lon1 - lon0) * 111.32 * np.cos(np.radians((lat0 + lat1) / 2))
    target = width_km * 0.18
    for candidate in (1, 2, 5, 10, 20, 25, 50, 100, 200):
        if candidate >= target:
            return candidate
    return 200


def draw_pois(ax, placer, pois, bbox, relevances=("anchor", "highlight", "hazard")):
    lon0, lat0, lon1, lat1 = bbox
    items = [p for p in pois if p.get("race_relevance") in relevances
             and lon0 <= p["coord"][0] <= lon1 and lat0 <= p["coord"][1] <= lat1]
    priority = {"anchor": 0, "hazard": 1, "highlight": 2}
    items.sort(key=lambda p: priority.get(p.get("race_relevance"), 3))
    for p in items:
        x, y = TO_MERC.transform(*p["coord"])
        color = POI_CATEGORY_COLOR.get(p.get("category"), "#666666")
        if p.get("race_relevance") == "hazard":
            marker, msize = "^", 7
        elif p.get("race_relevance") == "anchor":
            marker, msize = "D", 6
        else:
            marker, msize = "o", 5.5
        ax.plot(x, y, marker=marker, markersize=msize, color=color, markeredgecolor="white",
                markeredgewidth=0.6, zorder=8)
        placer.place(x, y, p["name"], size=7)


def draw_anchor_nodes(ax, placer, node_coord, node_props, bbox, label_ids=None, radius_frac=0.0035,
                       mbbox=None, always_label=False):
    lon0, lat0, lon1, lat1 = bbox
    r = (mbbox[2] - mbbox[0]) * radius_frac
    for nid, coord in node_coord.items():
        if not (lon0 <= coord[0] <= lon1 and lat0 <= coord[1] <= lat1):
            continue
        x, y = TO_MERC.transform(*coord)
        ax.add_patch(Circle((x, y), radius=r, facecolor="white", edgecolor="#333333",
                             linewidth=0.7, zorder=7))
        if always_label or (label_ids is not None and nid in label_ids):
            weight = "bold" if (label_ids and nid in label_ids) else "normal"
            placer.place(x, y, node_props[nid]["name"], size=8, weight=weight, force=always_label)


def draw_legend(ax, config, option_color):
    handles = [plt.Line2D([0], [0], color=MAIN_COLOR, lw=3, label="Main route")]
    for opt in config["options"]:
        handles.append(plt.Line2D([0], [0], color=option_color[opt["id"]], lw=2, linestyle="--",
                                   label=opt["name"]))
    handles.append(plt.Line2D([0], [0], marker="^", color="none", markerfacecolor="#a3341f",
                               markeredgecolor="#a3341f", markersize=8, label="Volcano"))
    handles.append(plt.Line2D([0], [0], marker="o", color="none", markerfacecolor="white",
                               markeredgecolor="#333333", markersize=7, label="Anchor / town"))
    ax.legend(handles=handles, loc="upper left", fontsize=6.5, framealpha=0.92, borderpad=0.8,
              labelspacing=0.5, handlelength=1.8)


# ---------------------------------------------------------------------------
# Map builders.

def draw_common_layers(ax, ctx, bbox, out_w, out_h, road_classes):
    draw_basemap(ax, ctx["dem"], ctx["dem_meta"], bbox, out_w, out_h)
    draw_roads(ax, ctx["vectors"]["roads"], bbox, road_classes)
    draw_lakes(ax, ctx["vectors"]["lakes"], bbox)
    draw_coastline(ax, ctx["vectors"]["coastline"], bbox)


def render_overview(ctx, master, out_dir, clean=False):
    bbox = ISLAND_BBOX
    out_w = 3600
    mbbox = merc_bbox(bbox)
    out_h = int(round(out_w / ((mbbox[2] - mbbox[0]) / (mbbox[3] - mbbox[1]))))
    fig, ax = new_figure(out_w, out_h, mbbox)
    draw_common_layers(ax, ctx, bbox, out_w, out_h, ["trunk", "primary"])

    coords, cum, boundary_idx = master
    draw_route(ax, coords, MAIN_COLOR, lw=3.2, zorder=6)

    if not clean:
        for opt in ctx["config"]["options"]:
            color = ctx["option_color"][opt["id"]]
            oc = chain_segments(opt["segments"], ctx["seg_geom"])
            draw_route(ax, oc, color, lw=1.7, dashed=True, halo=False, zorder=5.5)

    placer = LabelPlacer(ax, ax.figure)
    if not clean:
        # Reserve the legend's corner (drawn last) so no label is placed underneath it.
        lx0, ly0 = ax.transAxes.transform((0.0, 0.76))
        lx1, ly1 = ax.transAxes.transform((0.24, 1.0))
        placer.placed.append((min(lx0, lx1), min(ly0, ly1), max(lx0, lx1), max(ly0, ly1)))

    # Fixed landmarks first (section badges, volcano triangles): reserve their pixel-space so
    # the more numerous anchor/town labels placed afterwards get nudged around them.
    if not clean:
        for section in ctx["sections"]:
            i0 = boundary_idx.get(section["from_node"])
            i1 = boundary_idx.get(section["to_node"])
            if i0 is None or i1 is None:
                continue
            mid_km = (cum[i0] + cum[i1]) / 2
            (lon, lat), _ = point_at_km(coords, cum, mid_km)
            x, y = TO_MERC.transform(lon, lat)
            r = (mbbox[2] - mbbox[0]) * 0.0075
            ax.add_patch(Circle((x, y), radius=r, facecolor="white", edgecolor=MAIN_COLOR,
                                 linewidth=1.3, zorder=11))
            ax.annotate(f"{section['order']:02d}", (x, y), ha="center", va="center", fontsize=7,
                        weight="bold", color=MAIN_COLOR, zorder=12)
            px0, py0 = ax.transData.transform((x, y))
            px1, _ = ax.transData.transform((x + r, y))
            placer.block(x, y, abs(px1 - px0) * 2.2)

    for name in VOLCANO_LABELS:
        match = next((p for p in ctx["pois"] if name.lower() in p["name"].lower()
                      and p.get("category") in ("volcano", "crater-lake")), None)
        if match is None:
            log.warning("volcano label %r not matched to a POI", name)
            continue
        x, y = TO_MERC.transform(*match["coord"])
        ax.plot(x, y, marker="^", markersize=8, color="#a3341f", markeredgecolor="white",
                markeredgewidth=0.7, zorder=8)
        placer.place(x, y, name, size=8, weight="bold", color="#7a2415", force=True)

    draw_km_ticks(ax, coords, cum, 100, mbbox, size_frac=0.006, placer=placer)

    label_ids = {s["from_node"] for s in ctx["sections"]} | {s["to_node"] for s in ctx["sections"]}
    for p in ctx["node_props"].values():
        if p["name"] in NAMED_TOWNS:
            label_ids.add(p["id"])
    draw_anchor_nodes(ax, placer, ctx["node_coord"], ctx["node_props"], pad_bbox(bbox, 0.0),
                       label_ids=label_ids, radius_frac=0.0022, mbbox=mbbox)

    draw_scale_bar(ax, bbox, mbbox, km=50)
    draw_north_arrow(ax, bbox, mbbox)
    draw_attribution(ax, mbbox)
    if not clean:
        draw_legend(ax, ctx["config"], ctx["option_color"])

    name = "overview-clean.png" if clean else "overview.png"
    save_fig(ax.figure, out_dir / name, out_w, out_h)


def render_section(ctx, section, master, out_dir):
    order = section["order"]
    from_node, to_node = section["from_node"], section["to_node"]
    coords_full, cum_full, boundary_idx = master
    if from_node not in boundary_idx or to_node not in boundary_idx:
        log.warning("section %s: boundary anchors not on main chain, skipping", section["id"])
        return
    i0, i1 = boundary_idx[from_node], boundary_idx[to_node]
    chain = coords_full[i0:i1 + 1]
    cum = cum_full[i0:i1 + 1]
    out_w, out_h = 2400, 1800
    bbox = pad_bbox(bbox_of(chain), 0.12, min_width_km=25)
    bbox, mbbox = fit_aspect(bbox, (out_w, out_h))

    fig, ax = new_figure(out_w, out_h, mbbox)
    draw_common_layers(ax, ctx, bbox, out_w, out_h,
                        ["trunk", "primary", "secondary", "tertiary", "unclassified", "track", "path"])
    draw_route(ax, chain, MAIN_COLOR, lw=3.4, zorder=6)

    for opt in ctx["config"]["options"]:
        if order not in opt.get("sections", []):
            continue
        color = ctx["option_color"][opt["id"]]
        oc = chain_segments(opt["segments"], ctx["seg_geom"])
        draw_route(ax, oc, color, lw=2.2, dashed=True, halo=False, zorder=5.5)
        if len(oc) >= 2:
            mx, my = TO_MERC.transform(*oc[len(oc) // 2])
            label_text(ax, mx, my, opt["name"], size=7, color=color, weight="bold", dy=9)

    placer = LabelPlacer(ax, fig)
    draw_anchor_nodes(ax, placer, ctx["node_coord"], ctx["node_props"], bbox,
                       label_ids={from_node, to_node}, mbbox=mbbox, always_label=True)
    draw_km_ticks(ax, chain, cum, 10, mbbox, placer=placer)
    draw_pois(ax, placer, ctx["pois"], bbox)

    for nid in (from_node, to_node):
        x, y = TO_MERC.transform(*ctx["node_coord"][nid])
        kmval = cum[0] if nid == from_node else cum[-1]
        label_text(ax, x, y, f"{kmval:.0f} km", size=7.5, color="#7a1020", weight="bold", dy=-18)

    draw_scale_bar(ax, bbox, mbbox, km=nice_scale_km(bbox))
    draw_north_arrow(ax, bbox, mbbox)
    draw_attribution(ax, mbbox)
    save_fig(fig, out_dir / f"sec-{order:02d}.png", out_w, out_h)


def render_option(ctx, opt, out_dir):
    color = ctx["option_color"][opt["id"]]
    oc = chain_segments(opt["segments"], ctx["seg_geom"])
    rc = chain_segments(opt.get("replaces", []), ctx["seg_geom"])
    all_coords = (oc or []) + (rc or [])
    if not all_coords:
        log.warning("option %s: no geometry resolved, skipping", opt["id"])
        return
    out_w, out_h = 2400, 1800
    bbox = pad_bbox(bbox_of(all_coords), 0.18, min_width_km=15)
    bbox, mbbox = fit_aspect(bbox, (out_w, out_h))

    fig, ax = new_figure(out_w, out_h, mbbox)
    draw_common_layers(ax, ctx, bbox, out_w, out_h,
                        ["trunk", "primary", "secondary", "tertiary", "unclassified", "track", "path"])
    draw_route(ax, rc, MAIN_COLOR, lw=2.8, dashed=True, zorder=5)
    draw_route(ax, oc, color, lw=3.2, dashed=False, zorder=6)

    if len(oc) >= 2:
        mx, my = TO_MERC.transform(*oc[len(oc) // 2])
        label_text(ax, mx, my, "option", size=9, color=color, weight="bold", dy=12)
    if len(rc) >= 2:
        mx, my = TO_MERC.transform(*rc[len(rc) // 2])
        label_text(ax, mx, my, "main course", size=9, color=MAIN_COLOR, weight="bold", dy=-14)

    placer = LabelPlacer(ax, fig)
    draw_anchor_nodes(ax, placer, ctx["node_coord"], ctx["node_props"], bbox, mbbox=mbbox,
                       always_label=True)
    draw_pois(ax, placer, ctx["pois"], bbox)

    draw_scale_bar(ax, bbox, mbbox, km=nice_scale_km(bbox))
    draw_north_arrow(ax, bbox, mbbox)
    draw_attribution(ax, mbbox)
    save_fig(fig, out_dir / f"{opt['id']}.png", out_w, out_h)


def render_profile(path: Path, out_dir: Path):
    d = json.loads(path.read_text())
    pts = np.asarray(d["points"], dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    out_w, out_h, dpi = 2400, 700, 200
    fig = plt.figure(figsize=(out_w / dpi, out_h / dpi), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.055, 0.16, 0.925, 0.72])
    ax.set_facecolor("white")

    ymax = max(float(y.max()), 1.0)
    n = 256
    grad = np.linspace(0, 1, n).reshape(n, 1)
    warm = np.array([[0.94, 0.90, 0.78], [0.55, 0.36, 0.20]])
    cmap_img = warm[0] * (1 - grad) + warm[1] * grad
    ax.imshow(cmap_img.reshape(n, 1, 3), extent=(x.min(), x.max(), 0, ymax), origin="lower",
              aspect="auto", zorder=0)
    ax.fill_between(x, y, ymax * 1.05, color="white", zorder=1)
    ax.plot(x, y, color="#4a2f1a", linewidth=1.5, zorder=2)

    for a in d.get("anchors", []):
        ax.axvline(a["km"], color="#999999", linewidth=0.6, linestyle="--", zorder=3)
        ax.annotate(a["name"], (a["km"], ymax * 1.02), rotation=55, fontsize=7, ha="left",
                    va="bottom", zorder=4)

    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(0, ymax * 1.35)
    ax.set_xlabel("km", fontsize=8)
    ax.set_ylabel("m", fontsize=8)
    ax.tick_params(labelsize=7)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    length_km = d.get("length_km", float(x.max() - x.min()))
    ascent = d.get("ascent_m", 0)
    descent = d.get("descent_m", 0)
    ax.annotate(f"{length_km:.0f} km · +{ascent:.0f} m · −{descent:.0f} m",
                xy=(0.995, 0.94), xycoords="axes fraction", ha="right", fontsize=9.5, weight="bold")

    out_path = out_dir / f"{d['id']}.png"
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    log.info("wrote %s (%dx%d)", out_path, out_w, out_h)


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="path to data/ (nodes/pois/segments/sections)")
    ap.add_argument("--config", required=True, help="path to exports/brochure_config.json")
    ap.add_argument("--dem-dir", required=True, help="path to .cache/dem (SRTM .hgt tiles)")
    ap.add_argument("--overture-dir", required=True, help="path to .cache/overture (.geojsonl)")
    ap.add_argument("--out", required=True, help="output root; writes <out>/maps and <out>/profiles")
    ap.add_argument("--profiles-dir", default=None, help="dir of elevation-profile JSON inputs")
    ap.add_argument("--cache-dir", default=None,
                    help="scratch cache for the DEM mosaic/relief/vector extracts "
                         "(default: <dem-dir>/../brochure_render)")
    ap.add_argument("--only", choices=["overview", "sections", "options", "profiles"], default=None)
    args = ap.parse_args()

    t0 = time.time()
    data_dir = Path(args.data)
    out_dir = Path(args.out)
    dem_dir = Path(args.dem_dir)
    overture_dir = Path(args.overture_dir)
    cache_dir = Path(args.cache_dir) if args.cache_dir else dem_dir.parent / "brochure_render"
    cache_dir.mkdir(parents=True, exist_ok=True)

    config = json.loads(Path(args.config).read_text())
    data = load_race_data(data_dir)
    dem, dem_meta = load_dem_mosaic(dem_dir, cache_dir)
    vectors = load_overture_vectors(overture_dir, cache_dir, pad_bbox(ISLAND_BBOX, 0.05))

    option_color = {opt["id"]: OPTION_PALETTE[i % len(OPTION_PALETTE)]
                    for i, opt in enumerate(config["options"])}

    ctx = {**data, "dem": dem, "dem_meta": dem_meta, "vectors": vectors,
           "config": config, "option_color": option_color}

    if config["main_route"] not in data["routes"]:
        log.error("main_route %s not found in routes.json", config["main_route"])
        return 0
    main_route = data["routes"][config["main_route"]]
    master = build_master_chain(main_route["anchors"], main_route["segments"],
                                 data["seg_geom"], data["node_coord"])

    out_maps = out_dir / "maps"
    only = args.only

    if only in (None, "overview"):
        render_overview(ctx, master, out_maps, clean=False)
        render_overview(ctx, master, out_maps, clean=True)

    if only in (None, "sections"):
        for section in data["sections"]:
            try:
                render_section(ctx, section, master, out_maps)
            except Exception:
                log.exception("failed to render section %s", section.get("id"))

    if only in (None, "options"):
        for opt in config["options"]:
            try:
                render_option(ctx, opt, out_maps)
            except Exception:
                log.exception("failed to render option %s", opt.get("id"))

    if only in (None, "profiles"):
        pd = Path(args.profiles_dir) if args.profiles_dir else None
        if pd is None or not pd.exists() or not any(pd.glob("*.json")):
            log.warning("profiles dir %s missing or empty, skipping elevation profiles", pd)
        else:
            out_profiles = out_dir / "profiles"
            out_profiles.mkdir(parents=True, exist_ok=True)
            for jp in sorted(pd.glob("*.json")):
                try:
                    render_profile(jp, out_profiles)
                except Exception:
                    log.exception("failed to render profile %s", jp)

    log.info("done in %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
