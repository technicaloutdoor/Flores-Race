#!/usr/bin/env python3
"""export_gpx.py -- turn route variants and optional loops into GPX files that a
route planner (Ride with GPS, Komoot, Garmin) can import, plus the elevation
profiles and the stats the brochure quotes.

Everything is *derived*: the ordered segment list comes from data/routes.json,
the geometry from data/segments.geojson, the options from
exports/brochure_config.json. Nothing is typed by hand (docs/data-model.md,
design rule "totals are always derived").

Outputs (under --out, default exports/gpx/):

  flores-race-traverse.gpx              main course, one track, no waypoints
  flores-race-traverse-with-pois.gpx    same track + anchors and key POIs as <wpt>
  flores-race-ultra.gpx                 Ultra (Manggarai Timur + Bola loops)
  flores-race-ultra-plus.gpx            Ultra + Inerie full circuit
  sections/flores-race-s01-....gpx      one file per narrative section (main course)
  options/<option-id>.gpx               each optional loop / alternative on its own
  manifest.json                         every file with km, climbing, unpaved %, points
  README.md                             human summary table + import instructions

and, under --profiles-out (default docs/brochure/data/profiles/), one JSON per
route / section / option with the smoothed elevation profile and anchor km
marks, consumed by pipeline/render_brochure_maps.py.

Elevation: SRTM via pipeline/dem.py, bathymetry clamped to 0 (common.py),
5-sample median + mean smoothing and the 10 m hysteresis threshold from
build_profiles.py, so the climbing numbers here match the web app's.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import common  # noqa: E402
from build_profiles import (  # noqa: E402
    DEFAULT_ASCENT_THRESHOLD_M,
    ascent_descent,
    smooth_elevations,
)

CREATOR = "Flores Race Planner (pipeline/export_gpx.py)"
GPX_NS = "http://www.topografix.com/GPX/1/1"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_all(data_dir: Path, config_path: Path) -> dict:
    nodes = {f["properties"]["id"]: f for f in common.read_geojson(data_dir / "nodes.geojson")["features"]}
    pois = common.read_geojson(data_dir / "pois.geojson")["features"]
    segments = {f["properties"]["id"]: f for f in common.read_geojson(data_dir / "segments.geojson")["features"]}
    routes = {r["id"]: r for r in common.read_json(data_dir / "routes.json")}
    sections = sorted(common.read_json(data_dir / "sections.json"), key=lambda s: s["order"])
    config = common.read_json(config_path)
    return dict(nodes=nodes, pois=pois, segments=segments, routes=routes, sections=sections, config=config)


def node_xy(nodes: dict, node_id: str) -> tuple:
    return tuple(nodes[node_id]["geometry"]["coordinates"][:2])


# ---------------------------------------------------------------------------
# Chaining
# ---------------------------------------------------------------------------


def chain_segments(segment_ids: list, segments: dict, nodes: dict, start_node: str | None = None) -> dict:
    """Concatenate segment geometries in order, orienting each so it continues
    from the previous end. Returns coords, per-segment km offsets, gaps."""
    coords: list = []
    legs: list = []
    gaps: list = []
    cursor = node_xy(nodes, start_node) if start_node else None
    km_so_far = 0.0
    for sid in segment_ids:
        feat = segments.get(sid)
        if feat is None:
            gaps.append({"segment": sid, "problem": "missing segment id"})
            continue
        pts = [tuple(c[:2]) for c in feat["geometry"]["coordinates"]]
        if cursor is not None:
            d_start = common.haversine_m(*cursor, *pts[0])
            d_end = common.haversine_m(*cursor, *pts[-1])
            if d_end < d_start:
                pts = list(reversed(pts))
                d_start = d_end
            if d_start > 300:
                gaps.append({"segment": sid, "gap_m": round(d_start), "problem": "start is far from previous end"})
        if coords and common.haversine_m(*coords[-1], *pts[0]) < 1.0:
            pts = pts[1:]
        seg_km = common.geodesic_length_km(pts) if len(pts) > 1 else 0.0
        props = feat["properties"]
        legs.append(
            {
                "segment": sid,
                "from_node": props["from_node"],
                "to_node": props["to_node"],
                "start_km": round(km_so_far, 3),
                "length_km": round(seg_km, 3),
                "stats": props.get("stats") or {},
                "est_hab_km": props.get("est_hab_km", 0) or 0,
                "remoteness": props.get("remoteness"),
                "surface_mix": props.get("surface_mix") or {},
                "geometry_source": props.get("geometry_source"),
                "route_profile": props.get("route_profile"),
                "reversed": cursor is not None and d_end < d_start if cursor is not None else False,
            }
        )
        coords.extend(pts)
        km_so_far += seg_km
        cursor = pts[-1]
    return {"coords": coords, "legs": legs, "gaps": gaps, "length_km": round(km_so_far, 3)}


# ---------------------------------------------------------------------------
# Elevation and stats
# ---------------------------------------------------------------------------


def elevations_for(dem, coords: list) -> list:
    return [common.clamp_elevation(dem.elevation(lon, lat)) for lon, lat in coords]


def profile_for(dem, coords: list, step_m: float = 50.0) -> dict:
    samples = common.sample_line_clamped(dem, coords, step_m=step_m)
    if len(samples) < 2:
        return {"points": [], "ascent_m": 0.0, "descent_m": 0.0, "min_elev_m": 0.0, "max_elev_m": 0.0}
    dist = [d for d, _ in samples]
    smoothed = smooth_elevations([e for _, e in samples])
    asc, desc = ascent_descent(smoothed, ascent_threshold_m=DEFAULT_ASCENT_THRESHOLD_M)
    pts = list(zip(dist, [round(e, 1) for e in smoothed]))
    decimated = common.decimate_profile(pts, max_points=1500)
    return {
        "points": [[round(d / 1000.0, 3), e] for d, e in decimated],
        "ascent_m": round(asc),
        "descent_m": round(desc),
        "min_elev_m": round(min(smoothed)),
        "max_elev_m": round(max(smoothed)),
    }


def unpaved_pct(legs: list) -> float | None:
    paved = 0.0
    total = 0.0
    for leg in legs:
        mix = leg["surface_mix"]
        if mix:
            t = sum(mix.values())
            total += t
            paved += mix.get("paved", 0.0)
    if total <= 0:
        return None
    return round(100.0 * (total - paved) / total, 1)


def summarise(chain: dict, prof: dict) -> dict:
    legs = chain["legs"]
    hab = round(sum(l["est_hab_km"] for l in legs), 1)
    rem = [l["remoteness"] for l in legs if l["remoteness"] is not None]
    rem_w = None
    if rem:
        w = [l["length_km"] for l in legs if l["remoteness"] is not None]
        rem_w = round(sum(r * k for r, k in zip(rem, w)) / max(sum(w), 1e-9), 2)
    return {
        "length_km": round(chain["length_km"], 1),
        "ascent_m": prof["ascent_m"],
        "descent_m": prof["descent_m"],
        "min_elev_m": prof["min_elev_m"],
        "max_elev_m": prof["max_elev_m"],
        "unpaved_pct": unpaved_pct(legs),
        "hike_a_bike_km_est": hab,
        "remoteness_index_weighted": rem_w,
        "segments": len(legs),
        "sketch_segments": sum(1 for l in legs if l["geometry_source"] == "concept-sketch"),
        "gaps": chain["gaps"],
    }


# ---------------------------------------------------------------------------
# GPX writing
# ---------------------------------------------------------------------------


def _wpt(lon: float, lat: float, ele: float | None, name: str, desc: str, sym: str, typ: str) -> str:
    parts = [f'  <wpt lat="{lat:.6f}" lon="{lon:.6f}">']
    if ele is not None:
        parts.append(f"    <ele>{ele:.1f}</ele>")
    parts.append(f"    <name>{escape(name)}</name>")
    if desc:
        parts.append(f"    <desc>{escape(desc)}</desc>")
    parts.append(f"    <sym>{escape(sym)}</sym>")
    parts.append(f"    <type>{escape(typ)}</type>")
    parts.append("  </wpt>")
    return "\n".join(parts)


def write_gpx(path: Path, name: str, desc: str, coords: list, eles: list, waypoints: list, link: str) -> int:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<gpx version="1.1" creator="{escape(CREATOR)}" xmlns="{GPX_NS}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xsi:schemaLocation="{GPX_NS} http://www.topografix.com/GPX/1/1/gpx.xsd">',
        "  <metadata>",
        f"    <name>{escape(name)}</name>",
        f"    <desc>{escape(desc)}</desc>",
        f'    <link href="{escape(link)}"><text>Flores Race Planner</text></link>',
        f"    <time>{now}</time>",
        "  </metadata>",
    ]
    out.extend(waypoints)
    out.append("  <trk>")
    out.append(f"    <name>{escape(name)}</name>")
    out.append(f"    <desc>{escape(desc)}</desc>")
    out.append("    <trkseg>")
    for (lon, lat), ele in zip(coords, eles):
        out.append(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>{ele:.1f}</ele></trkpt>')
    out.append("    </trkseg>")
    out.append("  </trk>")
    out.append("</gpx>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(coords)


SYM_BY_NODE_KIND = {
    "start": "Flag, Green",
    "finish": "Flag, Red",
    "checkpoint": "Flag, Blue",
    "town": "City (Medium)",
    "village": "Residence",
    "junction": "Waypoint",
    "trailhead": "Trail Head",
    "port": "Anchor",
    "airport": "Airport",
}
SYM_BY_POI_CATEGORY = {
    "volcano": "Summit",
    "crater-lake": "Scenic Area",
    "traditional-village": "Museum",
    "beach": "Beach",
    "waterfall": "Scenic Area",
    "heritage": "Museum",
    "religious": "Church",
    "weaving": "Shopping Center",
    "viewpoint": "Scenic Area",
    "hot-spring": "Swimming Area",
    "cave": "Tunnel",
    "national-park": "Park",
    "airport": "Airport",
    "port": "Anchor",
    "market": "Shopping Center",
    "rice-terrace": "Scenic Area",
    "forest": "Forest",
    "savanna": "Scenic Area",
    "other": "Waypoint",
}


def anchor_waypoints(route_anchor_ids: list, legs: list, nodes: dict, dem) -> list:
    """One waypoint per anchor with its cumulative km (from the legs)."""
    km_at: dict = {}
    for leg in legs:
        km_at.setdefault(leg["from_node"] if not leg["reversed"] else leg["to_node"], leg["start_km"])
        km_at[leg["to_node"] if not leg["reversed"] else leg["from_node"]] = round(leg["start_km"] + leg["length_km"], 3)
    wpts = []
    for nid in route_anchor_ids:
        f = nodes.get(nid)
        if not f:
            continue
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        bits = [f"km {km_at.get(nid, 0):.1f}"]
        for key in ("kind", "resupply", "water", "sleep"):
            if p.get(key):
                bits.append(f"{key}: {p[key]}")
        if p.get("confidence") and p["confidence"] != "verified":
            bits.append(f"position {p['confidence']}")
        desc = " | ".join(bits)
        if p.get("notes"):
            desc += " -- " + p["notes"][:220]
        wpts.append(_wpt(lon, lat, common.clamp_elevation(dem.elevation(lon, lat)), p["name"], desc,
                         SYM_BY_NODE_KIND.get(p.get("kind"), "Waypoint"), f"anchor/{p.get('kind', '')}"))
    return wpts


def poi_waypoints(pois: list, coords: list, dem, max_dist_km: float = 6.0, relevance=("anchor", "highlight", "hazard", "resupply")) -> list:
    """POIs within max_dist_km of the track (cheap nearest-vertex test on a
    decimated track)."""
    step = max(1, len(coords) // 4000)
    sample = coords[::step]
    wpts = []
    for f in pois:
        p = f["properties"]
        if p.get("race_relevance") not in relevance:
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        near = min(common.haversine_m(lon, lat, x, y) for x, y in sample) / 1000.0
        if near > max_dist_km:
            continue
        desc = (p.get("summary") or "")[:300]
        tag = p.get("race_relevance", "")
        if p.get("hike_a_bike"):
            tag += ", hike-a-bike"
        if p.get("confidence") and p["confidence"] != "verified":
            tag += f", position {p['confidence']}"
        wpts.append(_wpt(lon, lat, common.clamp_elevation(dem.elevation(lon, lat)), p["name"], f"[{tag}] {desc}",
                         SYM_BY_POI_CATEGORY.get(p.get("category"), "Waypoint"), f"poi/{p.get('category', '')}"))
    return wpts


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------


def section_segment_ids(route: dict, section: dict) -> list:
    anchors = route["anchors"]
    try:
        i0 = anchors.index(section["from_node"])
        i1 = anchors.index(section["to_node"])
    except ValueError:
        return []
    if i1 <= i0:
        return []
    return route["segments"][i0:i1]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build(args) -> dict:
    data = load_all(Path(args.data), Path(args.config))
    nodes, pois, segments, routes, sections, config = (
        data["nodes"], data["pois"], data["segments"], data["routes"], data["sections"], data["config"],
    )
    dem = common.load_dem(args.dem_dir)
    out = Path(args.out)
    prof_dir = Path(args.profiles_out)
    out.mkdir(parents=True, exist_ok=True)
    prof_dir.mkdir(parents=True, exist_ok=True)
    link = args.link
    manifest: dict = {"generated": dt.date.today().isoformat(), "routes": [], "sections": [], "options": [], "notes": []}

    def emit_profile(pid: str, name: str, chain: dict, prof: dict, anchor_ids: list) -> None:
        km_at = {}
        for leg in chain["legs"]:
            a = leg["to_node"] if leg["reversed"] else leg["from_node"]
            b = leg["from_node"] if leg["reversed"] else leg["to_node"]
            km_at.setdefault(a, leg["start_km"])
            km_at[b] = round(leg["start_km"] + leg["length_km"], 3)
        anchors = []
        for nid in anchor_ids:
            if nid in km_at and nid in nodes:
                anchors.append({"km": km_at[nid], "name": nodes[nid]["properties"]["name"], "id": nid})
        common.write_json(
            prof_dir / f"{pid}.json",
            {
                "id": pid, "name": name, "points": prof["points"], "anchors": anchors,
                "length_km": round(chain["length_km"], 1), "ascent_m": prof["ascent_m"], "descent_m": prof["descent_m"],
                "min_elev_m": prof["min_elev_m"], "max_elev_m": prof["max_elev_m"],
            },
        )

    main_id = config["main_route"]
    route_ids = [main_id, config.get("ultra_route"), "r-ultra-plus"]
    route_ids = [r for r in route_ids if r and r in routes]
    file_for_route = {main_id: "flores-race-traverse", config.get("ultra_route"): "flores-race-ultra", "r-ultra-plus": "flores-race-ultra-plus"}

    main_chain = None
    for rid in route_ids:
        route = routes[rid]
        chain = chain_segments(route["segments"], segments, nodes, route["anchors"][0])
        prof = profile_for(dem, chain["coords"])
        stats = summarise(chain, prof)
        eles = elevations_for(dem, chain["coords"])
        base = file_for_route.get(rid) or common.slugify(rid)
        desc = (
            f"{route.get('tagline', '')} {stats['length_km']} km, +{stats['ascent_m']} m / -{stats['descent_m']} m, "
            f"unpaved {stats['unpaved_pct']}%, est. hike-a-bike {stats['hike_a_bike_km_est']} km. "
            "Concept status, unscouted: a machine proposal for the scouting team, not a decision."
        ).strip()
        n = write_gpx(out / f"{base}.gpx", route["name"], desc, chain["coords"], eles, [], link)
        entry = {"id": rid, "name": route["name"], "file": f"{base}.gpx", "points": n, **stats}
        if rid == main_id:
            wpts = anchor_waypoints(route["anchors"], chain["legs"], nodes, dem) + poi_waypoints(pois, chain["coords"], dem)
            write_gpx(out / f"{base}-with-pois.gpx", route["name"] + " (with POIs)", desc, chain["coords"], eles, wpts, link)
            entry["file_with_pois"] = f"{base}-with-pois.gpx"
            entry["waypoints"] = len(wpts)
            main_chain = chain
        emit_profile(rid, route["name"], chain, prof, route["anchors"])
        entry["legs"] = [{k: v for k, v in l.items() if k in ("segment", "start_km", "length_km", "geometry_source", "route_profile")} for l in chain["legs"]]
        manifest["routes"].append(entry)
        print(f"route {rid}: {stats['length_km']} km, +{stats['ascent_m']} m, {n} pts, gaps={len(chain['gaps'])}")

    # Sections of the main course
    main_route = routes[main_id]
    cum_km = 0.0
    for sec in sections:
        sids = section_segment_ids(main_route, sec)
        if not sids:
            manifest["notes"].append(f"section {sec['id']} has no segments on {main_id}")
            continue
        chain = chain_segments(sids, segments, nodes, sec["from_node"])
        prof = profile_for(dem, chain["coords"])
        stats = summarise(chain, prof)
        eles = elevations_for(dem, chain["coords"])
        slug = f"flores-race-s{sec['order']:02d}-{common.slugify(sec['title'])}"
        anchors_in = main_route["anchors"][main_route["anchors"].index(sec["from_node"]): main_route["anchors"].index(sec["to_node"]) + 1]
        wpts = anchor_waypoints(anchors_in, chain["legs"], nodes, dem) + poi_waypoints(pois, chain["coords"], dem, max_dist_km=5.0)
        desc = (
            f"Section {sec['order']:02d} of the Flores Race traverse: {sec.get('subtitle', '')}. "
            f"{stats['length_km']} km, +{stats['ascent_m']} m / -{stats['descent_m']} m, starts at km {cum_km:.0f} of the course."
        )
        n = write_gpx(out / "sections" / f"{slug}.gpx", f"S{sec['order']:02d} {sec['title']}", desc, chain["coords"], eles, wpts, link)
        emit_profile(sec["id"], f"{sec['order']:02d} {sec['title']}", chain, prof, anchors_in)
        manifest["sections"].append({
            "id": sec["id"], "order": sec["order"], "title": sec["title"], "from_node": sec["from_node"], "to_node": sec["to_node"],
            "file": f"sections/{slug}.gpx", "points": n, "start_km": round(cum_km, 1), "end_km": round(cum_km + stats["length_km"], 1),
            "hab_expected": sec.get("hab_expected"), "target_km": sec.get("target_km"), **stats,
        })
        cum_km += stats["length_km"]
        print(f"section {sec['order']:02d}: {stats['length_km']} km, +{stats['ascent_m']} m")

    # Options
    for opt in config.get("options", []):
        missing = [s for s in opt["segments"] if s not in segments]
        if missing:
            manifest["notes"].append(f"option {opt['id']}: missing segments {missing}")
            continue
        first = segments[opt["segments"][0]]["properties"]
        # start where the replaced part starts, so orientation matches the course direction
        start = segments[opt["replaces"][0]]["properties"]["from_node"] if opt.get("replaces") and opt["replaces"][0] in segments else first["from_node"]
        chain = chain_segments(opt["segments"], segments, nodes, start)
        prof = profile_for(dem, chain["coords"])
        stats = summarise(chain, prof)
        eles = elevations_for(dem, chain["coords"])
        rep_stats = None
        if opt.get("replaces") and all(s in segments for s in opt["replaces"]):
            rchain = chain_segments(opt["replaces"], segments, nodes, start)
            rprof = profile_for(dem, rchain["coords"])
            rep_stats = summarise(rchain, rprof)
        desc = f"{opt['name']} ({opt['kind']}): {opt.get('summary', '')} {stats['length_km']} km, +{stats['ascent_m']} m."
        if rep_stats:
            desc += f" Replaces {rep_stats['length_km']} km / +{rep_stats['ascent_m']} m of the main course."
        anchor_ids = []
        for leg in chain["legs"]:
            for nid in (leg["from_node"], leg["to_node"]):
                if nid not in anchor_ids:
                    anchor_ids.append(nid)
        wpts = anchor_waypoints(anchor_ids, chain["legs"], nodes, dem) + poi_waypoints(pois, chain["coords"], dem, max_dist_km=5.0)
        n = write_gpx(out / "options" / f"{opt['id']}.gpx", opt["name"], desc, chain["coords"], eles, wpts, link)
        emit_profile(opt["id"], opt["name"], chain, prof, anchor_ids)
        manifest["options"].append({
            "id": opt["id"], "name": opt["name"], "kind": opt["kind"], "sections": opt.get("sections"), "summary": opt.get("summary"),
            "file": f"options/{opt['id']}.gpx", "points": n, "segments": opt["segments"], "replaces": opt.get("replaces"),
            "option": stats, "replaced": rep_stats,
            "delta_km": round(stats["length_km"] - rep_stats["length_km"], 1) if rep_stats else None,
            "delta_ascent_m": (stats["ascent_m"] - rep_stats["ascent_m"]) if rep_stats else None,
        })
        print(f"option {opt['id']}: {stats['length_km']} km (+{stats['ascent_m']} m) vs {rep_stats['length_km'] if rep_stats else '?'} km")

    common.write_json(out / "manifest.json", manifest)
    write_readme(out / "README.md", manifest, link)
    return manifest


def write_readme(path: Path, m: dict, link: str) -> None:
    lines = [
        "# GPX exports of the Flores Race course",
        "",
        f"Generated {m['generated']} by `pipeline/export_gpx.py` from `data/routes.json`, `data/segments.geojson` and",
        "`exports/brochure_config.json`. Every number is derived; nothing is typed. Status of every line: **concept, unscouted**.",
        "",
        "Elevation is SRTM (30 m) sampled every 50 m, smoothed, with a 10 m hysteresis threshold for climbing",
        "(the same rule as the web app). Ride with GPS recomputes elevation from its own terrain data on import,",
        "so expect its figures to differ by a few percent.",
        "",
        "## Course variants",
        "",
        "| Variant | File | km | Climb (m) | Descent (m) | Unpaved | Hike-a-bike est. | Points |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in m["routes"]:
        lines.append(
            f"| {r['name']} | `{r['file']}`" + (f" (+ `{r['file_with_pois']}`)" if r.get("file_with_pois") else "") +
            f" | {r['length_km']:.0f} | {r['ascent_m']:,} | {r['descent_m']:,} | {r['unpaved_pct']}% | {r['hike_a_bike_km_est']} km | {r['points']:,} |"
        )
    lines += ["", "## Sections of the main course", "", "| # | Section | km | Climb (m) | Course km | File |", "|---|---|---|---|---|---|"]
    for s in m["sections"]:
        lines.append(f"| {s['order']:02d} | {s['title']} | {s['length_km']:.0f} | {s['ascent_m']:,} | {s['start_km']:.0f}–{s['end_km']:.0f} | `{s['file']}` |")
    lines += ["", "## Optional loops and alternatives", "", "| Option | Kind | km | Climb (m) | Replaces (km / m) | Δ km | File |", "|---|---|---|---|---|---|---|"]
    for o in m["options"]:
        rep = o["replaced"]
        lines.append(
            f"| {o['name']} | {o['kind']} | {o['option']['length_km']:.0f} | {o['option']['ascent_m']:,} | "
            + (f"{rep['length_km']:.0f} / {rep['ascent_m']:,}" if rep else "–")
            + f" | {o['delta_km']:+.0f} | `{o['file']}` |"
        )
    lines += [
        "",
        "## Importing into Ride with GPS",
        "",
        "1. Open <https://ridewithgps.com/routes/new> (the route planner) while logged in.",
        "2. Click **Import** (top of the left panel) → **Upload File** → choose one GPX from this folder → **Add to Planner**.",
        "   The whole track appears; Ride with GPS snaps nothing and recomputes elevation and surface where it can.",
        "3. Give it a name (for example `Flores Race — Traverse (concept)`), set the visibility, **Save**.",
        "4. Repeat for the section files and for each option file. Put them in a Collection named `Flores Race`.",
        "5. Alternative: the **Upload** page (left toolbar on the dashboard) accepts several files at once; choose *Save as Route*.",
        "",
        "The `*-with-pois.gpx` variant carries the anchors and key points of interest as waypoints; the planner turns them",
        "into POIs you can edit. Import the plain file if you prefer a clean map.",
        "",
        f"Planner and source data: {link}",
    ]
    if m.get("notes"):
        lines += ["", "## Notes", ""] + [f"- {n}" for n in m["notes"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--config", default="exports/brochure_config.json")
    ap.add_argument("--dem-dir", default=".cache/dem")
    ap.add_argument("--out", default="exports/gpx")
    ap.add_argument("--profiles-out", default="docs/brochure/data/profiles")
    ap.add_argument("--link", default="https://github.com/technicaloutdoor/Flores-Race")
    return ap


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
