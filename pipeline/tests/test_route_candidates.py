"""Tests for route_candidates.py.

Builds tiny synthetic `graph.json.gz` fixtures by hand, in the exact on-disk shape
`build_network.write_graph` produces (nodes: {id: [lon, lat]}; edges: list of dicts with
keys u, v, seg, i, cls, sub, surf, surf_src, len, asc, desc, grade, elev, rem, oneway,
coords) -- confirmed by reading `build_network.py`'s `write_graph`/`load_graph` -- so these
tests only depend on `build_network.load_graph`, not on any of its internals.
"""
from __future__ import annotations

import gzip
import json

import pytest

import build_network as bn
import route_candidates as rc


# ---------------------------------------------------------------------------
# Synthetic graph fixture helpers
# ---------------------------------------------------------------------------


def _edge(u, v, seg, i, cls, surf="unpaved", surf_src="inferred", length=1000.0,
          asc=10.0, desc=5.0, grade=2.0, elev=100.0, rem=3, oneway=False, coords=None):
    if coords is None:
        # a straight, made-up line; geometry correctness is checked separately
        coords = [[0.0, 0.0], [0.0, 0.0]]
    return {
        "u": u, "v": v, "seg": seg, "i": i, "cls": cls, "sub": None,
        "surf": surf, "surf_src": surf_src, "len": length, "asc": asc, "desc": desc,
        "grade": grade, "elev": elev, "rem": rem, "oneway": oneway, "coords": coords,
    }


def write_graph_gz(path, nodes: dict, edges: list[dict]) -> None:
    """Write a graph.json.gz exactly as build_network.write_graph does."""
    doc = {"nodes": {nid: list(xy) for nid, xy in nodes.items()}, "edges": edges}
    raw = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(raw)


def _straight_coords(p1, p2, n=2):
    return [[p1[0] + (p2[0] - p1[0]) * i / (n - 1), p1[1] + (p2[1] - p1[1]) * i / (n - 1)] for i in range(n)]


@pytest.fixture()
def branchy_graph(tmp_path):
    """Two edge-disjoint routes between n1 and n4:

    - "trunk" (n1-n2-n3-n4): paved, remoteness 1, short (3.0 km total).
    - "track" (n1-n5-n6-n4): unpaved, remoteness 5, longer (4.5 km total).

    Chosen so 'remote'/'rideable' should both prefer the track route (heavily discounted
    by class + remoteness) while 'direct' prefers the shorter trunk route despite its
    small safety penalty -- exercising both the alternatives search and cross-profile
    dedupe against a real load_graph() round trip.

    Also includes a second, edge-disjoint trunk-class path (n1-n2b-n3b-n4, same length as
    the first trunk path) so the 'direct' profile has a genuine, accept-able alternative
    once the first trunk path's edges are penalised.
    """
    nodes = {
        "n1": (120.000, -8.500),
        "n2": (120.010, -8.500),
        "n3": (120.020, -8.500),
        "n4": (120.030, -8.500),
        "n5": (120.010, -8.510),
        "n6": (120.020, -8.510),
        "n2b": (120.010, -8.490),
        "n3b": (120.020, -8.490),
    }

    def leg(a, b, seg, i, **kw):
        return _edge(a, b, seg, i, coords=_straight_coords(nodes[a], nodes[b]), **kw)

    edges = [
        # trunk route A: 3 x 1000 m, paved, remoteness 1
        leg("n1", "n2", "trunkA", 0, cls="trunk", surf="paved", length=1000.0, rem=1, grade=1.0),
        leg("n2", "n3", "trunkA", 1, cls="trunk", surf="paved", length=1000.0, rem=1, grade=1.0),
        leg("n3", "n4", "trunkA", 2, cls="trunk", surf="paved", length=1000.0, rem=1, grade=1.0),
        # trunk route B (parallel, edge-disjoint, same total length): alternative for 'direct'
        leg("n1", "n2b", "trunkB", 0, cls="trunk", surf="paved", length=1000.0, rem=1, grade=1.0),
        leg("n2b", "n3b", "trunkB", 1, cls="trunk", surf="paved", length=1000.0, rem=1, grade=1.0),
        leg("n3b", "n4", "trunkB", 2, cls="trunk", surf="paved", length=1000.0, rem=1, grade=1.0),
        # track route: 3 x 1500 m, unpaved, remoteness 5 (longer, but cheap for remote/rideable)
        leg("n1", "n5", "track", 0, cls="track", surf="unpaved", length=1500.0, rem=5, grade=3.0),
        leg("n5", "n6", "track", 1, cls="track", surf="unpaved", length=1500.0, rem=5, grade=3.0),
        leg("n6", "n4", "track", 2, cls="track", surf="unpaved", length=1500.0, rem=5, grade=3.0),
    ]
    path = tmp_path / "graph.json.gz"
    write_graph_gz(path, nodes, edges)
    return bn.load_graph(path), nodes


