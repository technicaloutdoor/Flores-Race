#!/usr/bin/env python3
"""
Check terrarium terrain tile coverage for Flores region.
"""
import math
import requests


def lng_lat_to_tile(lon, lat, zoom):
    """Convert WGS84 lon/lat to Web Mercator XYZ tile coordinates."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def get_tile_range(min_lon, min_lat, max_lon, max_lat, zoom):
    """Get XYZ tile range covering bbox."""
    x_min, y_max = lng_lat_to_tile(min_lon, min_lat, zoom)
    x_max, y_min = lng_lat_to_tile(max_lon, max_lat, zoom)
    return x_min, x_max, y_min, y_max


def check_terrain_tiles():
    """Check terrarium tile coverage."""
    bbox = (119.7, -9.0, 123.1, -8.0)  # minx, miny, maxx, maxy
    min_lon, min_lat, max_lon, max_lat = bbox

    print(f"Checking terrarium terrain tiles for bbox {bbox}")
    print(f"URL base: https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{{z}}/{{x}}/{{y}}.png\n")

    base_url = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium"

    for zoom in [10, 11, 12]:
        x_min, x_max, y_min, y_max = get_tile_range(min_lon, min_lat, max_lon, max_lat, zoom)
        tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)

        print(f"Zoom {zoom}:")
        print(f"  Tile range: x={x_min}..{x_max}, y={y_min}..{y_max}")
        print(f"  Total tiles: {tile_count}")

        # Sample 3 tiles
        samples = [
            (x_min, y_min),
            ((x_min + x_max) // 2, (y_min + y_max) // 2),
            (x_max, y_max),
        ]

        sample_results = []
        for x, y in samples:
            url = f"{base_url}/{zoom}/{x}/{y}.png"
            try:
                resp = requests.head(url, timeout=10)
                status = resp.status_code
                sample_results.append((x, y, status))
                print(f"    Sample z={zoom}/x={x}/y={y}: {status}")
            except Exception as e:
                print(f"    Sample z={zoom}/x={x}/y={y}: ERROR ({e})")
                sample_results.append((x, y, "ERROR"))

        print()


if __name__ == "__main__":
    check_terrain_tiles()
