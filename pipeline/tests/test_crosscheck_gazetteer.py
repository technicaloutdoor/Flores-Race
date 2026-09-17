"""Tests for crosscheck_gazetteer.py.

Everything here runs on tiny, hand-built synthetic inputs -- no dependency on
the real `data/` (another task owns and is actively editing it), the real
Overture extract, or the real SRTM DEM. A `FakeDem`/`NoDataDem` stand in for
`dem.DEM` wherever elevation is needed.

Covers, per the brief: a name-normalisation table, fuzzy/containment
matching (including the word-boundary fix that keeps a short toponym from
matching *inside* an unrelated compound word), verdict thresholds, and the
village-inside-polygon override -- plus gazetteer loading from tiny synthetic
`.geojsonl` files, the DEM checks, and a full CLI run for good measure.
"""
from __future__ import annotations

import json
import math

import pytest
from shapely.geometry import Polygon

import common
import crosscheck_gazetteer as cg


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

NORMALISATION_CASES = [
    # Indonesian generic prefixes stripped (BRIEF.md's list)
    ("Danau Kelimutu", "kelimutu"),
    ("Gunung Ebulobo", "ebulobo"),
    ("Poco Ranaka", "ranaka"),
    ("Pulau Rinca", "rinca"),
    ("Pantai Koka", "koka"),
    ("Gua Liang Bua", "liang bua"),
    ("Bukit Wolobobo", "wolobobo"),
    # "kantor desa"/"kantor kelurahan" collapse to the bare village name
    ("Kantor Desa Watu Galang", "watu galang"),
    ("Kantor Kelurahan Bajawa", "bajawa"),
    # Multi-word phrases removed as a unit, not word-by-word
    ("Taman Nasional Kelimutu", "kelimutu"),
    ("Air Terjun Cunca Rami", "cunca rami"),
    ("Air Panas Mataloko", "mataloko"),
    ("Mataloko Hot Springs", "mataloko"),
    # English generics
    ("Mount Egon", "egon"),
    ("Mt. Inerie", "inerie"),
    ("Komodo Island", "komodo"),
    # Compound words that merely *contain* a generic word as a substring must
    # survive whole -- this is the whole point of word-boundary stripping.
    ("Kelimutu", "kelimutu"),  # contains "keli" but is not "Keli Mutu"
    ("Wolojita", "wolojita"),  # contains "wolo"
    ("Wologai", "wologai"),
    # Diacritics stripped
    ("Pulau Wé", "we"),
    # Case-insensitive
    ("KELIMUTU", "kelimutu"),
    # Hyphens become spaces, punctuation dropped, whitespace collapsed
    ("Lewotobi Laki-laki", "lewotobi laki laki"),
    ("  Sano   Nggoang  ", "sano nggoang"),
    ("Reinha Rosari Cathedral (Larantuka)", "reinha rosari cathedral larantuka"),
    # A name that is *entirely* generic words has nothing left to match on
    ("Danau", ""),
    ("Kantor Desa", ""),
    (None, ""),
    ("", ""),
]


@pytest.mark.parametrize("raw,expected", NORMALISATION_CASES)
def test_normalise_name(raw, expected):
    assert cg.normalise_name(raw) == expected


def test_name_variants_dedupes_and_drops_empties():
    # name and local_name normalise to the same thing -> one variant, not two
    assert cg.name_variants("Danau Kelimutu", "Kelimutu") == ["kelimutu"]
    # no local_name at all
    assert cg.name_variants("Gunung Ebulobo", None) == ["ebulobo"]
    # local_name that is purely generic contributes nothing
    assert cg.name_variants("Bena", "Kampung") == ["bena"]
    # both empty -> no variants to try
    assert cg.name_variants("", None) == []


# ---------------------------------------------------------------------------
# Fuzzy / containment matching
# ---------------------------------------------------------------------------


def test_name_match_exact():
    assert cg.name_match("kelimutu", "kelimutu") == (1.0, "exact")


def test_name_match_none_for_empty_input():
    assert cg.name_match("", "kelimutu") is None
    assert cg.name_match("kelimutu", "") is None


def test_name_match_fuzzy_ratio_above_threshold():
    # "ranaka" vs "ranakah": not a whole-word containment (the extra "h"
    # blocks the word boundary), so this can only pass via difflib ratio.
    result = cg.name_match("ranaka", "ranakah")
    assert result is not None
    score, mtype = result
    assert mtype == "fuzzy-ratio"
    assert score >= 0.85


