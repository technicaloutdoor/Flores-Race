"""Tests for build_profiles.py: the pure smoothing/ascent math on synthetic
elevation series, and (when a real DEM is available) an end-to-end run
against the fixture."""
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
    close to 600 m, the true climb, even with SRTM-scale noise added."""
    n = 60
    peak = 600.0
    up = [i * (peak / n) for i in range(n + 1)]
    down = [peak - i * (peak / n) for i in range(1, n + 1)]
    ramp = up + down
    noisy = _noisy(ramp)

    smoothed = build_profiles.smooth_elevations(noisy)
    ascent, descent = build_profiles.ascent_descent(smoothed)

    assert ascent == pytest.approx(peak, abs=40)
    assert descent == pytest.approx(peak, abs=40)


def test_smoothing_prevents_srtm_noise_from_inflating_a_flat_profile():
    """On a perfectly flat road, alternating +/-2 m SRTM noise should NOT
    read as real climbing once smoothed -- this is the whole point of the
    median-then-mean smoothing documented in build_profiles.py."""
    flat = [100.0] * 101
    noisy = _noisy(flat, amplitude=2.0)

    raw_ascent, raw_descent = build_profiles.ascent_descent(noisy)
    assert raw_ascent > 50  # unsmoothed, noise alone looks like real climbing

    smoothed = build_profiles.smooth_elevations(noisy)
    smooth_ascent, smooth_descent = build_profiles.ascent_descent(smoothed)
    assert smooth_ascent < raw_ascent / 4
    assert smooth_descent < raw_descent / 4


def test_unpaved_pct_from_character_and_surface_mix():
    assert build_profiles.unpaved_pct_for({"character": "paved"}) == 0.0
    assert build_profiles.unpaved_pct_for({"character": "gravel"}) == 100.0
    assert build_profiles.unpaved_pct_for({"character": "unknown"}) == 100.0
    mixed = {"character": "mixed", "surface_mix": {"paved": 2.0, "gravel": 6.0, "dirt": 2.0}}
    assert build_profiles.unpaved_pct_for(mixed) == 80.0


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