@pytest.fixture()
def G(branchy_graph):
    g, _nodes = branchy_graph
    rc.precompute_costs(g)
    return g


# ---------------------------------------------------------------------------
# Cost profiles
# ---------------------------------------------------------------------------


def test_edge_multiplier_remote_prefers_track_over_trunk():
    trunk = {"cls": "trunk", "surface": "paved", "remoteness": 1, "max_grade_pct": 1.0}
    track = {"cls": "track", "surface": "unpaved", "remoteness": 5, "max_grade_pct": 3.0}
    assert rc.edge_multiplier("remote", track) < rc.edge_multiplier("remote", trunk)


def test_edge_multiplier_direct_only_penalises_trunk_safety():
    trunk = {"cls": "trunk", "surface": "paved", "remoteness": 1, "max_grade_pct": 1.0}
    track = {"cls": "track", "surface": "unpaved", "remoteness": 5, "max_grade_pct": 3.0}
    assert rc.edge_multiplier("direct", trunk) == pytest.approx(1.2)
    assert rc.edge_multiplier("direct", track) == pytest.approx(1.0)


def test_edge_multiplier_rideable_penalises_footway_and_steps_more_than_track():
    footway = {"cls": "footway", "surface": "unpaved", "remoteness": 3, "max_grade_pct": 1.0}
    steps = {"cls": "steps", "surface": "unpaved", "remoteness": 3, "max_grade_pct": 1.0}
    track = {"cls": "track", "surface": "unpaved", "remoteness": 3, "max_grade_pct": 1.0}
    assert rc.edge_multiplier("rideable", track) < rc.edge_multiplier("rideable", footway)
    assert rc.edge_multiplier("rideable", footway) < rc.edge_multiplier("rideable", steps)


def test_grade_factor_penalises_steep_edges():
    flat = {"cls": "track", "surface": "unpaved", "remoteness": 3, "max_grade_pct": 2.0}
    steep = dict(flat, max_grade_pct=25.0)
    assert rc.edge_multiplier("remote", steep) > rc.edge_multiplier("remote", flat)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def test_slugify():
    assert rc.slugify("Labuan Bajo") == "labuan-bajo"
    assert rc.slugify("  Sano Nggoang!! ") == "sano-nggoang"
    assert rc.slugify("") == "anchor"


def test_parse_anchors_arg_with_and_without_labels():
    out = rc.parse_anchors_arg("119.888,-8.487,Labuan Bajo; 120.056,-8.716")
    assert out[0] == ("Labuan Bajo", 119.888, -8.487)
    assert out[1][0] == "anchor2"
    assert out[1][1:] == (120.056, -8.716)


def test_jaccard_basic():
    assert rc.jaccard(set(), set()) == 1.0
    assert rc.jaccard({1, 2}, {1, 2}) == 1.0
    assert rc.jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)
    assert rc.jaccard({1}, {2}) == 0.0


def test_next_letters_starts_at_a_when_nothing_used():
    assert rc.next_letters(set(), 3) == ["A", "B", "C"]


def test_next_letters_continues_after_existing():
    assert rc.next_letters({"A", "B"}, 2) == ["C", "D"]
    assert rc.next_letters({"D"}, 1) == ["E"]


def test_next_letters_raises_rather_than_overflow_past_z():
    # 25 variants already used (A-Y): only one letter (Z) is left.
    used = {chr(ord("A") + i) for i in range(25)}
    assert rc.next_letters(used, 1) == ["Z"]
    with pytest.raises(ValueError):
        rc.next_letters(used, 2)  # would need Z and beyond
    with pytest.raises(ValueError):
        rc.next_letters({"Z"}, 1)  # nothing left after Z