def test_name_match_rejects_ratio_below_threshold():
    assert cg.name_match("ranaka", "totally different name") is None


def test_name_match_word_bounded_containment():
    # "egon" is a whole word inside "ili egon" (ratio alone is too low: 0.67)
    result = cg.name_match("egon", "ili egon")
    assert result is not None
    score, mtype = result
    assert mtype == "fuzzy-contains"


def test_name_match_rejects_fragment_inside_compound_word():
    # Regression: a bare substring test would "match" these (both are
    # literal character substrings) even though they are unrelated places --
    # see crosscheck_gazetteer.py's _contains_word_bounded docstring.
    assert cg.name_match("nggela", "maronggela") is None
    assert cg.name_match("denge", "wae denger") is None


def test_contains_word_bounded_requires_length_4():
    # Below length 4, containment is never accepted, even as a clean,
    # boundary-respecting whole word.
    assert cg._contains_word_bounded("io", "io lorenzo") is False
    assert cg._contains_word_bounded("reo", "kelurahan reo") is False
    # At length 4 a clean whole-word match is accepted.
    assert cg._contains_word_bounded("elar", "kantor camat elar") is True


def test_contains_word_bounded_both_directions():
    assert cg._contains_word_bounded("watu galang", "desa watu galang timur") is True
    assert cg._contains_word_bounded("desa watu galang timur", "watu galang") is False


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "distance_km,expected",
    [
        (None, "unmatched"),
        (0.0, "confirmed"),
        (cg.CONFIRMED_KM, "confirmed"),
        (cg.CONFIRMED_KM + 0.01, "plausible"),
        (cg.PLAUSIBLE_KM, "plausible"),
        (cg.PLAUSIBLE_KM + 0.01, "suspect"),
        (cg.SUSPECT_KM, "suspect"),
        (cg.SUSPECT_KM + 0.01, "wrong"),
        (50.0, "wrong"),
    ],
)
def test_classify(distance_km, expected):
    assert cg.classify(distance_km) == expected


# ---------------------------------------------------------------------------
# Synthetic curated-feature / gazetteer helpers shared by the tests below
# ---------------------------------------------------------------------------


def _node_feature(feature_id, name, kind, lon, lat, **props):
    properties = {"id": feature_id, "name": name, "kind": kind, "confidence": "approximate"}
    properties.update(props)
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": properties}


def _poi_feature(feature_id, name, category, lon, lat, **props):
    properties = {"id": feature_id, "name": name, "category": category, "confidence": "approximate"}
    properties.update(props)
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": properties}


def _gaz_entry(name, bucket, lon, lat, source_file="place", source_id="g-1", geometry=None, elevation=None):
    return cg.GazEntry(
        name=name,
        normalised_name=cg.normalise_name(name),
        bucket=bucket,
        kind_label=f"{source_file}:test",
        lon=lon,
        lat=lat,
        elevation=elevation,
        source_file=source_file,
        source_id=source_id,
        geometry=geometry,
    )


# ---------------------------------------------------------------------------
# Inside-polygon override
# ---------------------------------------------------------------------------


def test_village_inside_polygon_confirms_despite_far_centroid():
    # A long, thin desa polygon: ~3.3 km east-west, ~0.1 km north-south.
    # Centroid sits near the west end; the curated point sits inside the
    # polygon at the *east* end, over 1 km from the centroid -- far enough
    # that plain distance-to-centroid classification alone would call it
    # only "plausible", not "confirmed".
    polygon = Polygon([(120.00, -8.000), (120.00, -8.001), (120.03, -8.001), (120.03, -8.000)])
    entry = _gaz_entry(
        "Testville", "village_area", polygon.centroid.x, polygon.centroid.y,
        source_file="division_area", source_id="div-1", geometry=polygon,
    )
    centroid_distance_km = cg.haversine_km(120.029, -8.0005, polygon.centroid.x, polygon.centroid.y)
    assert cg.classify(centroid_distance_km) != "confirmed"  # sanity: the raw-distance rule would NOT confirm

    feature = _node_feature("n-testville", "Testville", "village", 120.029, -8.0005)
    result = cg.process_feature("nodes", feature, "kind", cg.NODE_COMPAT, [entry], dem=None)

    assert result["verdict"] == "confirmed"
    # The reported match is still the nearest *compatible* candidate (the
    # polygon itself, here -- the only candidate), so its distance is exactly
    # the centroid distance the plain rule would have rejected (rounded to
    # 3 decimals by Candidate.as_dict).
    assert result["match"]["distance_km"] == pytest.approx(centroid_distance_km, abs=1e-3)


