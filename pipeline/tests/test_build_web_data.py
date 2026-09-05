"""End-to-end test of build_web_data.py against the fixture. Uses the real
DEM and regency data when available (see conftest.py); skipped otherwise."""
import gzip
import json
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


# ---------------------------------------------------------------------------
# --network-web: build_network.py's network_web export
# ---------------------------------------------------------------------------


def _dense_network_web_line(lon0=120.47, lat0=-8.61, n=30, step_deg=0.00002, wiggle_deg=0.00002):
    """A LineString whose vertices sit only a few metres apart with a small
    zigzag (so it is not perfectly straight -- Douglas-Peucker has real
    corners to decide about) -- roughly 60-90 m long, well under
    NETWORK_WEB_TOLERANCE_M's default spacing."""
    coords = []
    for i in range(n):
        lat = lat0 + (wiggle_deg if i % 2 == 0 else -wiggle_deg)
        coords.append([round(lon0 + i * step_deg, 6), round(lat, 6)])
    return coords


def _coarse_network_web_line():
    """A LineString whose two vertices are already far apart (~1 km) -- well
    over NETWORK_WEB_TOLERANCE_M, so the file this belongs to should count
    as "already coarser" and be left alone rather than re-simplified."""
    return [[120.40, -8.58], [120.409, -8.589]]


