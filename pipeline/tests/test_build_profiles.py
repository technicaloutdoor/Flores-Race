"""Tests for build_profiles.py: the pure smoothing/ascent math on synthetic
elevation series, the ascent hysteresis threshold, and (when a real DEM is
available) an end-to-end run against the fixture."""
import random

import pytest

import build_profiles
import common
from fixtures import make_routes, make_segments


def _noisy(values, amplitude=2.5, seed=1234):
    """Add small quasi-random per-sample noise, the way SRTM interpolation
    noise actually looks. Deliberately NOT a perfectly alternating +/-
    square wave: that period-2 pattern is the one input a median filter
    cannot remove (in any odd window >= 3, 3 of 5 samples share the
    center's sign, so the median just returns the center value unchanged)
    -- realistic terrain noise has no such exact periodicity."""
    rng = random.Random(seed)
    return [v + rng.uniform(-amplitude, amplitude) for v in values]


def test_ascent_descent_on_synthetic_ramp():
    """A clean ramp 0 -> 600 m -> 0 m: smoothed ascent/descent should each be
    close to 600 m, the true climb, even with SRTM-scale noise added and the
    default ascent threshold applied (a real climb this size survives both
    the smoothing pass and the threshold)."""
    n = 60
    peak = 600.0
    up = [i * (peak / n) for i in range(n + 1)]
    down = [peak - i * (peak / n) for i in range(1, n + 1)]
    ramp = up + down
    noisy = _noisy(ramp)

    smoothed = build_profiles.smooth_elevations(noisy)
    ascent, descent = build_profiles.ascent_descent(smoothed)  # default threshold

    assert ascent == pytest.approx(peak, abs=40)
    assert descent == pytest.approx(peak, abs=40)


def test_ascent_descent_threshold_is_exact_on_a_clean_ramp():
    """Synthetic ramp, no noise at all: the threshold accumulator must not
    eat into a genuine climb/descent -- with a single real reversal (at the
    peak), ascent/descent should come out exact, not just approximately
    close, at the default threshold."""
    n = 60
    peak = 600.0
    up = [i * (peak / n) for i in range(n + 1)]
    down = [peak - i * (peak / n) for i in range(1, n + 1)]
    ramp = up + down

    ascent, descent = build_profiles.ascent_descent(ramp)  # default threshold

    assert ascent == pytest.approx(peak, abs=1e-6)
    assert descent == pytest.approx(peak, abs=1e-6)


def test_smoothing_prevents_srtm_noise_from_inflating_a_flat_profile():
    """On a perfectly flat road, alternating +/-2 m SRTM noise should NOT
    read as real climbing once smoothed -- this is the whole point of the
    median-then-mean smoothing documented in build_profiles.py. Isolated
    from the ascent threshold (threshold_m=0 on both sides) so this test is
    about smoothing specifically, not the threshold covered below."""
    flat = [100.0] * 101
    noisy = _noisy(flat, amplitude=2.0)

    raw_ascent, raw_descent = build_profiles.ascent_descent(noisy, ascent_threshold_m=0)
    assert raw_ascent > 50  # unsmoothed, noise alone looks like real climbing

    smoothed = build_profiles.smooth_elevations(noisy)
    smooth_ascent, smooth_descent = build_profiles.ascent_descent(smoothed, ascent_threshold_m=0)
    assert smooth_ascent < raw_ascent / 4
    assert smooth_descent < raw_descent / 4


def test_ascent_threshold_silences_residual_noise_on_a_smoothed_flat_profile():
    """Even after smoothing, a flat profile keeps a metre or two of residual
    wobble (see module docstring, "Why smoothing alone is not enough"):
    without a threshold that residual still sums to a non-trivial "ascent";
    with the default threshold it reads as ~0, because no single reversal in
    this residual clears the threshold."""
    flat = [100.0] * 101
    noisy = _noisy(flat, amplitude=2.0)
    smoothed = build_profiles.smooth_elevations(noisy)

    ascent_no_threshold, _ = build_profiles.ascent_descent(smoothed, ascent_threshold_m=0)
    assert ascent_no_threshold > 0  # smoothing alone still leaves some residual climb

    ascent_default, _ = build_profiles.ascent_descent(
        smoothed, ascent_threshold_m=build_profiles.DEFAULT_ASCENT_THRESHOLD_M
    )
    assert ascent_default == pytest.approx(0.0, abs=3.0)
    assert ascent_default < ascent_no_threshold


