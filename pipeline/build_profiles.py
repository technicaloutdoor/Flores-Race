#!/usr/bin/env python3
"""build_profiles.py

For every segment: sample the DEM along its geometry every 50 m
(``dem.DEM.sample_line``), clamp bathymetry/voids to 0, smooth, and compute
the derived ``Stats`` block (length, ascent, descent, min/max elevation,
% unpaved) plus a decimated elevation profile. Then roll the per-segment
stats up into each route that references them.

Why smooth before computing ascent/descent
--------------------------------------------
SRTM 1-arc-second data (~30 m posts) has several metres of vertical noise.
Summed naively over thousands of samples, that noise turns into many
hundreds of metres of *phantom* climbing on a long segment -- every noisy
up-tick counts as "ascent" even though the ground is basically flat. A
5-sample moving median first kills isolated spikes (a median is robust to
outliers in a way a mean is not), then a 5-sample moving average smooths the
remainder, before ascent/descent are summed from consecutive differences.
This trades a little bit of true small-scale relief for numbers a rider can
trust; ``min_elev_m``/``max_elev_m`` are taken from the raw (clamped, not
smoothed) samples so real peaks and valleys are not flattened away.

Never rewrites ``data/`` in place unless ``--in-place`` is passed -- see
ARCHITECTURE.md #6 ("reproducible derivations... nobody hand-edits generated
files"): the *canonical* segments.geojson/routes.json only change when a
human (or ``apply_patch.py`` on their behalf) says so; this script's job is
to produce an output copy with the derived fields filled in.
"""
from __future__ import annotations

import argparse
import copy
import statistics
import sys
from pathlib import Path
from typing import Optional, Sequence

import common

DEFAULT_STEP_M = 50.0
DEFAULT_MAX_PROFILE_POINTS = 400
SMOOTH_MEDIAN_WINDOW = 5
SMOOTH_MEAN_WINDOW = 5


# ---------------------------------------------------------------------------
# Smoothing and ascent/descent
# ---------------------------------------------------------------------------


def _moving_window(values: Sequence[float], window: int, reducer) -> list:
    n = len(values)
    half = window // 2
    out = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out.append(reducer(values[lo:hi]))
    return out


def moving_median(values: Sequence[float], window: int = SMOOTH_MEDIAN_WINDOW) -> list:
    return _moving_window(values, window, statistics.median)


def moving_average(values: Sequence[float], window: int = SMOOTH_MEAN_WINDOW) -> list:
    return _moving_window(values, window, lambda w: sum(w) / len(w))


def smooth_elevations(
    values: Sequence[float],
    median_window: int = SMOOTH_MEDIAN_WINDOW,
    mean_window: int = SMOOTH_MEAN_WINDOW,
) -> list:
    """5-sample moving median (kills SRTM spikes) then a 5-sample moving
    average (smooths the rest). See module docstring for why."""
    if len(values) < 2:
        return list(values)
    return moving_average(moving_median(values, median_window), mean_window)


def ascent_descent(values: Sequence[float]) -> tuple:
    """Total climb and total descent (both >= 0) from consecutive
    differences of an elevation series."""
    ascent = 0.0
    descent = 0.0
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        if diff > 0:
            ascent += diff
        else:
            descent += -diff
    return ascent, descent


# ---------------------------------------------------------------------------
# Per-segment stats
# ---------------------------------------------------------------------------


def unpaved_pct_for(props: dict) -> float:
    """From surface_mix {label: km} when available (anything not literally
    labelled 'paved' counts as unpaved), else from `character`
    (paved -> 0, everything else, including 'unknown' -> 100), per
    docs/data-model.md."""
    surface_mix = props.get("surface_mix")
    if surface_mix:
        total = sum(surface_mix.values())
        if total > 0:
            unpaved = sum(km for label, km in surface_mix.items() if label != "paved")
            return round(100.0 * unpaved / total, 1)
    return 0.0 if props.get("character") == "paved" else 100.0


def compute_segment_stats(
    feature: dict,
    dem,
    step_m: float = DEFAULT_STEP_M,
    max_profile_points: int = DEFAULT_MAX_PROFILE_POINTS,
) -> tuple:
    """Compute the Stats block and decimated elevation profile for one
    segment Feature. Returns (stats_dict, profile_points) where
    profile_points is a list of [km, elevation_m] pairs, decimated with
    Douglas-Peucker to at most max_profile_points."""
    props = feature["properties"]
    coords = feature["geometry"]["coordinates"]
    length_km = common.geodesic_length_km(coords)

    samples = common.sample_line_clamped(dem, coords, step_m=step_m)
    if len(samples) < 2:
        # Degenerate (near-zero-length) geometry: fall back to flat endpoints
        # so downstream code always has something to work with.
        samples = [(0.0, 0.0), (max(length_km * 1000.0, 1.0), 0.0)]

    distances_m = [d for d, _ in samples]
    raw_elevs = [e for _, e in samples]
    smoothed = smooth_elevations(raw_elevs)
    ascent, descent = ascent_descent(smoothed)

    profile_points_m = list(zip(distances_m, [round(e, 1) for e in smoothed]))
    decimated_m = common.decimate_profile(profile_points_m, max_points=max_profile_points)
    profile_points_km = [[round(d / 1000.0, 4), e] for d, e in decimated_m]

    stats = {
        "length_km": round(length_km, 3),
        "ascent_m": round(ascent, 1),
        "descent_m": round(descent, 1),
        "min_elev_m": round(min(raw_elevs), 1),
        "max_elev_m": round(max(raw_elevs), 1),
        "unpaved_pct": unpaved_pct_for(props),
        "profile_ref": props["id"],
    }
    return stats, profile_points_km


