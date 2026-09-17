#!/usr/bin/env python3
"""
Download and filter geoBoundaries for Flores regencies and subdistricts.
"""
import json
import sys
from pathlib import Path
import requests
from shapely.geometry import shape, box
from shapely.ops import unary_union
from pyproj import Transformer


# Flores regencies (with possible spelling variants)
REGENCY_PATTERNS = [
    "manggarai barat",
    "manggarai",
    "manggarai timur",
    "ngada",
    "nagekeo",
    "ende",
    "sikka",
    "flores timur",
]


def match_regency_name(shape_name):
    """Check if a shapeName matches a Flores regency pattern."""
    name_lower = shape_name.lower()
    for pattern in REGENCY_PATTERNS:
        if pattern in name_lower:
            return True
    return False


def fetch_boundaries(out_dir):
    """Download and filter regency/subdistrict boundaries."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print("Fetching ADM2 (regencies) from geoBoundaries...")
    adm2_url = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/IDN/ADM2/geoBoundaries-IDN-ADM2_simplified.geojson"

    try:
        resp = requests.get(adm2_url, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        print(f"ERROR fetching ADM2: {e}", file=sys.stderr)
        return

    adm2_data = resp.json()
    print(f"  Loaded {len(adm2_data['features'])} ADM2 features")

    # Filter to Flores regencies
    flores_regencies = []
    regency_shapes = []

    for feat in adm2_data["features"]:
        shape_name = feat["properties"].get("shapeName", "")
        if match_regency_name(shape_name):
            flores_regencies.append(feat)
            regency_shapes.append(shape(feat["geometry"]))

    print(f"\nFiltered to {len(flores_regencies)} Flores regencies:")

    # Compute stats
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)

    for feat in flores_regencies:
        props = feat["properties"]
        shape_name = props.get("shapeName", "")
        shape_id = props.get("shapeID", "")
        geom = shape(feat["geometry"])

        # Number of polygon parts
        if geom.geom_type == "Polygon":
            num_parts = 1
        elif geom.geom_type == "MultiPolygon":
            num_parts = len(geom.geoms)
        else:
            num_parts = 0

        # Area in km2 using equal-area projection
        area_km2 = geom.area * 1.0e-6 * 111.0 * 111.0  # Rough approximation for small areas
        # Better: compute area in projected coordinates
        try:
            from shapely.ops import transform as shapely_transform
            geom_proj = shapely_transform(transformer.transform, geom)
            area_km2 = geom_proj.area / 1e6
        except:
            # Fallback: use approximate area
            area_km2 = geom.area * 1.0e-6 * 111.0 * 111.0

        print(f"  {shape_name:30} ({shape_id:20}): {area_km2:8.0f} km2, {num_parts} part(s)")

    # Overall bbox
    union_geom = unary_union(regency_shapes)
    bbox = union_geom.bounds  # minx, miny, maxx, maxy
    print(f"\nOverall Flores bbox: lon {bbox[0]:.2f}..{bbox[2]:.2f}, lat {bbox[1]:.2f}..{bbox[3]:.2f}")

    # Write filtered ADM2
    output_file = out_path / "flores_regencies.geojson"
    with open(output_file, "w") as f:
        json.dump({"type": "FeatureCollection", "features": flores_regencies}, f)
    print(f"Wrote {output_file}")

    # Fetch ADM3 (subdistricts)
    print("\nFetching ADM3 (subdistricts) from geoBoundaries...")
    adm3_url = "https://raw.githubusercontent.com/wmgeolab/geoBoundaries/main/releaseData/gbOpen/IDN/ADM3/geoBoundaries-IDN-ADM3_simplified.geojson"

    try:
        resp = requests.get(adm3_url, timeout=120)
        resp.raise_for_status()
        content = resp.text
    except Exception as e:
        print(f"  WARNING: Could not fetch ADM3 from raw.githubusercontent.com: {e}", file=sys.stderr)
        # Try media.githubusercontent.com
        adm3_url_media = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/IDN/ADM3/geoBoundaries-IDN-ADM3_simplified.geojson"
        try:
            resp = requests.get(adm3_url_media, timeout=120)
            resp.raise_for_status()
            content = resp.text
        except Exception as e2:
            print(f"  ERROR: Could not fetch ADM3 from media either: {e2}", file=sys.stderr)
            return

    # Check for LFS pointer
    if content.startswith("version https://git-lfs"):
        print("  File is an LFS pointer, fetching from media.githubusercontent.com...")
        adm3_url = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/IDN/ADM3/geoBoundaries-IDN-ADM3_simplified.geojson"
        try:
            resp = requests.get(adm3_url, timeout=120)
            resp.raise_for_status()
            content = resp.text
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            return

    adm3_data = json.loads(content)
    print(f"  Loaded {len(adm3_data['features'])} ADM3 features")

    # Filter to those intersecting Flores regencies
    flores_box = box(*bbox)
    flores_subdistricts = []

    for feat in adm3_data["features"]:
        geom = shape(feat["geometry"])
        if geom.intersects(flores_box):
            flores_subdistricts.append(feat)

    print(f"Filtered to {len(flores_subdistricts)} subdistricts intersecting Flores")

    output_file = out_path / "flores_subdistricts.geojson"
    with open(output_file, "w") as f:
        json.dump({"type": "FeatureCollection", "features": flores_subdistricts}, f)
    print(f"Wrote {output_file}")


if __name__ == "__main__":
    out_dir = "raw/boundaries"
    fetch_boundaries(out_dir)