def test_outside_polygon_falls_back_to_distance_classification():
    polygon = Polygon([(120.00, -8.000), (120.00, -8.001), (120.03, -8.001), (120.03, -8.000)])
    entry = _gaz_entry(
        "Testville", "village_area", polygon.centroid.x, polygon.centroid.y,
        source_file="division_area", source_id="div-1", geometry=polygon,
    )
    # Well outside the polygon and > 8 km from the centroid.
    feature = _node_feature("n-testville", "Testville", "village", 120.10, -8.05)
    result = cg.process_feature("nodes", feature, "kind", cg.NODE_COMPAT, [entry], dem=None)

    assert result["verdict"] == "wrong"
    assert result["match"]["inside_polygon"] is False


def test_division_point_geometry_never_triggers_inside_override():
    # A division_area feature that came back as a bare Point (not a
    # Polygon/MultiPolygon) carries no geometry to test containment against
    # (see load_gazetteer) -- confirm process_feature still classifies it by
    # plain distance rather than crashing or auto-confirming.
    entry = _gaz_entry("Testville", "village_area", 120.10, -8.05, source_file="division_area", source_id="div-2")
    feature = _node_feature("n-testville", "Testville", "village", 120.10, -8.05)
    result = cg.process_feature("nodes", feature, "kind", cg.NODE_COMPAT, [entry], dem=None)
    assert result["verdict"] == "confirmed"  # 0 km away, by plain distance
    assert result["match"]["inside_polygon"] is False


# ---------------------------------------------------------------------------
# Category/kind compatibility and candidate selection
# ---------------------------------------------------------------------------


def test_incompatible_bucket_is_unmatched_with_off_kind_note():
    # A school named after the volcano is not a "peak"/place-layer match for
    # "airport" -- it must not satisfy the strict place_airport compat set.
    entry = _gaz_entry("Egon Airport Cafe", "place", 122.4556, -8.6762)
    feature = _poi_feature("p-egon-air", "Egon Airport", "airport", 122.4556, -8.6762)
    result = cg.process_feature("pois", feature, "category", cg.POI_COMPAT, [entry], dem=None)
    assert result["verdict"] == "unmatched"
    assert result["match"] is None
    assert "not compatible with 'airport'" in result["off_kind_note"]


def test_nearest_compatible_candidate_wins_over_stronger_name_match_far_away():
    # Two "Wai Sano"-named entries: an exact-name match far away, and a
    # weaker (fuzzy) but much closer one. Nearest compatible wins, per
    # crosscheck_gazetteer.py's module docstring (string similarity is a
    # filter, not a ranking signal).
    far_exact = _gaz_entry("Wai Sano", "peak", 121.0, -9.5, source_file="land", source_id="far")
    near_fuzzy = _gaz_entry("Gunung Wai Sano Barat", "peak", 120.02, -8.73, source_file="land", source_id="near")
    feature = _poi_feature("p-wai-sano", "Wai Sano volcano", "volcano", 120.038, -8.641, local_name="Gunung Wai Sano")
    result = cg.process_feature("pois", feature, "category", cg.POI_COMPAT, [far_exact, near_fuzzy], dem=None)
    assert result["match"]["source_id"] == "near"


def test_suggested_fix_suppressed_for_generic_place_bucket():
    entry = _gaz_entry("Aimere Warung", "place", 120.85, -8.84)  # far away, generic bucket
    feature = _node_feature("n-aimere", "Aimere", "port", 120.994, -8.95)
    result = cg.process_feature("nodes", feature, "kind", cg.NODE_COMPAT, [entry], dem=None)
    assert result["verdict"] == "wrong"
    assert result["suggested_fix"] is None


def test_suggested_fix_offered_for_strong_bucket():
    entry = _gaz_entry("Gunung Wai Sano", "peak", 120.0177, -8.7396, source_file="land", source_id="land-1")
    feature = _poi_feature("p-wai-sano", "Wai Sano volcano", "volcano", 120.038, -8.641)
    result = cg.process_feature("pois", feature, "category", cg.POI_COMPAT, [entry], dem=None)
    assert result["verdict"] == "wrong"
    assert result["suggested_fix"] == [120.0177, -8.7396]