# ---------------------------------------------------------------------------
# Anchor snapping
# ---------------------------------------------------------------------------


def test_snap_anchors_within_radius(G):
    a = rc.Anchor(label="near n1", node_id="n-start", lon=120.0001, lat=-8.5001)
    rc.snap_anchors(G, [a], snap_km=2.5)
    assert a.graph_node == "n1"
    assert a.snap_km < 0.1


def test_snap_anchors_off_network_beyond_radius(G):
    a = rc.Anchor(label="far away", node_id="n-far", lon=125.0, lat=-9.5)
    rc.snap_anchors(G, [a], snap_km=2.5)
    assert a.graph_node is None
    assert a.snap_km > 2.5


# ---------------------------------------------------------------------------
# Routing: shortest path + alternatives
# ---------------------------------------------------------------------------


def test_remote_and_rideable_prefer_the_track_route(G):
    cands = rc.find_profile_candidates(G, "n1", "n4", "remote", k=1)
    assert len(cands) == 1
    assert cands[0].edge_id_set() == {("track", 0), ("track", 1), ("track", 2)}

    cands = rc.find_profile_candidates(G, "n1", "n4", "rideable", k=1)
    assert cands[0].edge_id_set() == {("track", 0), ("track", 1), ("track", 2)}


def test_direct_prefers_the_shorter_trunk_route(G):
    cands = rc.find_profile_candidates(G, "n1", "n4", "direct", k=1)
    assert cands[0].edge_id_set() == {("trunkA", 0), ("trunkA", 1), ("trunkA", 2)}


def test_direct_finds_a_disjoint_alternative_within_k(G):
    cands = rc.find_profile_candidates(G, "n1", "n4", "direct", k=2)
    assert len(cands) == 2
    sets = [c.edge_id_set() for c in cands]
    # the two trunk routes are edge-disjoint and equal length -> low overlap, both <=1.6x
    assert rc.jaccard(sets[0], sets[1]) < 0.6
    assert {("trunkA", 0), ("trunkA", 1), ("trunkA", 2)} in sets
    assert {("trunkB", 0), ("trunkB", 1), ("trunkB", 2)} in sets


def test_no_path_returns_empty_list(tmp_path):
    nodes = {"a": (120.0, -8.5), "b": (121.0, -8.5)}
    edges = []  # a and b are not connected at all
    path = tmp_path / "g.json.gz"
    write_graph_gz(path, nodes, edges)
    g = bn.load_graph(path)
    rc.precompute_costs(g)
    assert rc.find_profile_candidates(g, "a", "b", "remote", k=2) == []


def test_same_start_and_end_is_a_degenerate_zero_length_candidate(G):
    cands = rc.find_profile_candidates(G, "n1", "n1", "remote", k=1)
    assert len(cands) == 1
    assert cands[0].length_m == 0.0
    assert cands[0].edges == []


# ---------------------------------------------------------------------------
# Cross-profile dedupe
# ---------------------------------------------------------------------------


def test_dedupe_merges_identical_candidates_keeping_most_remote_profile(G):
    raw = []
    for profile in ("remote", "rideable", "direct"):
        raw.extend(rc.find_profile_candidates(G, "n1", "n4", profile, k=1))
    clusters = rc.dedupe_candidates(raw)

    # remote & rideable both chose the track route -> one cluster with both profiles;
    # direct chose the (edge-disjoint) trunk route -> a second, separate cluster.
    assert len(clusters) == 2
    track_cluster = next(c for c in clusters if c.representative.profile in ("remote", "rideable"))
    assert track_cluster.profiles == {"remote", "rideable"}
    assert track_cluster.representative.profile == "remote"  # more-remote profile wins
    trunk_cluster = next(c for c in clusters if c is not track_cluster)
    assert trunk_cluster.profiles == {"direct"}


def test_dedupe_keeps_distinct_non_overlapping_candidates_separate():
    a = rc.RawCandidate(
        profile="remote", path=["x", "y"],
        edges=[("x", "y", 0, {"seg": "s1", "piece": 0})], length_m=100.0,
    )
    b = rc.RawCandidate(
        profile="direct", path=["x", "z"],
        edges=[("x", "z", 0, {"seg": "s2", "piece": 0})], length_m=100.0,
    )
    clusters = rc.dedupe_candidates([a, b])
    assert len(clusters) == 2


