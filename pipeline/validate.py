#!/usr/bin/env python3
"""validate.py

Validate the canonical data in ``data/`` against the JSON Schemas in
``schemas/`` (jsonschema, Draft 2020-12, with a schema registry so the
relative ``$ref: "common.schema.json#/..."`` in every schema resolves), then
check referential integrity across files: unique ids, segments referencing
real nodes, segment endpoints close to their nodes, routes chaining
``to_node -> from_node`` from their first anchor to their last, sections
referencing real nodes/pois, and scouting front matter referencing real
segments.

Runs in CI (see ARCHITECTURE.md, .github/workflows/validate.yml) and is
imported by ``apply_patch.py`` and ``build_web_data.py`` to check data before
they act on it, so the checking logic lives in importable functions, not only
behind a CLI.

Usage::

    python3 validate.py --data data --schemas schemas [--strict]

Exit code 1 if there are any errors (or, with --strict, any warnings too).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

import common

DATA_FILES = {
    "nodes": "nodes.geojson",
    "pois": "pois.geojson",
    "segments": "segments.geojson",
    "sections": "sections.json",
    "routes": "routes.json",
}

SCHEMA_FOR = {
    "nodes": "nodes.schema.json",
    "pois": "pois.schema.json",
    "segments": "segments.schema.json",
    "sections": "sections.schema.json",
    "routes": "routes.schema.json",
}

#: How far (metres) a segment's first/last vertex may sit from its declared
#: node before it is flagged. Concept-sketch corridors are hand-drawn and
#: routinely miss by more than this; anything scouted or traced should not.
ENDPOINT_TOLERANCE_M = 300.0

VALID_VERDICTS = {"go", "no-go", "partial"}


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def extend(self, other: "Report") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def ok(self, strict: bool = False) -> bool:
        if self.errors:
            return False
        if strict and self.warnings:
            return False
        return True

    def print_report(self, out=sys.stdout) -> None:
        for msg in self.errors:
            print(f"ERROR   {msg}", file=out)
        for msg in self.warnings:
            print(f"WARNING {msg}", file=out)
        print(
            f"-- {len(self.errors)} error(s), {len(self.warnings)} warning(s) --",
            file=out,
        )


# ---------------------------------------------------------------------------
# Schema loading / validation
# ---------------------------------------------------------------------------


def build_registry(schemas_dir: Path) -> Registry:
    """Load every *.schema.json in schemas_dir into a referencing.Registry,
    keyed by each schema's own ``$id`` -- this is what lets a schema's
    relative ``$ref: "common.schema.json#/$defs/..."`` resolve without
    network access or hardcoded absolute paths.
    """
    resources = []
    for schema_path in sorted(schemas_dir.glob("*.schema.json")):
        contents = common.read_json(schema_path)
        schema_id = contents.get("$id", schema_path.name)
        resource = Resource.from_contents(contents, default_specification=DRAFT202012)
        resources.append((schema_id, resource))
    return Registry().with_resources(resources)


def load_schema(schemas_dir: Path, schema_filename: str) -> dict:
    return common.read_json(schemas_dir / schema_filename)


def validate_instance(instance: Any, schema: dict, registry: Registry) -> list:
    """Validate one JSON instance against one already-loaded schema dict.
    Returns a list of human-readable error strings (empty if valid)."""
    validator = Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    out = []
    for err in errors:
        loc = "/".join(str(p) for p in err.path) or "<root>"
        out.append(f"{loc}: {err.message}")
    return out


def validate_against_schema(
    instance: Any, schema_filename: str, schemas_dir: Path, registry: Optional[Registry] = None
) -> list:
    """Convenience: load one schema by filename and validate against it."""
    if registry is None:
        registry = build_registry(schemas_dir)
    schema = load_schema(schemas_dir, schema_filename)
    return validate_instance(instance, schema, registry)


# ---------------------------------------------------------------------------
# Loading data/ from disk
# ---------------------------------------------------------------------------


@dataclass
class LoadedData:
    nodes: Optional[dict] = None
    pois: Optional[dict] = None
    segments: Optional[dict] = None
    sections: Optional[list] = None
    routes: Optional[list] = None
    scouting: Optional[dict] = None  # filename -> {"front_matter": {...}, "path": Path}


def load_data(data_dir: Path, report: Report) -> LoadedData:
    loaded = LoadedData()
    for key, filename in DATA_FILES.items():
        path = data_dir / filename
        if not path.exists():
            report.error(f"{filename}: file is missing")
            continue
        try:
            value = common.read_json(path)
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            report.error(f"{filename}: could not parse JSON ({exc})")
            continue
        setattr(loaded, key, value)

    scouting_dir = data_dir / "scouting"
    scouting = {}
    if scouting_dir.is_dir():
        for md_path in sorted(scouting_dir.glob("*.md")):
            text = md_path.read_text(encoding="utf-8")
            front_matter = parse_front_matter(text)
            scouting[md_path.name] = {"front_matter": front_matter, "path": md_path}
    loaded.scouting = scouting
    return loaded


def parse_front_matter(text: str) -> dict:
    """Parse the YAML front matter of a scouting report. Returns {} if the
    file has none. Only the first '---'-delimited block is treated as front
    matter; the rest of the file is free-text markdown and is not parsed."""
    if not text.lstrip().startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data or {}


# ---------------------------------------------------------------------------
# Schema-level validation of everything in data/
# ---------------------------------------------------------------------------


def validate_schemas(loaded: LoadedData, schemas_dir: Path, report: Report) -> Registry:
    registry = build_registry(schemas_dir)
    for key, filename in DATA_FILES.items():
        instance = getattr(loaded, key)
        if instance is None:
            continue  # already reported as missing in load_data
        schema = load_schema(schemas_dir, SCHEMA_FOR[key])
        for err in validate_instance(instance, schema, registry):
            report.error(f"{filename}: {err}")
    return registry


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------


def _feature_props_by_id(fc: Optional[dict]) -> dict:
    out = {}
    if not fc:
        return out
    for feat in fc.get("features", []):
        props = feat.get("properties", {})
        fid = props.get("id")
        if fid is not None:
            out[fid] = feat
    return out


def check_unique_ids(loaded: LoadedData, report: Report) -> None:
    def check_feature_ids(fc: Optional[dict], filename: str) -> None:
        if not fc:
            return
        seen = {}
        for feat in fc.get("features", []):
            fid = feat.get("properties", {}).get("id")
            seen[fid] = seen.get(fid, 0) + 1
        for fid, count in seen.items():
            if count > 1:
                report.error(f"{filename}: id {fid!r} used {count} times")

    def check_list_ids(items: Optional[list], filename: str) -> None:
        if not items:
            return
        seen = {}
        for item in items:
            iid = item.get("id")
            seen[iid] = seen.get(iid, 0) + 1
        for iid, count in seen.items():
            if count > 1:
                report.error(f"{filename}: id {iid!r} used {count} times")

    check_feature_ids(loaded.nodes, "nodes.geojson")
    check_feature_ids(loaded.pois, "pois.geojson")
    check_feature_ids(loaded.segments, "segments.geojson")
    check_list_ids(loaded.sections, "sections.json")
    check_list_ids(loaded.routes, "routes.json")


def check_segments(loaded: LoadedData, report: Report) -> None:
    nodes_by_id = _feature_props_by_id(loaded.nodes)
    if not loaded.segments:
        return
    for feat in loaded.segments.get("features", []):
        props = feat.get("properties", {})
        sid = props.get("id", "<unknown>")
        from_node = props.get("from_node")
        to_node = props.get("to_node")
        if from_node is not None and from_node not in nodes_by_id:
            report.error(f"segments.geojson: {sid}: from_node {from_node!r} not in nodes.geojson")
        if to_node is not None and to_node not in nodes_by_id:
            report.error(f"segments.geojson: {sid}: to_node {to_node!r} not in nodes.geojson")

        geometry = feat.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if len(coords) < 2 or from_node not in nodes_by_id or to_node not in nodes_by_id:
            continue

        geometry_source = props.get("geometry_source")
        from_geom = nodes_by_id[from_node].get("geometry", {}).get("coordinates")
        to_geom = nodes_by_id[to_node].get("geometry", {}).get("coordinates")
        first_pt = coords[0]
        last_pt = coords[-1]

        if from_geom:
            dist = common.haversine_m(first_pt[0], first_pt[1], from_geom[0], from_geom[1])
            if dist > ENDPOINT_TOLERANCE_M:
                msg = (
                    f"segments.geojson: {sid}: first vertex is {dist:.0f} m from "
                    f"{from_node} (tolerance {ENDPOINT_TOLERANCE_M:.0f} m)"
                )
                if geometry_source == "concept-sketch":
                    report.warn(msg)
                else:
                    report.error(msg)
        if to_geom:
            dist = common.haversine_m(last_pt[0], last_pt[1], to_geom[0], to_geom[1])
            if dist > ENDPOINT_TOLERANCE_M:
                msg = (
                    f"segments.geojson: {sid}: last vertex is {dist:.0f} m from "
                    f"{to_node} (tolerance {ENDPOINT_TOLERANCE_M:.0f} m)"
                )
                if geometry_source == "concept-sketch":
                    report.warn(msg)
                else:
                    report.error(msg)


def check_routes(loaded: LoadedData, report: Report) -> None:
    nodes_by_id = _feature_props_by_id(loaded.nodes)
    segments_by_id = _feature_props_by_id(loaded.segments)
    if not loaded.routes:
        return
    for route in loaded.routes:
        rid = route.get("id", "<unknown>")
        anchors = route.get("anchors") or []
        seg_ids = route.get("segments") or []

        for a in anchors:
            if a not in nodes_by_id:
                report.error(f"routes.json: {rid}: anchor {a!r} not in nodes.geojson")

        seg_feats = []
        missing = False
        for seg_id in seg_ids:
            feat = segments_by_id.get(seg_id)
            if feat is None:
                report.error(f"routes.json: {rid}: segment {seg_id!r} not in segments.geojson")
                missing = True
            seg_feats.append(feat)
        if missing or not seg_feats:
            continue

        # Chain to_node -> from_node between consecutive segments.
        for i in range(len(seg_feats) - 1):
            cur_props = seg_feats[i]["properties"]
            nxt_props = seg_feats[i + 1]["properties"]
            if cur_props.get("to_node") != nxt_props.get("from_node"):
                report.error(
                    f"routes.json: {rid}: segment {cur_props.get('id')} ends at "
                    f"{cur_props.get('to_node')} but segment {nxt_props.get('id')} "
                    f"starts at {nxt_props.get('from_node')} (chain broken)"
                )

        if anchors:
            first_from = seg_feats[0]["properties"].get("from_node")
            last_to = seg_feats[-1]["properties"].get("to_node")
            if first_from != anchors[0]:
                report.error(
                    f"routes.json: {rid}: first segment starts at {first_from!r}, "
                    f"not the first anchor {anchors[0]!r}"
                )
            if last_to != anchors[-1]:
                report.error(
                    f"routes.json: {rid}: last segment ends at {last_to!r}, "
                    f"not the last anchor {anchors[-1]!r}"
                )


def check_sections(loaded: LoadedData, report: Report) -> None:
    nodes_by_id = _feature_props_by_id(loaded.nodes)
    pois_by_id = _feature_props_by_id(loaded.pois)
    if not loaded.sections:
        return
    for section in loaded.sections:
        sid = section.get("id", "<unknown>")
        for field_name in ("from_node", "to_node"):
            node_id = section.get(field_name)
            if node_id is not None and node_id not in nodes_by_id:
                report.error(f"sections.json: {sid}: {field_name} {node_id!r} not in nodes.geojson")
        for poi_id in section.get("highlight_pois") or []:
            if poi_id not in pois_by_id:
                report.error(f"sections.json: {sid}: highlight_pois {poi_id!r} not in pois.geojson")


def check_scouting(loaded: LoadedData, report: Report) -> None:
    segments_by_id = _feature_props_by_id(loaded.segments)
    for filename, entry in (loaded.scouting or {}).items():
        fm = entry["front_matter"]
        if not fm:
            report.warn(f"scouting/{filename}: no YAML front matter found")
            continue
        date = fm.get("date")
        if date is not None and not _looks_like_date(str(date)):
            report.error(f"scouting/{filename}: date {date!r} is not YYYY-MM-DD")
        verdict = fm.get("verdict")
        if verdict is not None and verdict not in VALID_VERDICTS:
            report.error(
                f"scouting/{filename}: verdict {verdict!r} not one of {sorted(VALID_VERDICTS)}"
            )
        seg_ids = fm.get("segments") or []
        if isinstance(seg_ids, str):
            seg_ids = [seg_ids]
        for seg_id in seg_ids:
            if seg_id not in segments_by_id:
                report.error(f"scouting/{filename}: segment {seg_id!r} not in segments.geojson")


def _looks_like_date(value: str) -> bool:
    import re

    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------


def validate_loaded(loaded: LoadedData, schemas_dir: Path) -> Report:
    """Run schema validation (if schemas_dir given) plus every referential
    integrity check against already-loaded, in-memory data. Used both by the
    CLI and by callers (apply_patch.py, build_web_data.py) that already have
    the structures in memory and don't want a round trip through disk.
    """
    report = Report()
    validate_schemas(loaded, schemas_dir, report)
    check_unique_ids(loaded, report)
    check_segments(loaded, report)
    check_routes(loaded, report)
    check_sections(loaded, report)
    check_scouting(loaded, report)
    return report


def validate_data(data_dir: Path, schemas_dir: Path) -> Report:
    """Load data_dir from disk and fully validate it. This is what the CLI
    and build_web_data.py use for the "validate everything in data/" step."""
    report = Report()
    loaded = load_data(data_dir, report)
    report.extend(validate_loaded(loaded, schemas_dir))
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data", help="Path to the data/ directory (default: data)")
    parser.add_argument(
        "--schemas", default="schemas", help="Path to the schemas/ directory (default: schemas)"
    )
    parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as errors (exit 1 if any warnings)"
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    data_dir = Path(args.data)
    schemas_dir = Path(args.schemas)

    report = validate_data(data_dir, schemas_dir)
    report.print_report()

    return 0 if report.ok(strict=args.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
