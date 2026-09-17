"""Tests for validate.py using the in-code fixture (see fixtures.py)."""
from pathlib import Path

import validate
from fixtures import write_fixture

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


def test_validate_passes_on_fixture(tmp_path):
    write_fixture(tmp_path)
    report = validate.validate_data(tmp_path, SCHEMAS_DIR)
    assert report.errors == [], report.errors


def test_validate_fails_on_broken_chain(tmp_path):
    write_fixture(tmp_path, broken_route=True)
    report = validate.validate_data(tmp_path, SCHEMAS_DIR)
    assert report.errors, "a route with a scrambled segment order must fail validation"
    assert any("r-fx-test" in e for e in report.errors)


def test_validate_reports_unknown_segment_reference(tmp_path):
    write_fixture(tmp_path)
    routes_path = tmp_path / "routes.json"
    routes = validate.common.read_json(routes_path)
    routes[0]["segments"].append("s-does-not-exist")
    validate.common.write_json(routes_path, routes)

    report = validate.validate_data(tmp_path, SCHEMAS_DIR)
    assert any("s-does-not-exist" in e for e in report.errors)


def test_validate_reports_scouting_reference_to_missing_segment(tmp_path):
    write_fixture(tmp_path)
    md_path = tmp_path / "scouting" / "2026-01-01-fixture.md"
    text = md_path.read_text(encoding="utf-8")
    md_path.write_text(text.replace("s-fx-start-mid1-a", "s-not-a-real-segment"), encoding="utf-8")

    report = validate.validate_data(tmp_path, SCHEMAS_DIR)
    assert any("s-not-a-real-segment" in e for e in report.errors)


def test_endpoint_far_from_node_is_warning_for_concept_sketch_but_error_otherwise(tmp_path):
    write_fixture(tmp_path)
    segments_path = tmp_path / "segments.geojson"
    segments_fc = validate.common.read_geojson(segments_path)

    # s-fx-start-mid1-a is geometry_source "concept-sketch": push its first
    # vertex far from n-fx-start -> should be a warning, not an error.
    seg = next(f for f in segments_fc["features"] if f["properties"]["id"] == "s-fx-start-mid1-a")
    assert seg["properties"]["geometry_source"] == "concept-sketch"
    seg["geometry"]["coordinates"][0] = [121.0, -9.0]
    validate.common.write_geojson(segments_path, segments_fc)

    report = validate.validate_data(tmp_path, SCHEMAS_DIR)
    assert not any("s-fx-start-mid1-a" in e for e in report.errors)
    assert any("s-fx-start-mid1-a" in w for w in report.warnings)


def test_endpoint_far_from_node_is_error_for_non_concept_sketch(tmp_path):
    write_fixture(tmp_path)
    segments_path = tmp_path / "segments.geojson"
    segments_fc = validate.common.read_geojson(segments_path)

    # s-fx-mid1-mid2-a is geometry_source "manual-trace" -> should be an error.
    seg = next(f for f in segments_fc["features"] if f["properties"]["id"] == "s-fx-mid1-mid2-a")
    assert seg["properties"]["geometry_source"] == "manual-trace"
    seg["geometry"]["coordinates"][-1] = [121.0, -9.0]
    validate.common.write_geojson(segments_path, segments_fc)

    report = validate.validate_data(tmp_path, SCHEMAS_DIR)
    assert any("s-fx-mid1-mid2-a" in e for e in report.errors)