def test_ambiguous_requires_separation_between_candidates():
    # Two near-duplicate records for the same real spot (40 m apart) must
    # NOT be flagged ambiguous -- they agree on where the place is.
    dup_a = _gaz_entry("Koka Beach", "beach", 122.018125, -8.795162, source_id="a")
    dup_b = _gaz_entry("Koka Beach", "beach", 122.0185, -8.795162, source_id="b")  # ~40 m east
    feature = _poi_feature("p-koka", "Koka Beach", "beach", 122.018125, -8.795162)
    result = cg.process_feature("pois", feature, "category", cg.POI_COMPAT, [dup_a, dup_b], dem=None)
    assert result["ambiguous"] is False

    # Two genuinely different candidates, each ~1.1 km from the query in
    # opposite directions (so both are comparably close to the query) but
    # over 2 km from *each other* -- a real disagreement about location.
    query_lon, query_lat = 121.822, -8.751
    north = _gaz_entry("Moni Cafe", "place", query_lon, query_lat + 0.01, source_id="c")
    south = _gaz_entry("Moni Lodge", "place", query_lon, query_lat - 0.01, source_id="d")
    feature2 = _poi_feature("p-moni", "Moni", "other", query_lon, query_lat)
    result2 = cg.process_feature("pois", feature2, "category", cg.POI_COMPAT, [north, south], dem=None)
    assert result2["ambiguous"] is True
    assert result2["suggested_fix"] is None  # ambiguity suppresses the suggestion too


# ---------------------------------------------------------------------------
# DEM checks (elevation mismatch + local-max snap suggestion)
# ---------------------------------------------------------------------------


class FakeDem:
    """Synthetic single-cone DEM: elevation falls off linearly from a known
    peak at (lon0, lat0). Stands in for dem.DEM so tests never touch the
    real SRTM tiles."""

    def __init__(self, lon0, lat0, peak_elev, base_elev=0.0, falloff_per_km=50.0):
        self.lon0 = lon0
        self.lat0 = lat0
        self.peak_elev = peak_elev
        self.base_elev = base_elev
        self.falloff_per_km = falloff_per_km

    def elevation(self, lon, lat):
        dist_km = common.haversine_m(lon, lat, self.lon0, self.lat0) / 1000.0
        return max(self.base_elev, self.peak_elev - dist_km * self.falloff_per_km)


class NoDataDem:
    """A DEM with no coverage at all (e.g. off the loaded tiles)."""

    def elevation(self, lon, lat):
        return None


def test_elevation_check_flags_major_mismatch():
    dem = FakeDem(120.0, -8.0, peak_elev=1000.0)
    result = cg.elevation_check(dem, 120.0, -8.0, claimed_m=500.0)
    assert result["dem_elevation_m"] == pytest.approx(1000.0)
    assert result["diff_m"] == pytest.approx(500.0)
    assert result["major"] is True


def test_elevation_check_within_tolerance_is_not_major():
    dem = FakeDem(120.0, -8.0, peak_elev=1000.0)
    result = cg.elevation_check(dem, 120.0, -8.0, claimed_m=950.0)
    assert result["major"] is False


def test_elevation_check_none_without_a_claim():
    dem = FakeDem(120.0, -8.0, peak_elev=1000.0)
    assert cg.elevation_check(dem, 120.0, -8.0, None) is None


def test_local_dem_max_finds_offset_peak_and_flags_snap():
    query_lon, query_lat = 120.0, -8.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(query_lat))
    peak_lon = query_lon + 1000.0 / m_per_deg_lon  # true summit ~1000 m east
    peak_lat = query_lat
    dem = FakeDem(peak_lon, peak_lat, peak_elev=1500.0, base_elev=900.0, falloff_per_km=50.0)

    result = cg.local_dem_max(dem, query_lon, query_lat)
    assert result is not None
    assert result["distance_m"] > cg.LOCAL_MAX_SNAP_M
    assert result["elevation_m"] > result["center_elevation_m"]
    # the grid search should land close to the true peak (within one step)
    found_vs_true_m = common.haversine_m(result["lon"], result["lat"], peak_lon, peak_lat)
    assert found_vs_true_m < cg.LOCAL_MAX_STEP_M * 1.5


