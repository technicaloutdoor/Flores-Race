"""fixtures.py

Builds a small, self-contained data/ fixture in code (no dependency on
anything another agent may still be writing under data/ or schemas/):
4 nodes, 2 POIs, 3 chained segments, 1 section, 1 route, 1 scouting report.

Coordinates sit inside the real Flores SRTM tile set (near Ruteng, which the
project's own DEM sanity check uses -- ~1168 m -- see BRIEF.md/dem.py), so
tests that load the real DEM directory get genuine terrain, not zeros.

Used two ways:
  * directly by pytest tests, via ``write_fixture(tmp_path)`` -- hermetic,
    works in any CI checkout, no scratchpad dependency.
  * once, by a small script, to also materialise a copy under the shared
    scratchpad work/fixture/ directory for manual/CLI smoke testing during
    development (see the pipeline task's brief).
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

import common

NODE_START = [120.40, -8.58]
NODE_MID1 = [120.45, -8.60]
NODE_MID2 = [120.47, -8.61]  # ~ Ruteng; real elevation ~1168 m
NODE_END = [120.50, -8.63]


def make_nodes() -> dict:
    def node(fid, name, kind, coords, resupply="basic", water="reliable", sleep="guesthouse"):
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coords},
            "properties": {
                "id": fid,
                "name": name,
                "kind": kind,
                "resupply": resupply,
                "water": water,
                "sleep": sleep,
                "confidence": "approximate",
                "sources": ["field:2026-01-01"],
                "public": False,
            },
        }

    return {
        "type": "FeatureCollection",
        "features": [
            node("n-fx-start", "Fixture Start", "start", NODE_START, resupply="full", sleep="hotel"),
            node("n-fx-mid1", "Fixture Junction", "junction", NODE_MID1, resupply="minimal", sleep="none"),
            node("n-fx-mid2", "Fixture Town", "town", NODE_MID2),
            node("n-fx-end", "Fixture End", "finish", NODE_END, resupply="full", sleep="hotel"),
        ],
    }


def make_pois() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [120.46, -8.605]},
                "properties": {
                    "id": "p-fx-one",
                    "name": "Fixture Viewpoint",
                    "category": "viewpoint",
                    "summary": "A viewpoint used only by pipeline tests.",
                    "race_relevance": "highlight",
                    "access": "trail",
                    "confidence": "unverified",
                    "sources": ["field:2026-01-01"],
                    "public": False,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [120.48, -8.615]},
                "properties": {
                    "id": "p-fx-two",
                    "name": "Fixture Village",
                    "category": "traditional-village",
                    "summary": "A traditional village used only by pipeline tests.",
                    "race_relevance": "anchor",
                    "access": "road",
                    "confidence": "unverified",
                    "sources": ["field:2026-01-01"],
                    "public": False,
                },
            },
        ],
    }


def make_segments() -> dict:
    def segment(fid, name, from_node, to_node, coords, geometry_source, status="concept"):
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "id": fid,
                "name": name,
                "from_node": from_node,
                "to_node": to_node,
                "variant": "A",
                "status": status,
                "geometry_source": geometry_source,
                "character": "gravel",
                "est_hab_km": 0.5,
                "difficulty": 2,
                "remoteness": 2,
                "sources": ["field:2026-01-01"],
                "public": False,
            },
        }

    return {
        "type": "FeatureCollection",
        "features": [
            segment(
                "s-fx-start-mid1-a",
                "Fixture Start to Junction",
                "n-fx-start",
                "n-fx-mid1",
                [NODE_START, [120.425, -8.59], NODE_MID1],
                "concept-sketch",
            ),
            segment(
                "s-fx-mid1-mid2-a",
                "Fixture Junction to Town",
                "n-fx-mid1",
                "n-fx-mid2",
                [NODE_MID1, [120.46, -8.605], NODE_MID2],
                "manual-trace",
                status="desk-checked",
            ),
            segment(
                "s-fx-mid2-end-a",
                "Fixture Town to End",
                "n-fx-mid2",
                "n-fx-end",
                [NODE_MID2, [120.485, -8.62], NODE_END],
                "gpx-field",
            ),
        ],
    }


def make_sections() -> list:
    return [
        {
            "id": "sec-01-fixture",
            "order": 1,
            "title": "Fixture section",
            "from_node": "n-fx-start",
            "to_node": "n-fx-end",
            "theme": ["highland"],
            "story": "A fixture section used only by pipeline tests.",
            "highlight_pois": ["p-fx-one", "p-fx-two"],
            "target_km": [10, 20],
            "hab_expected": "low",
            "scouting_priority": 1,
            "open_questions": ["Is the fixture right?"],
            "public": False,
        }
    ]


def make_routes(broken: bool = False) -> list:
    """The one fixture route. With broken=True the segment order is
    scrambled so the to_node -> from_node chain is broken -- used by the
    "validate fails on a broken chain" test."""
    segments = ["s-fx-start-mid1-a", "s-fx-mid1-mid2-a", "s-fx-mid2-end-a"]
    if broken:
        segments = ["s-fx-start-mid1-a", "s-fx-mid2-end-a", "s-fx-mid1-mid2-a"]
    return [
        {
            "id": "r-fx-test",
            "name": "Fixture Test Route",
            "tagline": "A fixture route used only by pipeline tests.",
            "audience": ["scout"],
            "anchors": ["n-fx-start", "n-fx-mid1", "n-fx-mid2", "n-fx-end"],
            "segments": segments,
            "status": "concept",
            "target_km_range": [10, 20],
        }
    ]


SCOUTING_REPORT = """---
date: 2026-01-01
team: [RC]
segments: [s-fx-start-mid1-a]
verdict: partial
---

Fixture scouting report. Not a real field trip.
"""


def write_fixture(out_dir: Path, broken_route: bool = False) -> Path:
    """Write the full fixture (nodes/pois/segments/sections/routes/
    scouting) into out_dir, mirroring the layout of data/. Returns out_dir."""
    out_dir = Path(out_dir)
    common.write_geojson(out_dir / "nodes.geojson", make_nodes())
    common.write_geojson(out_dir / "pois.geojson", make_pois())
    common.write_geojson(out_dir / "segments.geojson", make_segments())
    common.write_json(out_dir / "sections.json", make_sections())
    common.write_json(out_dir / "routes.json", make_routes(broken=broken_route))

    scouting_dir = out_dir / "scouting"
    scouting_dir.mkdir(parents=True, exist_ok=True)
    (scouting_dir / "2026-01-01-fixture.md").write_text(SCOUTING_REPORT, encoding="utf-8")
    return out_dir
