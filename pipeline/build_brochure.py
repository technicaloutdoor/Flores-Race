#!/usr/bin/env python3
"""build_brochure.py -- assemble the course brochure (HTML, then PDF via Chromium).

Inputs
  pipeline/brochure_content.py            editorial content (prose only, no course numbers)
  exports/gpx/manifest.json               derived numbers per route / section / option (export_gpx.py)
  exports/brochure_config.json            option definitions and colours
  data/sections.json, data/nodes.geojson  hike-a-bike expectation, cultural checkpoints
  docs/brochure/img/maps/*.png            maps (render_brochure_maps.py)
  docs/brochure/img/profiles/*.png        elevation profiles (render_brochure_maps.py)
  docs/brochure/img/sat/*.jpg + manifest  Sentinel-2 crops (with scene dates)
  docs/brochure/research/*.json           desk-research files (photo shot-list appendix)

Outputs
  docs/brochure/flores-race-brochure.html
  docs/brochure/flores-race-brochure.pdf   (unless --no-pdf)

Nothing about the course is typed in the template or the content: every kilometre comes from the
manifest. Missing images become labelled placeholders so the document always builds.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Undefined

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from brochure_content import CONTENT  # noqa: E402

OPTION_COLORS = ["#1b998b", "#e09f3e", "#6f4a8e", "#6b8e23", "#4a6fa5", "#9c4a1a", "#b5179e", "#2a9d8f"]


class ImgIndex:
    """Relative-path helper for one image folder, relative to the HTML file."""

    def __init__(self, folder: Path, rel: str, ext: str, meta: dict | None = None):
        self.folder, self.rel, self.ext, self._meta = folder, rel, ext, meta or {}

    def exists(self, key) -> bool:
        return bool(key) and (self.folder / f"{key}{self.ext}").exists()

    def path(self, key) -> str:
        return f"{self.rel}/{key}{self.ext}"

    def meta(self, key):
        return self._meta.get(key)


def fmt_km(v) -> str:
    return f"{v:,.0f}" if v is not None else "–"


def fmt_int(v) -> str:
    return f"{int(round(v)):,}" if v is not None else "–"


def load_json(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def option_colors(config: dict) -> dict:
    return {o["id"]: OPTION_COLORS[i % len(OPTION_COLORS)] for i, o in enumerate(config.get("options", []))}


def checkpoints_for(section: dict, nodes: dict, route: dict) -> str:
    anchors = route["anchors"]
    try:
        i0, i1 = anchors.index(section["from_node"]), anchors.index(section["to_node"])
    except ValueError:
        return ""
    names = [nodes[a]["properties"]["name"] for a in anchors[i0:i1 + 1] if nodes[a]["properties"].get("kind") == "checkpoint"]
    return ", ".join(names) if names else "–"


def jpeg_copies(folder: Path, quality: int = 88) -> int:
    """Write a JPEG next to every PNG map that lacks a newer one. The PNGs are the
    renderer's lossless output and are not committed; the brochure embeds the JPEGs
    so the PDF and the repository stay a sensible size."""
    if not folder.exists():
        return 0
    try:
        from PIL import Image
    except ImportError:
        return 0
    n = 0
    for png in sorted(folder.glob("*.png")):
        jpg = png.with_suffix(".jpg")
        if jpg.exists() and jpg.stat().st_mtime >= png.stat().st_mtime:
            continue
        with Image.open(png) as im:
            im.convert("RGB").save(jpg, "JPEG", quality=quality, optimize=True, progressive=True)
        n += 1
    return n


def build_shots(research_dir: Path) -> list:
    shots = []
    if not research_dir.exists():
        return shots
    label = {"hazards": "hazards", "logistics": "logistics", "culture-history": "culture"}
    for p in sorted(research_dir.glob("*.json")):
        try:
            j = load_json(p)
        except Exception:
            continue
        tid = j.get("topic_id", p.stem)
        topic = label.get(tid, f"section {tid[-2:]}" if tid.startswith("sec-") else tid)
        for pl in j.get("places", []):
            subj = pl.get("photo_subjects") or []
            terms = pl.get("commons_search_terms") or []
            if not subj and not terms:
                continue
            shots.append({"place": pl.get("name", ""), "topic": topic, "subjects": "; ".join(subj[:5]), "terms": " · ".join(terms[:5])})
    # sections first (course order), then culture, hazards, logistics; cap so the appendix stays around two pages
    order = {"culture": 1, "hazards": 2, "logistics": 3}
    shots.sort(key=lambda s: (order.get(s["topic"], 0), s["topic"]))
    seen, out = set(), []
    for s in shots:
        key = s["place"].split(" (")[0].split(" -- ")[0].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out[:60]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=str(ROOT / "docs" / "brochure"))
    ap.add_argument("--manifest", default=str(ROOT / "exports" / "gpx" / "manifest.json"))
    ap.add_argument("--config", default=str(ROOT / "exports" / "brochure_config.json"))
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    manifest = load_json(Path(args.manifest))
    config = load_json(Path(args.config))
    sections_data = {s["id"]: s for s in load_json(Path(args.data) / "sections.json")}
    nodes = {f["properties"]["id"]: f for f in load_json(Path(args.data) / "nodes.geojson")["features"]}
    routes = {r["id"]: r for r in load_json(Path(args.data) / "routes.json")}
    main_route = routes[config["main_route"]]

    sat_meta = {}
    sat_manifest = out_dir / "img" / "sat" / "manifest.json"
    if sat_manifest.exists():
        for e in load_json(sat_manifest):
            date = e.get("date") or (e.get("dates") or [""])[0]
            if isinstance(date, list):
                date = date[0]
            sat_meta[e["slug"]] = {"date": str(date)[:10], "box_km": e.get("box_km"), "scene": e.get("scene_id") or e.get("scene_ids"), "status": e.get("status", "ok")}

    jpeg_copies(out_dir / "img" / "maps")
    img = {
        "sat": ImgIndex(out_dir / "img" / "sat", "img/sat", ".jpg", sat_meta),
        "maps": ImgIndex(out_dir / "img" / "maps", "img/maps", ".jpg"),
        "profiles": ImgIndex(out_dir / "img" / "profiles", "img/profiles", ".png"),
    }

    routes_by_id = {r["id"]: r for r in manifest["routes"]}
    main = routes_by_id[config["main_route"]]
    ultra = routes_by_id.get(config.get("ultra_route"), main)
    ultra_plus = routes_by_id.get("r-ultra-plus", ultra)
    sec_stats = {s["id"]: s for s in manifest["sections"]}

    sections = []
    for s in CONTENT["sections"]:
        st = sec_stats[s["id"]]
        sd = sections_data[s["id"]]
        sections.append({**s, "stats": st, "hab_expected": sd.get("hab_expected", "–"), "map_id": f"sec-{s['order']:02d}",
                         "checkpoints": checkpoints_for(sd, nodes, main_route)})

    colors = option_colors(config)
    options_list = []
    for o in manifest["options"]:
        text = CONTENT["options"]["items"].get(o["id"], {"why": "", "when": "", "risks": ""})
        options_list.append({**o, "color": colors.get(o["id"], "#555"), "text": text})
    options_by_id = {o["id"]: o for o in options_list}
    n_checkpoints = sum(1 for a in main_route["anchors"] if nodes[a]["properties"].get("kind") == "checkpoint")

    shots = build_shots(out_dir / "research")
    sat_scenes = [{"slug": k, "scene": (v["scene"] if isinstance(v["scene"], str) else ", ".join(v["scene"] or [])), "date": v["date"]} for k, v in sorted(sat_meta.items()) if v.get("status") == "ok"]

    env = Environment(loader=FileSystemLoader(str(HERE / "templates")), autoescape=True, undefined=Undefined, trim_blocks=False, lstrip_blocks=False)
    env.globals.update(fmt_km=fmt_km, fmt_int=fmt_int)
    tpl = env.get_template("brochure.html.j2")
    html = tpl.render(
        meta=CONTENT["meta"], cover=CONTENT["cover"], idea=CONTENT["idea"], glance=CONTENT["glance"], rwgps=CONTENT["rwgps"],
        sections=sections, options=CONTENT["options"], options_list=options_list, options_by_id=options_by_id,
        hazards=CONTENT["hazards"], culture=CONTENT["culture"], logistics=CONTENT["logistics"], photos=CONTENT["photos"], sources=CONTENT["sources"],
        manifest=manifest, main=main, ultra=ultra, ultra_plus=ultra_plus, img=img, n_checkpoints=n_checkpoints, shots=shots, sat_scenes=sat_scenes,
        built=dt.date.today().isoformat(),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "flores-race-brochure.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"wrote {html_path} ({len(html)//1024} KB)")

    missing = []
    for s in sections:
        if not img["maps"].exists(s["map_id"]):
            missing.append(f"map {s['map_id']}")
        if not img["profiles"].exists(s["id"]):
            missing.append(f"profile {s['id']}")
    for o in options_list:
        if not (img["maps"].exists("opt-" + o["id"]) or img["maps"].exists(o["id"])):
            missing.append(f"map {o['id']}")
    if not img["maps"].exists("overview"):
        missing.append("map overview")
    if missing:
        print("placeholders used for:", ", ".join(missing))

    if args.no_pdf:
        return 0
    pdf_path = out_dir / "flores-race-brochure.pdf"
    env_vars = dict(os.environ, NODE_PATH=os.environ.get("NODE_PATH", "/opt/node22/lib/node_modules"))
    subprocess.run(["node", str(HERE / "html_to_pdf.mjs"), str(html_path), str(pdf_path)], check=True, env=env_vars)
    try:
        import pymupdf  # type: ignore

        doc = pymupdf.open(str(pdf_path))
        print(f"wrote {pdf_path}: {len(doc)} pages, {pdf_path.stat().st_size // 1024} KB")
    except Exception:
        print(f"wrote {pdf_path}: {pdf_path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