def test_local_dem_max_none_without_data_at_query_point():
    assert cg.local_dem_max(NoDataDem(), 120.0, -8.0) is None


def test_process_feature_dem_note_for_volcano_with_offset_peak():
    query_lon, query_lat = 120.0, -8.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(query_lat))
    peak_lon = query_lon + 1000.0 / m_per_deg_lon
    dem = FakeDem(peak_lon, query_lat, peak_elev=1500.0, base_elev=900.0, falloff_per_km=50.0)
    entry = _gaz_entry("Test Volcano", "peak", query_lon, query_lat, source_file="land", source_id="v-1")
    feature = _poi_feature("p-test-volcano", "Test Volcano", "volcano", query_lon, query_lat, elevation_m=1400)

    result = cg.process_feature("pois", feature, "category", cg.POI_COMPAT, [entry], dem=dem)
    assert result["verdict"] == "confirmed"  # matched itself at 0 km
    assert "consider snapping" in result["dem_note"]


def test_process_feature_without_dem_skips_dem_checks():
    entry = _gaz_entry("Test Volcano", "peak", 120.0, -8.0, source_file="land", source_id="v-1")
    feature = _poi_feature("p-test-volcano", "Test Volcano", "volcano", 120.0, -8.0, elevation_m=1400)
    result = cg.process_feature("pois", feature, "category", cg.POI_COMPAT, [entry], dem=None)
    assert result["dem_note"] is None
    assert result["elevation_check"] is None
    assert result["local_max"] is None


# ---------------------------------------------------------------------------
# Gazetteer loading from tiny synthetic .geojsonl files
# ---------------------------------------------------------------------------


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_load_gazetteer_buckets_and_skips_unnamed(tmp_path):
    _write_jsonl(
        tmp_path / "place.geojsonl",
        [
            {
                "properties": {"id": "pl-1", "name": "Kantor Desa Testvillage", "category": "central_government_office"},
                "geometry": {"type": "Point", "coordinates": [120.0, -8.0]},
            },
            {
                # A regency-scoped office must NOT count as a village locator.
                "properties": {"id": "pl-2", "name": "Dinas Kesehatan Kabupaten Testkab", "category": "central_government_office"},
                "geometry": {"type": "Point", "coordinates": [120.1, -8.1]},
            },
            {
                # No name -> skipped entirely (nothing to match on).
                "properties": {"id": "pl-3", "name": None, "category": "school"},
                "geometry": {"type": "Point", "coordinates": [120.2, -8.2]},
            },
        ],
    )
    _write_jsonl(
        tmp_path / "land.geojsonl",
        [
            {
                "properties": {"id": "ld-1", "name": "Gunung Test", "class": "volcano", "elevation": 1234},
                "geometry": {"type": "Point", "coordinates": [120.3, -8.3]},
            },
        ],
    )
    _write_jsonl(
        tmp_path / "water.geojsonl",
        [
            {
                "properties": {"id": "wt-1", "name": "Danau Test", "class": "lake"},
                "geometry": {"type": "Point", "coordinates": [120.4, -8.4]},
            },
        ],
    )
    square = [[120.5, -8.5], [120.5, -8.6], [120.6, -8.6], [120.6, -8.5], [120.5, -8.5]]
    _write_jsonl(
        tmp_path / "division_area.geojsonl",
        [
            {
                "properties": {"id": "dv-1", "name": "Testville", "subtype": "locality"},
                "geometry": {"type": "Polygon", "coordinates": [square]},
            },
        ],
    )
    _write_jsonl(
        tmp_path / "land_use.geojsonl",
        [
            {
                "properties": {"id": "lu-1", "name": "Test National Park", "class": "national_park"},
                "geometry": {"type": "Point", "coordinates": [120.7, -8.7]},
            },
        ],
    )

    gaz = cg.load_gazetteer(tmp_path)
    by_id = {e.source_id: e for e in gaz}

    assert len(gaz) == 6  # every row but pl-3 (unnamed), which has nothing to match on
    assert by_id["pl-1"].bucket == "place_gov"
    assert by_id["pl-1"].normalised_name == "testvillage"  # "kantor desa" stripped
    assert by_id["pl-2"].bucket == "place"  # demoted: regency-scoped office
    assert by_id["ld-1"].bucket == "peak"
    assert by_id["ld-1"].elevation == 1234
    assert by_id["wt-1"].bucket == "lake"
    assert by_id["dv-1"].bucket == "village_area"
    assert by_id["dv-1"].geometry is not None  # polygon kept for the inside-test
    assert by_id["lu-1"].bucket == "national_park"