def test_dedupe_merges_above_threshold_but_not_below():
    # 4-edge and 5-edge candidates sharing 4 edges: jaccard = 4/5 = 0.8 -> below the 0.85
    # merge threshold, so these must stay distinct candidates.
    shared = [("u", "v", 0, {"seg": f"s{i}", "piece": 0}) for i in range(4)]
    a = rc.RawCandidate(profile="remote", path=[], edges=shared, length_m=400.0)
    b = rc.RawCandidate(
        profile="rideable", path=[], edges=shared + [("v", "w", 0, {"seg": "s4", "piece": 0})],
        length_m=500.0,
    )
    clusters = rc.dedupe_candidates([a, b])
    assert len(clusters) == 2

    # now 9 shared edges + 1 different: jaccard = 9/10 = 0.9 -> merges.
    shared9 = [("u", "v", 0, {"seg": f"t{i}", "piece": 0}) for i in range(9)]
    c = rc.RawCandidate(profile="remote", path=[], edges=shared9, length_m=900.0)
    d = rc.RawCandidate(
        profile="direct", path=[], edges=shared9 + [("v", "w", 0, {"seg": "t9", "piece": 0})],
        length_m=1000.0,
    )
    clusters2 = rc.dedupe_candidates([c, d])
    assert len(clusters2) == 1
    assert clusters2[0].profiles == {"remote", "direct"}


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------


def test_est_hab_km_full_for_steep_path_half_for_gentle():
    edges = [
        ("a", "b", 0, {"length_m": 1000.0, "cls": "path", "max_grade_pct": 20.0}),
        ("b", "c", 0, {"length_m": 1000.0, "cls": "path", "max_grade_pct": 2.0}),
        ("c", "d", 0, {"length_m": 1000.0, "cls": "track", "max_grade_pct": 20.0}),
    ]
    # steep path: 1.0 km full; gentle path: 1.0 km * 0.5; track (even if steep): not counted
    assert rc.est_hab_km(edges) == pytest.approx(1.5)


def test_compute_character_singletrack_dominant():
    edges = [("a", "b", 0, {"length_m": 900.0, "cls": "path", "surface": "unpaved"})] * 1
    edges += [("b", "c", 0, {"length_m": 100.0, "cls": "trunk", "surface": "paved"})]
    assert rc.compute_character(edges) == "singletrack"


def test_compute_character_mixed_when_no_bucket_dominates():
    edges = [
        ("a", "b", 0, {"length_m": 500.0, "cls": "path", "surface": "unpaved"}),
        ("b", "c", 0, {"length_m": 500.0, "cls": "trunk", "surface": "paved"}),
    ]
    assert rc.compute_character(edges) == "mixed"


def test_compute_difficulty_flat_and_easy_is_low():
    assert rc.compute_difficulty(length_km=10.0, ascent_m=20.0, hab_km=0.0) <= 2


def test_compute_difficulty_steep_and_hab_heavy_is_high():
    assert rc.compute_difficulty(length_km=10.0, ascent_m=900.0, hab_km=4.0) == 5


def test_aggregate_stats_remoteness_is_length_weighted_mean(G):
    edges = rc.path_edges(G, ["n1", "n5", "n6", "n4"], lambda d: d["length_m"])
    stats = rc.aggregate_stats(edges)
    assert stats["remoteness"] == 5  # all three track edges are remoteness 5
    assert stats["length_m"] == pytest.approx(4500.0)


# ---------------------------------------------------------------------------
# Water points
# ---------------------------------------------------------------------------


def test_find_water_points_within_range_formats_and_orders_by_distance():
    coords = [[120.0, -8.5], [120.01, -8.5], [120.02, -8.5]]
    water = [("spring", 120.015, -8.5001), ("waterfall", 120.001, -8.5001)]
    out = rc.find_water_points(coords, water, within_m=250.0)
    assert len(out) == 2
    assert out[0].startswith("waterfall ~ km")
    assert out[1].startswith("spring ~ km")
    assert out[0].endswith("(OSM, unverified)")