def _network_web_fc(coords_list):
    features = []
    for i, coords in enumerate(coords_list):
        features.append(
            {
                "type": "Feature",
                "id": f"seg-{i}",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "id": f"seg-{i}",
                    "class": "track",
                    "subclass": None,
                    "surface": "unpaved",
                    "surface_source": "tag",
                    "name": None,
                    "remoteness": 3,
                    "km": round(common.geodesic_length_m(coords) / 1000.0, 3),
                    # Not in NETWORK_WEB_KEPT_PROPS -- must be dropped.
                    "flag_tags": ["steps"],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def test_mean_vertex_spacing_and_already_coarser_than():
    dense_fc = _network_web_fc([_dense_network_web_line()])
    coarse_fc = _network_web_fc([_coarse_network_web_line()])

    dense_spacing = build_web_data.mean_vertex_spacing_m(dense_fc)
    coarse_spacing = build_web_data.mean_vertex_spacing_m(coarse_fc)
    assert dense_spacing < build_web_data.NETWORK_WEB_TOLERANCE_M
    assert coarse_spacing > build_web_data.NETWORK_WEB_TOLERANCE_M

    assert build_web_data.is_already_coarser_than(dense_fc, build_web_data.NETWORK_WEB_TOLERANCE_M) is False
    assert build_web_data.is_already_coarser_than(coarse_fc, build_web_data.NETWORK_WEB_TOLERANCE_M) is True


def test_build_network_bundle_from_network_web_keeps_properties_and_simplifies_dense_geometry():
    fc = _network_web_fc([_dense_network_web_line()])
    original_n_points = len(fc["features"][0]["geometry"]["coordinates"])

    out, already_coarser = build_web_data.build_network_bundle_from_network_web(fc)

    assert already_coarser is False
    assert len(out["features"]) == 1
    feat = out["features"][0]
    assert set(feat["properties"]) == set(build_web_data.NETWORK_WEB_KEPT_PROPS)
    assert feat["properties"]["surface_source"] == "tag"  # kept, unlike the overture-dir path
    assert feat["properties"]["id"] == "seg-0"
    # Dense + nearly-straight geometry at an 8 m tolerance collapses to
    # fewer points than the original (Douglas-Peucker actually ran).
    assert len(feat["geometry"]["coordinates"]) < original_n_points
    assert len(feat["geometry"]["coordinates"]) >= 2


def test_build_network_bundle_from_network_web_skips_simplify_when_already_coarse():
    fc = _network_web_fc([_coarse_network_web_line()])
    original_coords = fc["features"][0]["geometry"]["coordinates"]

    out, already_coarser = build_web_data.build_network_bundle_from_network_web(fc)

    assert already_coarser is True
    got_coords = out["features"][0]["geometry"]["coordinates"]
    assert len(got_coords) == len(original_coords)  # not re-simplified, just rounded


def test_read_network_web_file_handles_gzip_and_plain(tmp_path):
    fc = _network_web_fc([_dense_network_web_line()])

    plain_path = tmp_path / "network_web.geojson"
    plain_path.write_text(json.dumps(fc), encoding="utf-8")
    gz_path = tmp_path / "network_web.geojson.gz"
    with gzip.open(gz_path, "wt", encoding="utf-8") as f:
        f.write(json.dumps(fc))
    # Also exercise "gzip content regardless of filename" -- rename the gz
    # file so the suffix alone can't be relied on.
    renamed_gz_path = tmp_path / "network_web_no_gz_suffix.geojson"
    renamed_gz_path.write_bytes(gz_path.read_bytes())

    assert build_web_data.read_network_web_file(plain_path) == fc
    assert build_web_data.read_network_web_file(gz_path) == fc
    assert build_web_data.read_network_web_file(renamed_gz_path) == fc


def test_build_web_data_uses_network_web_over_overture_dir(tmp_path, dem_dir, regencies_path):
    data_dir = tmp_path / "data"
    write_fixture(data_dir)
    out_dir = tmp_path / "out"

    network_web_path = tmp_path / "network_web.geojson.gz"
    network_web_fc = _network_web_fc([_dense_network_web_line(), _coarse_network_web_line()])
    with gzip.open(network_web_path, "wt", encoding="utf-8") as f:
        f.write(json.dumps(network_web_fc))

    # An --overture-dir is also given, but --network-web must win.
    overture_dir = tmp_path / "overture"
    overture_dir.mkdir()
    (overture_dir / "segment.geojsonl").write_text(
        json.dumps(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": _coarse_network_web_line()},
                "properties": {"id": "overture-seg", "subtype": "road", "class": "track"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rc = build_web_data.main(
        [
            "--data", str(data_dir),
            "--schemas", str(SCHEMAS_DIR),
            "--dem-dir", dem_dir,
            "--regencies", regencies_path,
            "--network-web", str(network_web_path),
            "--overture-dir", str(overture_dir),
            "--out", str(out_dir),
        ]
    )
    assert rc == 0

    network_gz = out_dir / "network.geojson.gz"
    assert network_gz.exists()
    with gzip.open(network_gz, "rt", encoding="utf-8") as f:
        network_fc = json.load(f)
    assert len(network_fc["features"]) == 2
    ids = {f["properties"]["id"] for f in network_fc["features"]}
    assert ids == {"seg-0", "seg-1"}
    # surface_source only exists on the network-web path, not the
    # overture-dir reduction -- proof this build used --network-web.
    assert all("surface_source" in f["properties"] for f in network_fc["features"])

    meta = common.read_json(out_dir / "meta.json")
    assert meta["network_source"] == "network-web"
    assert meta["counts"]["network_features"] == 2


def test_build_web_data_falls_back_to_overture_dir_when_network_web_missing(
    tmp_path, dem_dir, regencies_path
):
    data_dir = tmp_path / "data"
    write_fixture(data_dir)
    out_dir = tmp_path / "out"

    overture_dir = tmp_path / "overture"
    overture_dir.mkdir()
    (overture_dir / "segment.geojsonl").write_text(
        json.dumps(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": _coarse_network_web_line()},
                "properties": {
                    "id": "overture-seg", "subtype": "road", "class": "track",
                    "road_surface": "dirt", "name": "Test track",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rc = build_web_data.main(
        [
            "--data", str(data_dir),
            "--schemas", str(SCHEMAS_DIR),
            "--dem-dir", dem_dir,
            "--regencies", regencies_path,
            "--network-web", str(tmp_path / "does-not-exist.geojson.gz"),
            "--overture-dir", str(overture_dir),
            "--out", str(out_dir),
        ]
    )
    assert rc == 0

    network_gz = out_dir / "network.geojson.gz"
    with gzip.open(network_gz, "rt", encoding="utf-8") as f:
        network_fc = json.load(f)
    assert len(network_fc["features"]) == 1
    # The overture-dir reduction never carries surface_source/id/km.
    assert "surface_source" not in network_fc["features"][0]["properties"]
    assert network_fc["features"][0]["properties"]["surface"] == "dirt"

    meta = common.read_json(out_dir / "meta.json")
    assert meta["network_source"] == "overture-dir"
    assert meta["counts"]["network_features"] == 1