def test_load_gazetteer_missing_file_is_skipped(tmp_path):
    # No .geojsonl files at all -> empty gazetteer, not a crash.
    assert cg.load_gazetteer(tmp_path) == []


def test_load_gazetteer_division_point_geometry_dropped(tmp_path):
    _write_jsonl(
        tmp_path / "division_area.geojsonl",
        [
            {
                "properties": {"id": "dv-2", "name": "Pointville", "subtype": "neighborhood"},
                "geometry": {"type": "Point", "coordinates": [120.0, -8.0]},
            },
        ],
    )
    gaz = cg.load_gazetteer(tmp_path)
    assert gaz[0].geometry is None


# ---------------------------------------------------------------------------
# Report assembly: findings, caveats, summary
# ---------------------------------------------------------------------------


def _result(
    file_label="pois", feature_id="p-x", name="X", verdict="confirmed", match=None,
    ambiguous=False, runner_up=None, off_kind_note=None, elevation_check=None, local_max=None,
    suggested_fix=None,
):
    return {
        "file": file_label,
        "id": feature_id,
        "name": name,
        "local_name": None,
        "kind_or_category": "other",
        "confidence": "approximate",
        "lon": 120.0,
        "lat": -8.0,
        "match": match,
        "runner_up": runner_up,
        "ambiguous": ambiguous,
        "verdict": verdict,
        "off_kind_note": off_kind_note,
        "elevation_check": elevation_check,
        "local_max": local_max,
        "dem_note": None,
        "suggested_fix": suggested_fix,
    }


def test_collect_findings_severity_mapping():
    match = {
        "name": "Somewhere Else", "kind_label": "place:test", "source_file": "place", "source_id": "id1",
        "lon": 120.1, "lat": -8.1, "distance_km": 9.5, "match_type": "exact", "inside_polygon": False,
    }
    results = [
        _result(feature_id="p-wrong", verdict="wrong", match=match),
        _result(feature_id="p-suspect", verdict="suspect", match=match),
        _result(feature_id="p-unmatched", verdict="unmatched", off_kind_note="nothing compatible nearby"),
        _result(feature_id="p-confirmed", verdict="confirmed", match=match),
        _result(
            feature_id="p-elev",
            verdict="confirmed",
            match=match,
            elevation_check={"claimed_elevation_m": 500, "dem_elevation_m": 900.0, "diff_m": 400.0, "major": True},
        ),
    ]
    findings = cg.collect_findings(results)
    by_id_severity = {(f["feature_id"], f["severity"]) for f in findings}

    assert ("p-wrong", "blocker") in by_id_severity
    assert ("p-suspect", "major") in by_id_severity
    assert ("p-unmatched", "minor") in by_id_severity
    assert ("p-elev", "major") in by_id_severity
    # a plain "confirmed" feature with nothing wrong contributes no finding
    assert not any(f["feature_id"] == "p-confirmed" for f in findings)
    # exactly the elevation-mismatch finding for p-elev (verdict itself is fine)
    assert sum(1 for f in findings if f["feature_id"] == "p-elev") == 1


def test_summarise_counts_every_verdict():
    results = [_result(verdict=v) for v in ("confirmed", "confirmed", "plausible", "wrong", "unmatched")]
    counts = cg.summarise(results)
    assert counts == {"confirmed": 2, "plausible": 1, "suspect": 0, "wrong": 1, "unmatched": 1}


def test_build_report_confirmed_ids_and_summary_totals():
    node_results = [_result(file_label="nodes", feature_id="n-a", verdict="confirmed")]
    poi_results = [
        _result(file_label="pois", feature_id="p-a", verdict="confirmed"),
        _result(file_label="pois", feature_id="p-b", verdict="wrong"),
    ]
    report = cg.build_report(node_results, poi_results)

    assert report["confirmed_ids"] == ["n-a", "p-a"]
    assert sum(report["summary"]["nodes"].values()) == 1
    assert sum(report["summary"]["pois"].values()) == 2
    assert sum(report["summary"]["overall"].values()) == 3
    assert isinstance(report["caveats"], list) and len(report["caveats"]) >= 2  # the two static caveats