def test_find_water_points_excludes_far_points():
    coords = [[120.0, -8.5], [120.01, -8.5]]
    water = [("spring", 120.0, -8.6)]  # ~11 km away
    assert rc.find_water_points(coords, water, within_m=250.0) == []


# ---------------------------------------------------------------------------
# Geometry orientation
# ---------------------------------------------------------------------------


def test_build_geometry_orients_reverse_edges_and_dedupes_joints(G):
    # n4 -> n1 direction uses the reverse copies of the trunk-A edges; coords are stored
    # in the ORIGINAL u->v order by build_network.load_graph, so this checks the fix-up.
    edges = rc.path_edges(G, ["n4", "n3", "n2", "n1"], lambda d: d["length_m"])
    coords = rc.build_geometry(G, edges)
    assert coords[0] == [120.03, -8.5]
    assert coords[-1] == [120.0, -8.5]
    # 3 hops of 2 points each, joints deduplicated -> 4 points, not 6
    assert len(coords) == 4


# ---------------------------------------------------------------------------
# End-to-end via main(): --anchors mode, schema validity, variant lettering, merge
# ---------------------------------------------------------------------------


@pytest.fixture()
def graph_file(tmp_path):
    """A standalone graph.json.gz on disk (independent of the in-memory `G` fixture)."""
    nodes = {
        "n1": (120.000, -8.500), "n2": (120.010, -8.500), "n3": (120.020, -8.500),
        "n4": (120.030, -8.500), "n5": (120.010, -8.510), "n6": (120.020, -8.510),
    }

    def leg(a, b, seg, i, **kw):
        return _edge(a, b, seg, i, coords=_straight_coords(nodes[a], nodes[b]), **kw)

    edges = [
        leg("n1", "n2", "trunkA", 0, cls="trunk", surf="paved", length=1000.0, rem=1, grade=1.0),
        leg("n2", "n3", "trunkA", 1, cls="trunk", surf="paved", length=1000.0, rem=1, grade=1.0),
        leg("n3", "n4", "trunkA", 2, cls="trunk", surf="paved", length=1000.0, rem=1, grade=1.0),
        leg("n1", "n5", "track", 0, cls="track", surf="unpaved", length=1500.0, rem=5, grade=3.0),
        leg("n5", "n6", "track", 1, cls="track", surf="unpaved", length=1500.0, rem=5, grade=3.0),
        leg("n6", "n4", "track", 2, cls="track", surf="unpaved", length=1500.0, rem=5, grade=3.0),
    ]
    path = tmp_path / "graph.json.gz"
    write_graph_gz(path, nodes, edges)
    return path


def test_main_anchors_mode_writes_valid_schema_conformant_features(tmp_path, graph_file):
    out_dir = tmp_path / "out"
    rc_argv = [
        "--graph", str(graph_file),
        "--anchors", "120.0,-8.5,Start;120.03,-8.5,End",
        "--k", "2",
        "--out", str(out_dir),
    ]
    rc_exit = rc.main(rc_argv)
    assert rc_exit == 0

    seg_path = out_dir / "segments.candidates.geojson"
    assert seg_path.exists()
    doc = json.loads(seg_path.read_text())
    assert doc["type"] == "FeatureCollection"
    assert len(doc["features"]) >= 1

    errors = rc.validate_features(doc["features"])
    assert errors == [], errors

    ids = [f["properties"]["id"] for f in doc["features"]]
    assert ids == sorted(ids)  # features sorted by id
    for f in doc["features"]:
        p = f["properties"]
        assert p["from_node"] == "n-start"
        assert p["to_node"] == "n-end"
        assert p["route_profile"] in ("remote", "rideable", "direct")
        assert p["variant"].isupper()

    report_path = out_dir / "candidates_report.md"
    assert report_path.exists()
    assert "Start" in report_path.read_text()