# ---------------------------------------------------------------------------
# Route roll-up
# ---------------------------------------------------------------------------


def _rollup_route_stats(route: dict, stats_by_id: dict, profiles: dict) -> tuple:
    """Returns (stats_dict, concatenated_profile_points) for one route, or
    raises KeyError if the route references a segment with no computed
    stats (caller is expected to have validated referential integrity
    first; this is a defensive check, not the primary one)."""
    seg_ids = route.get("segments") or []
    total_length = 0.0
    total_ascent = 0.0
    total_descent = 0.0
    total_hab = 0.0
    min_elev: Optional[float] = None
    max_elev: Optional[float] = None
    unpaved_weighted = 0.0
    status_counts: dict = {}
    concatenated = []
    cumulative_km = 0.0

    for seg_id in seg_ids:
        if seg_id not in stats_by_id:
            raise KeyError(f"route {route.get('id')!r} references unknown segment {seg_id!r}")
        stats, props = stats_by_id[seg_id]
        total_length += stats["length_km"]
        total_ascent += stats["ascent_m"]
        total_descent += stats["descent_m"]
        total_hab += props.get("est_hab_km") or 0
        if min_elev is None or stats["min_elev_m"] < min_elev:
            min_elev = stats["min_elev_m"]
        if max_elev is None or stats["max_elev_m"] > max_elev:
            max_elev = stats["max_elev_m"]
        unpaved_weighted += stats["unpaved_pct"] * stats["length_km"]
        status = props.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

        for km, elev in profiles.get(seg_id, []):
            concatenated.append([round(km + cumulative_km, 4), elev])
        cumulative_km += stats["length_km"]

    unpaved_pct_route = round(unpaved_weighted / total_length, 1) if total_length > 0 else 0.0
    stats = {
        "length_km": round(total_length, 3),
        "ascent_m": round(total_ascent, 1),
        "descent_m": round(total_descent, 1),
        "min_elev_m": round(min_elev, 1) if min_elev is not None else 0.0,
        "max_elev_m": round(max_elev, 1) if max_elev is not None else 0.0,
        "unpaved_pct": unpaved_pct_route,
        "profile_ref": route.get("id"),
        "hab_km": round(total_hab, 1),
        "segments_by_status": status_counts,
    }
    return stats, concatenated


def build_profiles(
    segments_fc: dict,
    routes: list,
    dem,
    step_m: float = DEFAULT_STEP_M,
    max_profile_points: int = DEFAULT_MAX_PROFILE_POINTS,
) -> tuple:
    """Compute stats + profiles for every segment, then roll routes up.

    Returns (segments_fc_out, routes_out, profiles) where profiles is
    ``{id: [[km, m], ...]}`` for both segment ids and route ids, per
    docs/data-model.md.
    """
    profiles: dict = {}
    stats_by_id: dict = {}
    segments_out = {"type": segments_fc.get("type", "FeatureCollection"), "features": []}

    for feature in segments_fc.get("features", []):
        feat = copy.deepcopy(feature)
        stats, profile_points = compute_segment_stats(feat, dem, step_m, max_profile_points)
        feat["properties"]["stats"] = stats
        segments_out["features"].append(feat)
        seg_id = feat["properties"]["id"]
        stats_by_id[seg_id] = (stats, feat["properties"])
        profiles[seg_id] = profile_points

    routes_out = []
    for route in routes:
        route_copy = copy.deepcopy(route)
        stats, concatenated = _rollup_route_stats(route_copy, stats_by_id, profiles)
        route_copy["stats"] = stats
        routes_out.append(route_copy)
        profiles[route_copy["id"]] = concatenated

    return segments_out, routes_out, profiles


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data", help="Path to data/ (default: data)")
    parser.add_argument("--dem-dir", required=True, help="Directory of SRTM .hgt tiles")
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory for segments.geojson/routes.json/profiles.json "
        "(required unless --in-place)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Write back into --data instead of --out (never the default -- "
        "canonical data/ is not meant to be pipeline-written except this way)",
    )
    parser.add_argument("--step-m", type=float, default=DEFAULT_STEP_M)
    parser.add_argument("--max-profile-points", type=int, default=DEFAULT_MAX_PROFILE_POINTS)
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    data_dir = Path(args.data)

    if args.in_place:
        out_dir = data_dir
    else:
        if not args.out:
            print(
                "error: --out is required unless --in-place is given "
                "(data/ is never rewritten in place by default)",
                file=sys.stderr,
            )
            return 2
        out_dir = Path(args.out)

    segments_fc = common.read_geojson(data_dir / "segments.geojson")
    routes = common.read_json(data_dir / "routes.json")
    dem = common.load_dem(args.dem_dir)

    segments_out, routes_out, profiles = build_profiles(
        segments_fc, routes, dem, step_m=args.step_m, max_profile_points=args.max_profile_points
    )

    common.write_geojson(out_dir / "segments.geojson", segments_out)
    common.write_json(out_dir / "routes.json", routes_out)
    common.write_json(out_dir / "profiles.json", profiles)

    print(
        f"Wrote {len(segments_out['features'])} segment(s) with stats, "
        f"{len(routes_out)} route(s) with stats, and profiles.json to {out_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
