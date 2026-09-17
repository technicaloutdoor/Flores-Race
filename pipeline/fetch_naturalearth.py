#!/usr/bin/env python3
"""
Download and filter Natural Earth datasets for Flores region.
"""
import json
import sys
from pathlib import Path
import requests
from shapely.geometry import shape, box


# Flores extent (with margin)
FLORES_BBOX = (119.5, -9.2, 123.5, -7.8)  # minx, miny, maxx, maxy


def fetch_naturalearth_file(url, name, out_dir, clip_to_bbox=False):
    """Download and filter a Natural Earth GeoJSON file."""
    print(f"Downloading {name}...")

    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return None

    data = resp.json()
    print(f"  Loaded {len(data['features'])} features")

    # Filter to Flores bbox
    flores_box = box(*FLORES_BBOX)
    filtered = []
    flores_names = set()

    for feat in data["features"]:
        geom = shape(feat["geometry"])
        if geom.intersects(flores_box):
            if clip_to_bbox:
                # Clip to bbox
                clipped_geom = geom.intersection(flores_box)
                if not clipped_geom.is_empty:
                    feat = feat.copy()
                    feat["geometry"] = clipped_geom.__geo_interface__
                    filtered.append(feat)
            else:
                filtered.append(feat)

            # Collect place names
            if "name" in feat.get("properties", {}):
                flores_names.add(feat["properties"]["name"])

    print(f"  Filtered to {len(filtered)} features in Flores bbox")

    if flores_names:
        print(f"  Names found: {', '.join(sorted(flores_names)[:10])}")
        if len(flores_names) > 10:
            print(f"    ... and {len(flores_names) - 10} more")

    # Write output
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    base_name = name.split("/")[-1]
    output_file = out_path / base_name

    with open(output_file, "w") as f:
        json.dump({"type": "FeatureCollection", "features": filtered}, f)
    print(f"  Wrote {output_file}")

    return len(filtered)


def fetch_naturalearth(out_dir):
    """Download and filter Natural Earth datasets."""
    base_url = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"

    files = [
        ("ne_10m_populated_places.geojson", False),
        ("ne_10m_minor_islands.geojson", False),
        ("ne_10m_land.geojson", True),
    ]

    print("Fetching Natural Earth datasets for Flores region...\n")

    for filename, clip_bbox in files:
        url = f"{base_url}/{filename}"
        fetch_naturalearth_file(url, filename, out_dir, clip_bbox)
        print()


if __name__ == "__main__":
    out_dir = "raw/naturalearth"
    fetch_naturalearth(out_dir)