def test_main_variant_lettering_continues_after_existing_file(tmp_path, graph_file):
    existing_path = tmp_path / "segments.geojson"
    existing = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[120.0, -8.5], [120.03, -8.5]]},
                "properties": {
                    "id": "s-start-end-a", "name": "Start -> End (hand sketch)",
                    "from_node": "n-start", "to_node": "n-end", "variant": "A",
                    "status": "concept", "geometry_source": "concept-sketch",
                    "character": "mixed", "est_hab_km": 0, "difficulty": 2, "remoteness": 3,
                    "sources": ["field:2026-01-01"],
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[120.0, -8.5], [120.03, -8.5]]},
                "properties": {
                    "id": "s-start-end-b", "name": "Start -> End (hand sketch 2)",
                    "from_node": "n-start", "to_node": "n-end", "variant": "B",
                    "status": "desk-checked", "geometry_source": "manual-trace",
                    "character": "gravel", "est_hab_km": 0, "difficulty": 2, "remoteness": 3,
                    "sources": ["field:2026-01-01"],
                },
            },
        ],
    }
    existing_path.write_text(json.dumps(existing))

    out_dir = tmp_path / "out"
    rc_exit = rc.main([
        "--graph", str(graph_file),
        "--anchors", "120.0,-8.5,Start;120.03,-8.5,End",
        "--k", "1",
        "--existing-segments", str(existing_path),
        "--out", str(out_dir),
    ])
    assert rc_exit == 0
    doc = json.loads((out_dir / "segments.candidates.geojson").read_text())
    variants = sorted(f["properties"]["variant"] for f in doc["features"])
    # standalone mode: only the new candidates are written, and they continue after A/B
    assert all(v >= "C" for v in variants)
    assert "A" not in variants and "B" not in variants


def test_main_merge_freeze_rule_keeps_human_segments_and_replaces_stale_ones(tmp_path, graph_file):
    existing_path = tmp_path / "segments.geojson"
    existing = {
        "type": "FeatureCollection",
        "features": [
            # human-owned: must survive untouched even though it's the pair being regenerated
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[120.0, -8.5], [120.03, -8.5]]},
                "properties": {
                    "id": "s-start-end-a", "name": "hand sketch",
                    "from_node": "n-start", "to_node": "n-end", "variant": "A",
                    "status": "scouted-go", "geometry_source": "gpx-field",
                    "character": "gravel", "est_hab_km": 0, "difficulty": 2, "remoteness": 3,
                    "sources": ["field:2026-01-01"],
                },
            },
            # stale computed candidate for the SAME pair: regenerable, must be dropped
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[120.0, -8.5], [120.03, -8.5]]},
                "properties": {
                    "id": "s-start-end-b", "name": "stale computed",
                    "from_node": "n-start", "to_node": "n-end", "variant": "B",
                    "status": "concept", "geometry_source": "overture-route",
                    "character": "gravel", "est_hab_km": 0, "difficulty": 2, "remoteness": 3,
                    "sources": ["map:overture"],
                },
            },
            # a scouted computed candidate for the same pair: has a scouting entry, so it
            # is NOT regenerable even though geometry_source/status match
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[120.0, -8.5], [120.03, -8.5]]},
                "properties": {
                    "id": "s-start-end-c", "name": "scouted computed",
                    "from_node": "n-start", "to_node": "n-end", "variant": "C",
                    "status": "concept", "geometry_source": "overture-route",
                    "character": "gravel", "est_hab_km": 0, "difficulty": 2, "remoteness": 3,
                    "sources": ["map:overture"],
                    "scouting": [{"date": "2026-02-01", "team": "RC", "verdict": "partial"}],
                },
            },
            # unrelated pair, not processed this run: must survive regardless of its own fields
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[121.0, -8.5], [121.03, -8.5]]},
                "properties": {
                    "id": "s-other-pair-a", "name": "unrelated pair",
                    "from_node": "n-other", "to_node": "n-pair", "variant": "A",
                    "status": "concept", "geometry_source": "overture-route",
                    "character": "gravel", "est_hab_km": 0, "difficulty": 2, "remoteness": 3,
                    "sources": ["map:overture"],
                },
            },
        ],
    }
    existing_path.write_text(json.dumps(existing))

    out_dir = tmp_path / "out"
    rc_exit = rc.main([
        "--graph", str(graph_file),
        "--anchors", "120.0,-8.5,Start;120.03,-8.5,End",
        "--k", "1",
        "--existing-segments", str(existing_path),
        "--merge",
        "--out", str(out_dir),
    ])
    assert rc_exit == 0
    doc = json.loads((out_dir / "segments.candidates.geojson").read_text())
    ids = {f["properties"]["id"] for f in doc["features"]}

    assert "s-start-end-a" in ids  # human-owned: kept
    assert "s-start-end-b" not in ids  # stale computed: dropped
    assert "s-start-end-c" in ids  # scouted computed: kept (not regenerable)
    assert "s-other-pair-a" in ids  # unrelated pair: kept untouched

    # new computed candidate(s) for the regenerated pair continue lettering after A/B/C
    new_ids = ids - {"s-start-end-a", "s-start-end-b", "s-start-end-c", "s-other-pair-a"}
    assert new_ids
    for f in doc["features"]:
        if f["properties"]["id"] in new_ids:
            assert f["properties"]["variant"] >= "D"

    errors = rc.validate_features(doc["features"])
    assert errors == [], errors


