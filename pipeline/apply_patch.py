#!/usr/bin/env python3
"""apply_patch.py

Apply a scouting patch (``schemas/scouting-patch.schema.json``, exported by
the app in scout mode) to ``data/``: a maintainer's half of the loop
described in ARCHITECTURE.md section 7.4.

A patch may only touch the scouting-owned fields listed in
docs/data-model.md -- for a segment: ``status``, ``character``,
``est_hab_km``, ``difficulty``, ``remoteness``, ``water_points``,
``resupply_notes``, ``hazards``, ``cultural_notes``, ``open_questions``, plus
appending to ``scouting``; for a node: ``resupply``, ``water``, ``sleep``,
``notes`` -- and may append brand new POIs. It can never rename a feature or
touch geometry: geometry changes come from GPX files a human traces
(see ARCHITECTURE.md section 8), never from a patch. This is enforced twice:
the schema's ``additionalProperties: false`` already rejects any other key
(including ``geometry``/``id``), and the merge step below refuses them again
independently of the schema, so the rule holds even if a future schema
change loosened it by accident.

Usage::

    python3 apply_patch.py --patch scouting-patch.json --data data [--dry-run]
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Optional

import common
import validate

ALLOWED_SEGMENT_FIELDS = {
    "status",
    "character",
    "est_hab_km",
    "difficulty",
    "remoteness",
    "water_points",
    "resupply_notes",
    "hazards",
    "cultural_notes",
    "open_questions",
}

ALLOWED_NODE_FIELDS = {"resupply", "water", "sleep", "notes"}


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def _index_by_id(fc: dict) -> dict:
    return {feat["properties"]["id"]: feat for feat in fc.get("features", [])}


def _generate_poi_id(name: str, existing_ids: set) -> str:
    base = f"p-{common.slugify(name) or 'poi'}"
    candidate = base
    n = 2
    while candidate in existing_ids:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def apply_patch_to_data(patch: dict, nodes_fc: dict, segments_fc: dict, pois_fc: dict) -> tuple:
    """Merge a patch into (copies of) the canonical data.

    Returns (nodes_fc, segments_fc, pois_fc, diff, errors). ``errors`` is a
    list of human-readable refusal reasons (unknown ids, disallowed fields,
    id collisions); the caller should refuse to write anything if it is
    non-empty. Inputs are not mutated.
    """
    nodes_fc = copy.deepcopy(nodes_fc)
    segments_fc = copy.deepcopy(segments_fc)
    pois_fc = copy.deepcopy(pois_fc)

    segments_by_id = _index_by_id(segments_fc)
    nodes_by_id = _index_by_id(nodes_fc)
    pois_by_id = _index_by_id(pois_fc)

    errors: list = []
    diff = {"segments": {}, "nodes": {}, "new_pois": []}

    for seg_id, changes in (patch.get("segments") or {}).items():
        feat = segments_by_id.get(seg_id)
        if feat is None:
            errors.append(f"segments: unknown segment id {seg_id!r} (refused)")
            continue
        changed = {}
        for key, value in (changes or {}).items():
            if key == "scouting_append":
                entries = value or []
                feat["properties"].setdefault("scouting", [])
                feat["properties"]["scouting"].extend(entries)
                changed["scouting_append"] = f"+{len(entries)} entry(ies)"
                continue
            if key not in ALLOWED_SEGMENT_FIELDS:
                errors.append(
                    f"segments.{seg_id}: field {key!r} may not be set by a scouting patch (refused)"
                )
                continue
            old = feat["properties"].get(key)
            feat["properties"][key] = value
            changed[key] = {"old": old, "new": value}
        if changed:
            diff["segments"][seg_id] = changed

    for node_id, changes in (patch.get("nodes") or {}).items():
        feat = nodes_by_id.get(node_id)
        if feat is None:
            errors.append(f"nodes: unknown node id {node_id!r} (refused)")
            continue
        changed = {}
        for key, value in (changes or {}).items():
            if key not in ALLOWED_NODE_FIELDS:
                errors.append(
                    f"nodes.{node_id}: field {key!r} may not be set by a scouting patch (refused)"
                )
                continue
            old = feat["properties"].get(key)
            feat["properties"][key] = value
            changed[key] = {"old": old, "new": value}
        if changed:
            diff["nodes"][node_id] = changed

    used_new_ids: set = set()
    for poi in patch.get("new_pois") or []:
        props = dict(poi.get("properties") or {})
        poi_id = props.get("id")
        if poi_id is not None:
            if poi_id in pois_by_id or poi_id in used_new_ids:
                errors.append(f"new_pois: id {poi_id!r} already exists (refused)")
                continue
        else:
            poi_id = _generate_poi_id(props.get("name", "poi"), set(pois_by_id) | used_new_ids)
            props["id"] = poi_id
        used_new_ids.add(poi_id)
        new_feature = {"type": "Feature", "geometry": poi.get("geometry"), "properties": props}
        pois_fc["features"].append(new_feature)
        pois_by_id[poi_id] = new_feature
        diff["new_pois"].append(poi_id)

    return nodes_fc, segments_fc, pois_fc, diff, errors


def print_diff_summary(diff: dict, out=sys.stdout) -> None:
    n_seg = len(diff["segments"])
    n_node = len(diff["nodes"])
    n_poi = len(diff["new_pois"])
    print(
        f"-- patch diff: {n_seg} segment(s) changed, {n_node} node(s) changed, "
        f"{n_poi} new POI(s) --",
        file=out,
    )
    for seg_id, fields in diff["segments"].items():
        print(f"  segment {seg_id}:", file=out)
        for key, value in fields.items():
            if key == "scouting_append":
                print(f"    scouting_append: {value}", file=out)
            else:
                print(f"    {key}: {value['old']!r} -> {value['new']!r}", file=out)
    for node_id, fields in diff["nodes"].items():
        print(f"  node {node_id}:", file=out)
        for key, value in fields.items():
            print(f"    {key}: {value['old']!r} -> {value['new']!r}", file=out)
    for poi_id in diff["new_pois"]:
        print(f"  new POI: {poi_id}", file=out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", required=True, help="Path to the scouting-patch JSON file")
    parser.add_argument("--data", default="data", help="Path to data/ (default: data)")
    parser.add_argument("--schemas", default="schemas", help="Path to schemas/ (default: schemas)")
    parser.add_argument(
        "--out", default=None, help="Where to write the merged files (default: --data, in place)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the diff summary; write nothing"
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    data_dir = Path(args.data)
    schemas_dir = Path(args.schemas)
    out_dir = Path(args.out) if args.out else data_dir

    patch = common.read_json(args.patch)

    schema_errors = validate.validate_against_schema(patch, "scouting-patch.schema.json", schemas_dir)
    if schema_errors:
        print("patch rejected: does not match schemas/scouting-patch.schema.json:", file=sys.stderr)
        for err in schema_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    nodes_fc = common.read_geojson(data_dir / "nodes.geojson")
    segments_fc = common.read_geojson(data_dir / "segments.geojson")
    pois_fc = common.read_geojson(data_dir / "pois.geojson")

    nodes_new, segments_new, pois_new, diff, errors = apply_patch_to_data(
        patch, nodes_fc, segments_fc, pois_fc
    )
    if errors:
        print("patch rejected:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    # Re-validate the merged result before writing anything -- a patch that
    # is individually well-formed can still leave the data inconsistent
    # (e.g. a new POI missing a required field).
    loaded = validate.LoadedData(
        nodes=nodes_new,
        pois=pois_new,
        segments=segments_new,
        sections=common.read_json(data_dir / "sections.json"),
        routes=common.read_json(data_dir / "routes.json"),
        scouting={},
    )
    report = validate.validate_loaded(loaded, schemas_dir)
    if report.errors:
        print("patch rejected: result would fail validation:", file=sys.stderr)
        report.print_report(out=sys.stderr)
        return 1

    print_diff_summary(diff)

    if args.dry_run:
        print("(dry run: nothing written)")
        return 0

    common.write_geojson(out_dir / "nodes.geojson", nodes_new)
    common.write_geojson(out_dir / "segments.geojson", segments_new)
    common.write_geojson(out_dir / "pois.geojson", pois_new)
    print(f"Applied patch, wrote nodes/segments/pois.geojson to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
