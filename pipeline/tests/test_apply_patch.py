"""Tests for apply_patch.py: a legitimate scouting patch applies cleanly;
one that tries to change geometry or an id is refused, at both the CLI level
(schema validation) and the merge level (defense in depth, see
apply_patch.py's docstring)."""
from pathlib import Path

import apply_patch
import common
from fixtures import make_nodes, make_pois, make_segments, write_fixture

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


def _valid_patch() -> dict:
    return {
        "version": 1,
        "created": "2026-01-02T10:00:00Z",
        "author": "RC",
        "segments": {
            "s-fx-start-mid1-a": {
                "status": "scouted-go",
                "character": "dirt",
                "scouting_append": [
                    {"date": "2026-01-02", "team": "RC", "verdict": "go", "notes": "rideable"}
                ],
            }
        },
        "nodes": {"n-fx-mid1": {"water": "reliable"}},
        "new_pois": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [120.46, -8.6]},
                "properties": {
                    "name": "Fixture Spring",
                    "category": "hot-spring",
                    "summary": "Reported by the scouting team.",
                    "race_relevance": "resupply",
                    "access": "trail",
                    "confidence": "unverified",
                    "sources": ["field:2026-01-02"],
                },
            }
        ],
    }


def test_apply_patch_valid_change(tmp_path):
    write_fixture(tmp_path)
    patch_path = tmp_path / "patch.json"
    common.write_json(patch_path, _valid_patch())

    rc = apply_patch.main(
        ["--patch", str(patch_path), "--data", str(tmp_path), "--schemas", str(SCHEMAS_DIR)]
    )
    assert rc == 0

    segments_fc = common.read_geojson(tmp_path / "segments.geojson")
    seg = next(f for f in segments_fc["features"] if f["properties"]["id"] == "s-fx-start-mid1-a")
    assert seg["properties"]["status"] == "scouted-go"
    assert seg["properties"]["character"] == "dirt"
    assert len(seg["properties"].get("scouting", [])) == 1

    nodes_fc = common.read_geojson(tmp_path / "nodes.geojson")
    node = next(f for f in nodes_fc["features"] if f["properties"]["id"] == "n-fx-mid1")
    assert node["properties"]["water"] == "reliable"

    pois_fc = common.read_geojson(tmp_path / "pois.geojson")
    assert any(f["properties"]["name"] == "Fixture Spring" for f in pois_fc["features"])
    new_poi = next(f for f in pois_fc["features"] if f["properties"]["name"] == "Fixture Spring")
    assert new_poi["properties"]["id"].startswith("p-")


def test_apply_patch_dry_run_writes_nothing(tmp_path):
    write_fixture(tmp_path)
    before = (tmp_path / "segments.geojson").read_text(encoding="utf-8")
    patch_path = tmp_path / "patch.json"
    common.write_json(patch_path, _valid_patch())

    rc = apply_patch.main(
        [
            "--patch",
            str(patch_path),
            "--data",
            str(tmp_path),
            "--schemas",
            str(SCHEMAS_DIR),
            "--dry-run",
        ]
    )
    assert rc == 0
    after = (tmp_path / "segments.geojson").read_text(encoding="utf-8")
    assert before == after


def test_apply_patch_refuses_geometry_change_via_cli(tmp_path):
    write_fixture(tmp_path)
    patch = {
        "version": 1,
        "created": "2026-01-02T10:00:00Z",
        "author": "RC",
        "segments": {
            "s-fx-start-mid1-a": {
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
            }
        },
    }
    patch_path = tmp_path / "patch.json"
    common.write_json(patch_path, patch)

    before = (tmp_path / "segments.geojson").read_text(encoding="utf-8")
    rc = apply_patch.main(
        ["--patch", str(patch_path), "--data", str(tmp_path), "--schemas", str(SCHEMAS_DIR)]
    )
    assert rc != 0
    after = (tmp_path / "segments.geojson").read_text(encoding="utf-8")
    assert before == after  # refused: nothing written


def test_apply_patch_to_data_refuses_geometry_and_id_even_bypassing_schema():
    """Defense in depth: even a patch dict that skipped schema validation
    (e.g. constructed directly, as here) must be refused by the merge step
    itself if it tries to touch geometry or id."""
    nodes_fc = make_nodes()
    segments_fc = make_segments()
    pois_fc = make_pois()
    patch = {
        "segments": {
            "s-fx-start-mid1-a": {
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                "id": "s-hacked",
            }
        }
    }

    _, segments_new, _, _, errors = apply_patch.apply_patch_to_data(
        patch, nodes_fc, segments_fc, pois_fc
    )
    assert errors

    orig = next(f for f in segments_fc["features"] if f["properties"]["id"] == "s-fx-start-mid1-a")
    new = next(f for f in segments_new["features"] if f["properties"]["id"] == "s-fx-start-mid1-a")
    assert new["geometry"] == orig["geometry"]
    assert new["properties"]["id"] == "s-fx-start-mid1-a"


def test_apply_patch_refuses_unknown_segment_id(tmp_path):
    write_fixture(tmp_path)
    patch = {
        "version": 1,
        "created": "2026-01-02T10:00:00Z",
        "author": "RC",
        "segments": {"s-does-not-exist": {"status": "scouted-go"}},
    }
    patch_path = tmp_path / "patch.json"
    common.write_json(patch_path, patch)

    rc = apply_patch.main(
        ["--patch", str(patch_path), "--data", str(tmp_path), "--schemas", str(SCHEMAS_DIR)]
    )
    assert rc != 0
