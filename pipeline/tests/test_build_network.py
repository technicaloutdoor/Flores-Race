"""Tests for pipeline/build_network.py.

All synthetic: no dependency on the real Overture/DEM extracts. Run with:
    pytest pipeline/tests/test_build_network.py
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import pytest
from pyproj import Geod

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_network as bn  # noqa: E402

GEOD = Geod(ellps="WGS84")


# ---------------------------------------------------------------------------
# Segment -> edge cutting
# ---------------------------------------------------------------------------


def _seg_coords():
    # a bent line so length != straight-line distance, three roughly-equal-spaced
    # points plus a couple of shape vertices in between each.
    return [
        [120.00, -8.50],
        [120.01, -8.505],
        [120.02, -8.50],
        [120.03, -8.505],
        [120.04, -8.50],
    ]


def test_two_connectors_yield_one_edge_spanning_the_whole_segment():
    coords = _seg_coords()
    connectors = {"a": tuple(coords[0]), "b": tuple(coords[-1])}
    caveats = Counter()
    pieces = bn.cut_segment_edges("s1", coords, ["a", "b"], connectors, caveats)
    assert len(pieces) == 1
    u, v, piece = pieces[0]
    assert (u, v) == ("a", "b")
    whole_len = GEOD.geometry_length(__import__("shapely.geometry", fromlist=["LineString"]).LineString(coords))
    assert piece.length > 0
    assert GEOD.geometry_length(piece) == pytest.approx(whole_len, rel=1e-6)
    assert caveats["interior_connector_position_approximated"] == 0


def test_three_connectors_yield_two_edges_summing_to_the_whole():
    coords = _seg_coords()
    # middle connector sits exactly on the middle vertex
    connectors = {"a": tuple(coords[0]), "mid": tuple(coords[2]), "b": tuple(coords[-1])}
    caveats = Counter()
    pieces = bn.cut_segment_edges("s1", coords, ["a", "mid", "b"], connectors, caveats)
    assert len(pieces) == 2
    assert (pieces[0][0], pieces[0][1]) == ("a", "mid")
    assert (pieces[1][0], pieces[1][1]) == ("mid", "b")

    from shapely.geometry import LineString

    whole_len = GEOD.geometry_length(LineString(coords))
    piece_lens = [GEOD.geometry_length(p[2]) for p in pieces]
    assert sum(piece_lens) == pytest.approx(whole_len, rel=1e-6)
    # the shared endpoint really is shared
    assert list(pieces[0][2].coords)[-1] == pytest.approx(list(pieces[1][2].coords)[0])


def test_missing_endpoint_connector_falls_back_to_segment_endpoint_exactly():
    """A connector id absent from connectors.geojsonl entirely is still resolved exactly
    when it is the first or last id of the segment (no approximation needed)."""
    coords = _seg_coords()
    connectors = {"b": tuple(coords[-1])}  # "a" is missing entirely
    caveats = Counter()
    pieces = bn.cut_segment_edges("s1", coords, ["a", "b"], connectors, caveats)
    assert len(pieces) == 1
    u, v, piece = pieces[0]
    assert (u, v) == ("a", "b")
    assert list(piece.coords)[0] == pytest.approx(tuple(coords[0]))
    assert caveats["interior_connector_position_approximated"] == 0


def test_missing_interior_connector_is_approximated_and_reported():
    coords = _seg_coords()
    connectors = {"a": tuple(coords[0]), "b": tuple(coords[-1])}  # "mid" missing
    caveats = Counter()
    pieces = bn.cut_segment_edges("s1", coords, ["a", "mid", "b"], connectors, caveats)
    assert len(pieces) == 2
    assert caveats["interior_connector_position_approximated"] == 1


def test_single_connector_segment_yields_no_edges():
    coords = _seg_coords()
    caveats = Counter()
    assert bn.cut_segment_edges("s1", coords, ["a"], {"a": tuple(coords[0])}, caveats) == []


# ---------------------------------------------------------------------------
# Surface inference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls,road_surface,expected_surface,expected_source",
    [
        ("track", None, "unpaved", "inferred"),
        ("path", None, "unpaved", "inferred"),
        ("footway", None, "unpaved", "inferred"),
        ("trunk", None, "paved", "inferred"),
        ("primary", None, "paved", "inferred"),
        ("secondary", None, "paved", "inferred"),
        ("tertiary", None, "unknown_likely_paved", "inferred"),
        ("unclassified", None, "unknown", "inferred"),
        ("residential", None, "unknown", "inferred"),
        ("service", None, "unknown", "inferred"),
        ("unknown", None, "unknown", "inferred"),
        # a tag always wins, regardless of class
        ("track", "paved", "paved", "tag"),
        ("trunk", "gravel", "gravel", "tag"),
    ],
)
def test_infer_surface_table(cls, road_surface, expected_surface, expected_source):
    surface, source = bn.infer_surface(cls, road_surface)
    assert (surface, source) == (expected_surface, expected_source)


# ---------------------------------------------------------------------------
# One-way detection
# ---------------------------------------------------------------------------


def test_is_forward_only_whole_segment_backward_denied():
    ar = [{"access_type": "denied", "when": {"heading": "backward"}, "between": None}]
    assert bn.is_forward_only(ar) is True


def test_is_forward_only_false_for_partial_or_forward_or_allowed():
    assert bn.is_forward_only(None) is False
    assert bn.is_forward_only([{"access_type": "allowed", "when": {}, "between": None}]) is False
    assert bn.is_forward_only(
        [{"access_type": "denied", "when": {"heading": "backward"}, "between": [0.0, 0.3]}]
    ) is False
    assert bn.has_partial_restriction(
        [{"access_type": "denied", "when": {"heading": "backward"}, "between": [0.0, 0.3]}]
    ) is True


# ---------------------------------------------------------------------------
# Remoteness bucketing
# ---------------------------------------------------------------------------


def test_bucket_thresholds_match_brief_examples():
    import numpy as np

    thresholds = (1.0, 2.5, 5.0, 8.0)
    # both under a km -> level 1 (matches "town roads" example)
    assert bn._bucket(np.array([500.0]), thresholds)[0] == 1
    # comfortably past the last threshold -> level 5 ("nobody for a day" example)
    assert bn._bucket(np.array([9000.0]), thresholds)[0] == 5
    # each interior bucket
    assert bn._bucket(np.array([1500.0]), thresholds)[0] == 2  # 1 <= km < 2.5
    assert bn._bucket(np.array([3000.0]), thresholds)[0] == 3  # 2.5 <= km < 5
    assert bn._bucket(np.array([6000.0]), thresholds)[0] == 4  # 5 <= km < 8
    # boundary values fall into the higher (farther) bucket
    assert bn._bucket(np.array([1000.0]), thresholds)[0] == 2
    assert bn._bucket(np.array([8000.0]), thresholds)[0] == 5


def test_parse_thresholds_accepts_ascending_and_rejects_bad_input():
    assert bn.parse_thresholds("1,2.5,5,8") == (1.0, 2.5, 5.0, 8.0)
    with pytest.raises(Exception):
        bn.parse_thresholds("1,2,3")  # wrong count
    with pytest.raises(Exception):
        bn.parse_thresholds("5,1,2,8")  # not ascending


# ---------------------------------------------------------------------------
# DEM-derived edge stats (against a stub DEM, no real tiles needed)
# ---------------------------------------------------------------------------


class _StubDEM:
    """Exposes the same `sample_line` contract as pipeline.dem.DEM."""

    def __init__(self, elevations, step_m=50.0):
        self._elevations = elevations
        self._step_m = step_m

    def sample_line(self, coords, step_m=50):
        return [(i * self._step_m, e) for i, e in enumerate(self._elevations)]


def test_smooth3_leaves_short_arrays_unchanged_and_averages_longer_ones():
    assert bn._smooth3([]) == []
    assert bn._smooth3([5.0]) == [5.0]
    assert bn._smooth3([1.0, 2.0]) == [1.0, 2.0]
    out = bn._smooth3([0.0, 9.0, 0.0])
    assert out[0] == 0.0 and out[-1] == 0.0  # endpoints untouched
    assert out[1] == pytest.approx(3.0)  # (0+9+0)/3


def test_dem_edge_stats_ascent_descent_and_grade():
    # ascent uses a 3-sample moving average of elevation (see module docstring); derive
    # the expected numbers from that same smoothing so the test tracks behaviour, not a
    # hand-derived arithmetic coincidence.
    elevations = [0.0, 10.0, 5.0, 10.0, 2.0, 20.0]
    step_m = 50.0
    dem = _StubDEM(elevations, step_m=step_m)
    asc, desc, grade, mean_elev = bn.dem_edge_stats(dem, [(0, 0), (0, 0)], step_m=step_m)

    smoothed = bn._smooth3(elevations)
    exp_asc = sum(max(0.0, smoothed[i] - smoothed[i - 1]) for i in range(1, len(smoothed)))
    exp_desc = sum(max(0.0, smoothed[i - 1] - smoothed[i]) for i in range(1, len(smoothed)))
    exp_grade = max(abs(smoothed[i] - smoothed[i - 1]) / step_m * 100.0 for i in range(1, len(smoothed)))

    assert asc == pytest.approx(exp_asc)
    assert desc == pytest.approx(exp_desc)
    assert grade == pytest.approx(exp_grade)
    assert exp_asc > 0 and exp_desc > 0  # sanity: the fixture actually has both
    assert mean_elev == pytest.approx(sum(elevations) / len(elevations))


def test_dem_edge_stats_clamps_negative_bathymetry_to_zero():
    dem = _StubDEM([-5, -2, 0, 3])
    asc, desc, grade, mean_elev = bn.dem_edge_stats(dem, [(0, 0), (0, 0)], step_m=50.0)
    assert mean_elev >= 0
    # all clamped to 0 except the last -> mean is 3/4
    assert mean_elev == pytest.approx(3 / 4)


def test_dem_edge_stats_handles_none_samples():
    dem = _StubDEM([0, None, 10])
    asc, desc, grade, mean_elev = bn.dem_edge_stats(dem, [(0, 0), (0, 0)], step_m=50.0)
    assert mean_elev >= 0  # None treated as 0, must not raise


# ---------------------------------------------------------------------------
# graph.json.gz round trip through load_graph()
# ---------------------------------------------------------------------------


def _make_edge(u, v, seg, i, cls="tertiary", length=1000.0, asc=10.0, desc=5.0, oneway=False):
    return bn.Edge(
        u=u, v=v, seg=seg, i=i, cls=cls, sub=None, surf="paved", surf_src="tag",
        len_m=length, asc=asc, desc=desc, grade=1.0, elev=100.0, rem=2, oneway=oneway,
        coords=[(120.0, -8.5), (120.01, -8.5)],
    )


def test_write_graph_and_load_graph_round_trip(tmp_path):
    nodes = {"a": (120.0, -8.5), "b": (120.01, -8.5), "c": (120.02, -8.5)}
    edges = [
        _make_edge("a", "b", "seg1", 0, oneway=False),
        _make_edge("b", "c", "seg2", 0, cls="track", oneway=True),
    ]
    bn.write_graph(tmp_path, nodes, edges)
    g = bn.load_graph(tmp_path / "graph.json.gz")

    assert g.number_of_nodes() == 3
    assert g.nodes["a"]["pos"] == (120.0, -8.5)
    # bidirectional edge: both directions present
    assert g.has_edge("a", "b") and g.has_edge("b", "a")
    # oneway edge on a non-track/path class would be one direction only; here it is
    # "track", so build_network's own rule (ignore oneway for track/path) means
    # load_graph must still see the oneway flag honoured only for driveable classes.
    assert g.has_edge("b", "c") and g.has_edge("c", "b")  # track ignores oneway

    d = g.get_edge_data("a", "b")[0]
    assert d["length_m"] == 1000.0
    assert d["seg"] == "seg1"


def test_load_graph_honours_oneway_for_driveable_classes(tmp_path):
    nodes = {"a": (120.0, -8.5), "b": (120.01, -8.5)}
    edges = [_make_edge("a", "b", "seg1", 0, cls="tertiary", oneway=True)]
    bn.write_graph(tmp_path, nodes, edges)
    g = bn.load_graph(tmp_path / "graph.json.gz")
    assert g.has_edge("a", "b")
    assert not g.has_edge("b", "a")


# ---------------------------------------------------------------------------
# Connectivity report
# ---------------------------------------------------------------------------


def test_connectivity_report_finds_two_components():
    nodes = {"a": (120.0, -8.5), "b": (120.01, -8.5), "c": (121.0, -8.6), "d": (121.01, -8.6)}
    edges = [
        _make_edge("a", "b", "seg1", 0, length=1000.0),
        _make_edge("c", "d", "seg2", 0, length=500.0),
    ]
    report = bn.connectivity_report(nodes, edges)
    assert report["n_components"] == 2
    assert report["largest_component_n_nodes"] == 2
    assert report["largest_component_km"] == pytest.approx(1.0)
    assert len(report["largest_disconnected_components"]) == 1
    assert report["largest_disconnected_components"][0]["total_km"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# End-to-end: tiny synthetic Overture extract on disk
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_build_edges_end_to_end_on_synthetic_extract(tmp_path):
    overture_dir = tmp_path / "overture"
    overture_dir.mkdir()

    coords = _seg_coords()
    segment = {
        "type": "Feature", "id": "seg1",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "id": "seg1", "subtype": "road", "class": "track", "subclass": None,
            "name": "Test track", "road_surface": None, "road_flags": None,
            "access_restrictions": None, "connector_ids": ["a", "b"], "sources": [],
        },
    }
    ferry = {
        "type": "Feature", "id": "ferry1",
        "geometry": {"type": "LineString", "coordinates": [[120.0, -8.5], [121.0, -8.6]]},
        "properties": {
            "id": "ferry1", "subtype": "water", "class": None, "subclass": None,
            "name": "Ferry", "road_surface": None, "road_flags": None,
            "access_restrictions": None, "connector_ids": ["a", "z"], "sources": [],
        },
    }
    _write_jsonl(overture_dir / "segment.geojsonl", [segment, ferry])
    _write_jsonl(overture_dir / "connector.geojsonl", [
        {"type": "Feature", "id": "a", "geometry": {"type": "Point", "coordinates": list(coords[0])},
         "properties": {"id": "a"}},
        {"type": "Feature", "id": "b", "geometry": {"type": "Point", "coordinates": list(coords[-1])},
         "properties": {"id": "b"}},
    ])
    _write_jsonl(overture_dir / "place.geojsonl", [])

    caveats = Counter()
    dem = _StubDEM([10, 20, 15])
    nodes, edges, seg_meta, tallies = bn.build_edges(overture_dir, dem, 50.0, caveats)

    assert caveats["dropped_ferry_segments"] == 1
    assert len(edges) == 1
    assert edges[0].seg == "seg1"
    assert set(nodes) == {"a", "b"}
    assert seg_meta["seg1"]["class"] == "track"
    assert seg_meta["seg1"]["surface"] == "unpaved"
    assert seg_meta["seg1"]["surface_source"] == "inferred"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
