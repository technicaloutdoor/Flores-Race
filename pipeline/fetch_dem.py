#!/usr/bin/env python3
"""
Fetch SRTM/Skadi DEM tiles from AWS S3.
Covers Flores island: lon 119-123 E, lat 8-9 S.
"""
import argparse
import gzip
import sys
from pathlib import Path
import requests


# Flores DEM coverage: 8 tiles
FLORES_TILES = [
    "S09E119", "S09E120", "S09E121", "S09E122",
    "S08E119", "S08E120", "S08E121", "S08E122",
]

BASE_URL = "https://elevation-tiles-prod.s3.amazonaws.com/skadi"


def fetch_dem_tiles(out_dir, tiles=None, verbose=False):
    """Download and gunzip HGT tiles."""
    if tiles is None:
        tiles = FLORES_TILES

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    failed = []
    fetched = []
    skipped = []

    for tile in tiles:
        lat = tile[:3]  # S09, S08, etc.
        output_file = out_path / f"{tile}.hgt"

        # Skip if already present
        if output_file.exists():
            skipped.append(tile)
            if verbose:
                print(f"Skipping {tile} (already exists)")
            continue

        url = f"{BASE_URL}/{lat}/{tile}.hgt.gz"
        try:
            if verbose:
                print(f"Fetching {tile}...")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()

            # Gunzip and save
            decompressed = gzip.decompress(resp.content)
            output_file.write_bytes(decompressed)
            fetched.append(tile)
            if verbose:
                print(f"  -> {output_file.name} ({len(decompressed) / 1e6:.1f} MB)")
        except Exception as e:
            failed.append((tile, str(e)))
            print(f"ERROR: {tile}: {e}", file=sys.stderr)

    return {
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch SRTM/Skadi DEM tiles for Flores.")
    parser.add_argument("--out", type=str, default="raw/dem", help="Output directory")
    parser.add_argument("--tiles", nargs="+", default=None, help="Tile list")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()
    result = fetch_dem_tiles(args.out, args.tiles, args.verbose)

    print(f"\nDEM fetch complete:")
    print(f"  Fetched: {len(result['fetched'])} ({', '.join(result['fetched'])})")
    print(f"  Skipped: {len(result['skipped'])} ({', '.join(result['skipped'])})")
    if result['failed']:
        print(f"  Failed: {len(result['failed'])}")
        for tile, err in result['failed']:
            print(f"    {tile}: {err}")
