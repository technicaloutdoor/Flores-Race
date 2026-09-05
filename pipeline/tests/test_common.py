"""Tests for the small pure helpers in common.py."""
import math

import common


def test_round6_normalises_negative_zero():
    assert common.round6(-0.0000001) == 0.0
    assert common.round6(1.1234565) == 1.123456 or common.round6(1.1234565) == 1.123457


def test_write_geojson_sorts_by_id_and_rounds(tmp_path):
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [120.123456789, -8.1]},
                "properties": {"id": "n-zzz"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [120.0, -8.0]},
                "properties": {"id": "n-aaa"},
            },
        ],
    }
    path = tmp_path / "out.geojson"
    common.write_geojson(path, fc)

    written = common.read_geojson(path)
    ids = [f["properties"]["id"] for f in written["features"]]
    assert ids == ["n-aaa", "n-zzz"]
    lon = written["features"][1]["geometry"]["coordinates"][0]
    assert lon == round(120.123456789, 6)

    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "  " in text  # 2-space indent


def test_geodesic_length_roughly_matches_known_distance():
    # Roughly 1 degree of longitude at the equator ~ 111.3 km.
    coords = [[0.0, 0.0], [1.0, 0.0]]
    km = common.geodesic_length_km(coords)
    assert 110.0 < km < 112.0


def test_haversine_matches_geodesic_within_tolerance():
    lon1, lat1 = 120.40, -8.58
    lon2, lat2 = 120.45, -8.60
    hav = common.haversine_m(lon1, lat1, lon2, lat2)
    geo = common.geodesic_length_m([[lon1, lat1], [lon2, lat2]])
    assert abs(hav - geo) < 50  # metres, over a ~5-6 km hop


def test_clamp_elevation():
    assert common.clamp_elevation(None) == 0.0
    assert common.clamp_elevation(-5.0) == 0.0
    assert common.clamp_elevation(123.4) == 123.4


def test_douglas_peucker_keeps_endpoints_and_drops_collinear_points():
    points = [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]]  # perfectly straight
    simplified = common.douglas_peucker(points, epsilon=0.01)
    assert simplified == [[0, 0], [4, 0]]


def test_douglas_peucker_keeps_a_real_peak():
    points = [[0, 0], [1, 0], [2, 10], [3, 0], [4, 0]]
    simplified = common.douglas_peucker(points, epsilon=0.5)
    assert [2, 10] in simplified
    assert simplified[0] == [0, 0]
    assert simplified[-1] == [4, 0]


def test_decimate_profile_respects_max_points():
    points = [[i * 0.05, math.sin(i / 5.0) * 100] for i in range(2000)]
    decimated = common.decimate_profile(points, max_points=400)
    assert len(decimated) <= 400
    assert decimated[0] == list(points[0])
    assert decimated[-1] == list(points[-1])


def test_simplify_geometry_reduces_points_on_a_dense_nearly_straight_line():
    coords = [[120.0 + i * 0.0001, -8.0 + i * 0.00005] for i in range(50)]
    geometry = {"type": "LineString", "coordinates": coords}
    simplified = common.simplify_geometry(geometry, tolerance_m=50.0)
    assert len(simplified["coordinates"]) < len(coords)
    assert simplified["coordinates"][0] == common.round_coords(coords)[0]
    assert simplified["coordinates"][-1] == common.round_coords(coords)[-1]


def test_simplify_geometry_zero_tolerance_only_rounds():
    geometry = {"type": "LineString", "coordinates": [[120.123456789, -8.1], [120.2, -8.2]]}
    simplified = common.simplify_geometry(geometry, tolerance_m=0)
    assert simplified["coordinates"] == [[120.123457, -8.1], [120.2, -8.2]]


def test_load_regencies_reduces_properties(tmp_path):
    raw = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[120.0, -8.0], [120.1, -8.0], [120.1, -8.1], [120.0, -8.0]]]},
                "properties": {"shapeName": "Ende", "shapeISO": "", "shapeID": "abc123", "shapeGroup": "IDN"},
            }
        ],
    }
    path = tmp_path / "raw_regencies.geojson"
    common.write_json(path, raw)

    normalised = common.load_regencies(path)
    props = normalised["features"][0]["properties"]
    assert set(props.keys()) == {"id", "name"}
    assert props["name"] == "Ende"
    assert props["id"] == "reg-ende"
