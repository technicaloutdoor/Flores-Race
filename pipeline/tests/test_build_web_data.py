"""End-to-end test of build_web_data.py against the fixture. Uses the real
DEM and regency data when available (see conftest.py); skipped otherwise."""
from pathlib import Path

import build_web_data
import common
from fixtures import write_fixture

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"

EXPECTED_FILES = [
    "nodes.geojson",
    "pois.geojson",
    "segments.geojson",
    "regencies.geojson",
    "sections.json",
    "routes.json",
    "profiles.json",
    "meta.json",
]


def test_build_web_data_end_to_end(tmp_path, dem_dir, regencies_path):
    data_dir = tmp_path / "data"
    write_fixture(data_dir)
    out_dir = tmp_path / "out"

    rc = build_web_data.main(
        [
            "--data",
            str(data_dir),
            "--schemas",
            str(SCHEMAS_DIR),
            "--dem-dir",
            dem_dir,
            "--regencies",
            regencies_path,
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 0

    for name in EXPECTED_FILES:
        assert (out_dir / name).exists(), f"missing {name}"
    assert not (out_dir / "network.geojson.gz").exists()  # no --overture-dir given

    meta = common.read_json(out_dir / "meta.json")
    assert meta["counts"] == {
        "nodes": 4,
        "pois": 2,
        "segments": 3,
        "sections": 1,
        "routes": 1,
        "regencies": 8,
    }
    assert meta["public_build"] is False
    assert "generated_at" in meta
    assert isinstance(meta["sources"], list) and meta["sources"]
    # web/src/data/store.ts's MetaJSON type requires `build_time` and `attribution` -- without
    # these the web app's attribution control never shows the SRTM/geoBoundaries/Overture credit
    # lines it is supposed to (ARCHITECTURE.md §9).
    assert meta["build_time"] == meta["generated_at"]
    assert isinstance(meta["attribution"], list) and meta["attribution"]
    for source in meta["sources"]:
        assert f'{source["name"]} ({source["license"]})' in meta["attribution"]

    nodes_fc = common.read_geojson(out_dir / "nodes.geojson")
    ruteng = next(f for f in nodes_fc["features"] if f["properties"]["id"] == "n-fx-mid2")
    assert 900 < ruteng["properties"]["elevation_m"] < 1400  # real DEM, ~ Ruteng

    segments_fc = common.read_geojson(out_dir / "segments.geojson")
    for feat in segments_fc["features"]:
        assert "stats" in feat["properties"]

    routes = common.read_json(out_dir / "routes.json")
    assert routes[0]["stats"]["length_km"] > 0


def test_build_web_data_public_build_drops_non_public_features(tmp_path, dem_dir, regencies_path):
    data_dir = tmp_path / "data"
    write_fixture(data_dir)
    out_dir = tmp_path / "out"

    rc = build_web_data.main(
        [
            "--data",
            str(data_dir),
            "--schemas",
            str(SCHEMAS_DIR),
            "--dem-dir",
            dem_dir,
            "--regencies",
            regencies_path,
            "--out",
            str(out_dir),
            "--public-build",
        ]
    )
    assert rc == 0

    # Every fixture feature has public: false and no route audience of
    # "public" -- a public build of this fixture should keep none of them.
    nodes_fc = common.read_geojson(out_dir / "nodes.geojson")
    assert nodes_fc["features"] == []
    routes = common.read_json(out_dir / "routes.json")
    assert routes == []

    meta = common.read_json(out_dir / "meta.json")
    assert meta["public_build"] is True
    assert meta["counts"]["nodes"] == 0
    assert meta["counts"]["routes"] == 0
    # Regencies carry no public flag -- unaffected by --public-build.
    assert meta["counts"]["regencies"] == 8


def test_build_web_data_aborts_on_invalid_data(tmp_path, dem_dir, regencies_path):
    data_dir = tmp_path / "data"
    write_fixture(data_dir, broken_route=True)
    out_dir = tmp_path / "out"

    rc = build_web_data.main(
        [
            "--data",
            str(data_dir),
            "--schemas",
            str(SCHEMAS_DIR),
            "--dem-dir",
            dem_dir,
            "--regencies",
            regencies_path,
            "--out",
            str(out_dir),
        ]
    )
    assert rc != 0
    assert not out_dir.exists() or list(out_dir.iterdir()) == []