def test_main_rejects_anchors_and_route_mode_together(tmp_path, graph_file):
    with pytest.raises(SystemExit):
        rc.main([
            "--graph", str(graph_file),
            "--anchors", "120.0,-8.5,Start;120.03,-8.5,End",
            "--nodes", str(tmp_path / "nodes.geojson"),
            "--out", str(tmp_path / "out"),
        ])


def test_main_merge_requires_existing_segments(tmp_path, graph_file):
    with pytest.raises(SystemExit):
        rc.main([
            "--graph", str(graph_file),
            "--anchors", "120.0,-8.5,Start;120.03,-8.5,End",
            "--merge",
            "--out", str(tmp_path / "out"),
        ])


# ---------------------------------------------------------------------------
# --write-route
# ---------------------------------------------------------------------------


def test_main_write_route_chains_best_candidates(tmp_path, graph_file):
    nodes_path = tmp_path / "nodes.geojson"
    routes_path = tmp_path / "routes.json"
    nodes_doc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature", "geometry": {"type": "Point", "coordinates": [120.0, -8.5]},
                "properties": {"id": "n-start", "name": "Start", "kind": "start",
                               "resupply": "full", "water": "reliable", "sleep": "hotel",
                               "confidence": "verified", "sources": ["field:2026-01-01"]},
            },
            {
                "type": "Feature", "geometry": {"type": "Point", "coordinates": [120.03, -8.5]},
                "properties": {"id": "n-end", "name": "End", "kind": "finish",
                               "resupply": "full", "water": "reliable", "sleep": "hotel",
                               "confidence": "verified", "sources": ["field:2026-01-01"]},
            },
        ],
    }
    nodes_path.write_text(json.dumps(nodes_doc))
    routes_doc = [
        {
            "id": "r-traverse", "name": "Traverse", "audience": ["stakeholder", "scout"],
            "anchors": ["n-start", "n-end"], "segments": [], "status": "concept",
            "target_km_range": [10, 20],
        }
    ]
    routes_path.write_text(json.dumps(routes_doc))

    out_dir = tmp_path / "out"
    rc_exit = rc.main([
        "--graph", str(graph_file),
        "--nodes", str(nodes_path),
        "--routes", str(routes_path),
        "--route-id", "r-traverse",
        "--k", "1",
        "--write-route", "r-traverse-remote",
        "--out", str(out_dir),
    ])
    assert rc_exit == 0

    routes_out = json.loads((out_dir / "routes.candidates.json").read_text())
    new_route = next(r for r in routes_out if r["id"] == "r-traverse-remote")
    assert new_route["name"] == "Traverse (computed, remote profile)"
    assert new_route["anchors"] == ["n-start", "n-end"]
    assert new_route["target_km_range"] == [10, 20]
    assert len(new_route["segments"]) == 1
    seg_id = new_route["segments"][0]

    seg_doc = json.loads((out_dir / "segments.candidates.geojson").read_text())
    chosen = next(f for f in seg_doc["features"] if f["properties"]["id"] == seg_id)
    assert chosen["properties"]["route_profile"] == "remote"  # track route wins under remote


def test_main_write_route_requires_route_mode_not_anchors_arg(tmp_path, graph_file):
    with pytest.raises(SystemExit):
        rc.main([
            "--graph", str(graph_file),
            "--anchors", "120.0,-8.5,Start;120.03,-8.5,End",
            "--write-route", "r-x",
            "--out", str(tmp_path / "out"),
        ])