def test_ascent_descent_threshold_zero_matches_naive_sum():
    """--ascent-threshold-m 0 must recover exactly the old (pre-threshold)
    "sum every consecutive difference" behaviour -- this is what the
    pipeline task's before/after measurements use for "before"."""
    rng = random.Random(7)
    values = [50.0 + rng.uniform(-3.0, 3.0) for _ in range(80)]

    naive = build_profiles._ascent_descent_naive(values)
    thresholded = build_profiles.ascent_descent(values, ascent_threshold_m=0)
    assert thresholded == naive


def test_unpaved_pct_from_character_and_surface_mix():
    assert build_profiles.unpaved_pct_for({"character": "paved"}) == 0.0
    assert build_profiles.unpaved_pct_for({"character": "gravel"}) == 100.0
    assert build_profiles.unpaved_pct_for({"character": "unknown"}) == 100.0
    mixed = {"character": "mixed", "surface_mix": {"paved": 2.0, "gravel": 6.0, "dirt": 2.0}}
    assert build_profiles.unpaved_pct_for(mixed) == 80.0


def test_ascent_threshold_default_is_wired_into_the_cli():
    """The CLI flag exists, defaults to the module constant, and 0 parses
    (used by --ascent-threshold-m 0 for the "before" measurement)."""
    parser = build_profiles.build_arg_parser()
    args = parser.parse_args(["--dem-dir", "unused", "--out", "unused"])
    assert args.ascent_threshold_m == build_profiles.DEFAULT_ASCENT_THRESHOLD_M

    args_zero = parser.parse_args(
        ["--dem-dir", "unused", "--out", "unused", "--ascent-threshold-m", "0"]
    )
    assert args_zero.ascent_threshold_m == 0.0


def test_build_profiles_end_to_end(dem_dir):
    segments_fc = make_segments()
    routes = make_routes()
    dem = common.load_dem(dem_dir)

    segments_out, routes_out, profiles = build_profiles.build_profiles(segments_fc, routes, dem)

    total_length = 0.0
    for feat in segments_out["features"]:
        props = feat["properties"]
        stats = props["stats"]
        assert stats["length_km"] > 0
        assert stats["min_elev_m"] >= 0  # bathymetry/void clamp
        assert stats["max_elev_m"] >= stats["min_elev_m"]
        assert stats["unpaved_pct"] == 100.0  # all fixture segments are "gravel"
        assert stats["profile_ref"] == props["id"]
        assert props["id"] in profiles
        assert len(profiles[props["id"]]) <= 400
        total_length += stats["length_km"]

    route = routes_out[0]
    assert route["stats"]["length_km"] == pytest.approx(total_length, rel=1e-6)
    assert route["stats"]["hab_km"] == pytest.approx(1.5, rel=1e-6)  # 3 * 0.5
    assert route["stats"]["segments_by_status"] == {"concept": 2, "desk-checked": 1}
    assert "r-fx-test" in profiles
    # Route profile is the concatenation of its segments' profiles, cumulative km.
    assert profiles["r-fx-test"][-1][0] == pytest.approx(total_length, abs=0.05)


def test_ascent_per_km_is_plausible_on_real_terrain(dem_dir):
    """End-to-end sanity check against the real Ruteng-area SRTM DEM
    (dem_dir fixture, guarded by FLORES_RACE_TEST_DEM_DIR -- see
    conftest.py): with the default threshold, ascent per km should land in a
    plausible range for hilly Flores terrain rather than the many hundreds
    of m/km unthresholded SRTM noise can produce over a long, noisy profile,
    and should never exceed what the same profile gives with the threshold
    disabled (the threshold only ever removes climbing, never adds any)."""
    segments_fc = make_segments()
    dem = common.load_dem(dem_dir)

    segments_default, _, _ = build_profiles.build_profiles(segments_fc, [], dem)
    segments_raw, _, _ = build_profiles.build_profiles(
        segments_fc, [], dem, ascent_threshold_m=0.0
    )

    for feat_default, feat_raw in zip(segments_default["features"], segments_raw["features"]):
        stats_default = feat_default["properties"]["stats"]
        stats_raw = feat_raw["properties"]["stats"]
        km = stats_default["length_km"]
        assert km > 0
        per_km_default = stats_default["ascent_m"] / km
        # Generous upper bound for short fixture segments in real hill
        # country (see module docstring for the measured project-wide
        # figures this bound is chosen against).
        assert per_km_default < 200
        assert stats_default["ascent_m"] <= stats_raw["ascent_m"] + 1e-9
        assert stats_default["descent_m"] <= stats_raw["descent_m"] + 1e-9