def test_render_markdown_escapes_pipes_and_includes_sections():
    match = {
        "name": "A | Weird Name", "kind_label": "place:test", "source_file": "place", "source_id": "abcdefgh1234",
        "lon": 120.1, "lat": -8.1, "distance_km": 0.5, "match_type": "exact", "inside_polygon": False,
    }
    report = cg.build_report(
        [_result(file_label="nodes", feature_id="n-a", verdict="confirmed", match=match)],
        [],
    )
    text = cg.render_markdown(report)

    assert "# Gazetteer cross-check report" in text
    assert "## Summary" in text
    assert "## data/nodes.geojson" in text
    assert "## data/pois.geojson" in text
    assert "## Caveats" in text
    assert "## Confirmed ids" in text
    assert "n-a" in text
    # the pipe inside the matched name must not have broken the table
    assert "A / Weird Name" in text
    row_lines = [ln for ln in text.splitlines() if ln.startswith("| n-a")]
    assert len(row_lines) == 1
    assert row_lines[0].count("|") == 10  # 9 columns -> 10 pipe separators


# ---------------------------------------------------------------------------
# End-to-end CLI run on a tiny synthetic data/ + overture-dir
# ---------------------------------------------------------------------------


def test_run_end_to_end_without_dem(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    overture_dir = tmp_path / "overture"
    overture_dir.mkdir()

    common.write_geojson(
        data_dir / "nodes.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                _node_feature("n-testville", "Testville", "village", 120.001, -8.001),
                _node_feature("n-nowhere", "Nowhereton", "junction", 121.5, -8.5),
            ],
        },
    )
    common.write_geojson(
        data_dir / "pois.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                _poi_feature("p-test-volcano", "Test Volcano", "volcano", 120.100, -8.100, elevation_m=1000),
            ],
        },
    )
    _write_jsonl(
        overture_dir / "place.geojsonl",
        [
            {
                "properties": {"id": "pl-1", "name": "Kantor Desa Testville", "category": "central_government_office"},
                "geometry": {"type": "Point", "coordinates": [120.001, -8.001]},
            },
        ],
    )
    _write_jsonl(
        overture_dir / "land.geojsonl",
        [
            {
                "properties": {"id": "ld-1", "name": "Test Volcano", "class": "volcano", "elevation": 1000},
                "geometry": {"type": "Point", "coordinates": [120.100, -8.100]},
            },
        ],
    )
    for extra in ("water.geojsonl", "division_area.geojsonl", "land_use.geojsonl"):
        (overture_dir / extra).write_text("", encoding="utf-8")

    report = cg.run(data_dir, overture_dir, dem_dir=None)

    assert report["summary"]["overall"]["confirmed"] == 2
    ids = {r["id"] for r in report["features"]["nodes"] + report["features"]["pois"]}
    assert ids == {"n-testville", "n-nowhere", "p-test-volcano"}
    nowhere = next(r for r in report["features"]["nodes"] if r["id"] == "n-nowhere")
    assert nowhere["verdict"] == "unmatched"
    # No DEM was supplied -> no elevation/local-max checks anywhere.
    assert all(r["elevation_check"] is None for r in report["features"]["pois"])


def test_main_writes_report_files_and_returns_zero(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    overture_dir = tmp_path / "overture"
    overture_dir.mkdir()
    common.write_geojson(
        data_dir / "nodes.geojson",
        {"type": "FeatureCollection", "features": [_node_feature("n-a", "Placeholder", "junction", 120.0, -8.0)]},
    )
    common.write_geojson(data_dir / "pois.geojson", {"type": "FeatureCollection", "features": []})
    for name in ("place.geojsonl", "land.geojsonl", "water.geojsonl", "division_area.geojsonl", "land_use.geojsonl"):
        (overture_dir / name).write_text("", encoding="utf-8")

    out_md = tmp_path / "out" / "report.md"
    out_json = tmp_path / "out" / "report.json"
    exit_code = cg.main(
        [
            "--data", str(data_dir),
            "--overture-dir", str(overture_dir),
            "--out", str(out_md),
            "--json", str(out_json),
        ]
    )

    assert exit_code == 0
    assert out_md.exists()
    assert "# Gazetteer cross-check report" in out_md.read_text(encoding="utf-8")
    written = json.loads(out_json.read_text(encoding="utf-8"))
    assert written["summary"]["overall"]["unmatched"] == 1
