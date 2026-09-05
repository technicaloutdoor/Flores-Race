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
remainder, before ascent/descent are derived from the result.
This trades a little bit of true small-scale relief for numbers a rider can
trust; ``min_elev_m``/``max_elev_m`` are taken from the raw (clamped, not
smoothed) samples so real peaks and valleys are not flattened away.

Why smoothing alone is not enough -- the ascent threshold
-----------------------------------------------------------
Smoothing reduces the noise but does not remove it: even a 5-sample
median-then-mean pass leaves a residual wobble of a metre or two on ground
that is, in truth, flat. That residual is small on any *one* sample, but
``ascent_descent`` used to sum every single up-tick between consecutive
samples, and a 50 m-step DEM profile of a long course has thousands of
samples -- thousands of small wobbles add up to tens of thousands of metres
of climbing that was never actually climbed. Measured on this project's own
data (see the pipeline task's own measurement notes for the exact run): the
hand-sketched (``concept-sketch``) traverse route -- straight-ish lines
drawn over genuinely mountainous terrain, so much of its climb is real --
still summed to roughly 65-70 m of "ascent" per km with smoothing alone and
no threshold; the computed, Overture-graph candidate routes (real
roads/tracks, the case the threshold is really aimed at) summed to roughly
30-35 m/km, well above what a rider who has seen the actual roads would
expect for this terrain.

The fix is a hysteresis (threshold) accumulator, applied *after* smoothing,
in ``ascent_descent``: instead of summing every consecutive difference, it
tracks a running high (while apparently climbing) or low (while apparently
descending) since the last *confirmed* turning point, and only "confirms"
that turning point -- banking the change since the previous one into ascent
or descent -- once the profile has reversed by more than
``ascent_threshold_m`` (module default ``DEFAULT_ASCENT_THRESHOLD_M``,
overridable per run with ``--ascent-threshold-m``). A wobble that never
reverses by more than the threshold contributes nothing; a genuine climb or
descent, however long, is banked in full once a real reversal (or the end of
the profile) confirms it -- so the threshold trades away sub-threshold
texture, not real relief, the same trade the smoothing pass already makes.

Choosing the default (10 m): SRTM 1-arc-second vertical error is commonly
several metres (RMSE literature and this project's own noisy-flat-segment
tests both land in the 2-4 m range after the median/mean smoothing above),
so a threshold has to clear that noise floor by a comfortable margin or it
does nothing. ``--ascent-threshold-m 5`` was tried first and only partly
closed the gap on the computed candidate routes (~29-33 m/km depending on
which candidates are averaged) -- still occasionally over the 30 m/km top of
a plausible range for Flores' hill country; ``10`` clears it reliably
(computed candidates land at roughly 26-30 m/km) while barely moving the
hand-sketched traverse route at all (~66-67 m/km either way, confirming that
route's climb is mostly real terrain, not noise, and the threshold correctly
leaves it alone) and without visibly eating the clean synthetic ramp test's
climb. See pipeline/tests/test_build_profiles.py for the synthetic ramp
(threshold does not eat a real climb) and noisy-flat (threshold silences
residual wobble that a threshold of 0 would still sum) cases this reasoning
rests on.

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
#: Minimum confirmed elevation reversal (metres) before a climb/descent is
#: banked into ascent/descent -- see "Why smoothing alone is not enough"
#: above. Pass --ascent-threshold-m 0 to recover the old "sum every
#: consecutive difference" behaviour.
DEFAULT_ASCENT_THRESHOLD_M = 10.0


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


def _ascent_descent_naive(values: Sequence[float]) -> tuple:
    """Sum every consecutive up/down difference, with no threshold. This is
    what ``ascent_descent`` used to do unconditionally; kept as the
    ``ascent_threshold_m <= 0`` behaviour (and the "before" half of the
    threshold's own before/after measurements) -- see module docstring for
    why it overstates climbing on noisy elevation data."""
    ascent = 0.0
    descent = 0.0
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        if diff > 0:
            ascent += diff
        else:
            descent += -diff
    return ascent, descent


def ascent_descent(
    values: Sequence[float], ascent_threshold_m: float = DEFAULT_ASCENT_THRESHOLD_M
) -> tuple:
    """Total climb and total descent (both >= 0) from an elevation series,
    using a hysteresis (threshold) accumulator: a climb or descent is only
    "confirmed" -- and banked into ascent/descent -- once the running
    elevation change since the last confirmed turning point exceeds
    ``ascent_threshold_m``. See the module docstring ("Why smoothing alone
    is not enough") for the reasoning and the choice of default.

    ``ascent_threshold_m <= 0`` recovers the naive "sum every consecutive
    difference" behaviour (no threshold at all).
    """
    if ascent_threshold_m <= 0 or len(values) < 2:
        return _ascent_descent_naive(values)

    ascent = 0.0
    descent = 0.0
    base = values[0]  # elevation at the last *confirmed* turning point
    peak = values[0]  # running high (climbing) or low (descending) since base
    climbing = 0  # +1 climbing, -1 descending, 0 undecided (still at base)

    for v in values[1:]:
        if climbing >= 0 and v >= peak:
            peak = v
            climbing = 1
        elif climbing <= 0 and v <= peak:
            peak = v
            climbing = -1
        elif abs(peak - v) >= ascent_threshold_m:
            # Reversed far enough to confirm the turning point at `peak`:
            # bank the change since `base`, then start the next leg from
            # `peak` towards `v`.
            change = peak - base
            if change > 0:
                ascent += change
            elif change < 0:
                descent += -change
            base = peak
            peak = v
            climbing = 1 if v > base else (-1 if v < base else 0)
        # else: v has not reversed far enough yet -- absorbed as noise,
        # `base`/`peak`/`climbing` unchanged.

    # Close out the final, still-open leg (there is no more data left to
    # reverse it, so it is banked unconditionally).
    change = peak - base
    if change > 0:
        ascent += change
    elif change < 0:
        descent += -change
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
    ascent_threshold_m: float = DEFAULT_ASCENT_THRESHOLD_M,
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
    ascent, descent = ascent_descent(smoothed, ascent_threshold_m=ascent_threshold_m)

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
    ascent_threshold_m: float = DEFAULT_ASCENT_THRESHOLD_M,
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
        stats, profile_points = compute_segment_stats(
            feat, dem, step_m, max_profile_points, ascent_threshold_m
        )
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
    parser.add_argument(
        "--ascent-threshold-m",
        type=float,
        default=DEFAULT_ASCENT_THRESHOLD_M,
        help="Minimum confirmed elevation reversal (metres) before a climb/descent is "
        "banked into ascent/descent, applied after smoothing (default: "
        f"{DEFAULT_ASCENT_THRESHOLD_M}; pass 0 to sum every consecutive difference with "
        "no threshold). See module docstring for why this exists.",
    )
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
        segments_fc,
        routes,
        dem,
        step_m=args.step_m,
        max_profile_points=args.max_profile_points,
        ascent_threshold_m=args.ascent_threshold_m,
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
