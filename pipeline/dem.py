#!/usr/bin/env python3
"""
DEM class for loading and interpolating SRTM HGT tiles.
"""
import struct
from pathlib import Path
import numpy as np
from pyproj import Geod


class DEM:
    """
    SRTM DEM loaded from HGT tiles (1-arc-second resolution).
    HGT format: 3601 x 3601 big-endian signed int16.
    Row 0 is NORTH edge, row 3600 is SOUTH edge.
    """

    def __init__(self, dem_dir):
        """Initialize with path to DEM tile directory."""
        self.dem_dir = Path(dem_dir)
        self._tiles = {}  # Cache: (lat_int, lon_int) -> array
        self.arc_sec_per_pixel = 1.0 / 3600.0  # ~30.87 m at equator

    def _tile_for_coord(self, lon, lat):
        """Return tile name for given lon/lat."""
        lat_int = int(np.floor(lat))
        lon_int = int(np.floor(lon))
        lat_str = f"S{abs(lat_int):02d}" if lat_int < 0 else f"N{lat_int:02d}"
        lon_str = f"E{lon_int:03d}" if lon_int >= 0 else f"W{abs(lon_int):03d}"
        return f"{lat_str}{lon_str}"

    def _load_tile(self, lat_int, lon_int):
        """Load HGT tile (cached)."""
        key = (lat_int, lon_int)
        if key in self._tiles:
            return self._tiles[key]

        tile_name = self._tile_for_coord(lon_int + 0.5, lat_int + 0.5)
        hgt_file = self.dem_dir / f"{tile_name}.hgt"

        if not hgt_file.exists():
            return None

        with open(hgt_file, "rb") as f:
            data = f.read()

        # 3601 x 3601 x 2 bytes = 25,934,402 bytes
        arr = np.frombuffer(data, dtype=">i2").reshape((3601, 3601))
        self._tiles[key] = arr
        return arr

    def elevation(self, lon, lat):
        """
        Get elevation at lon/lat with bilinear interpolation.
        Returns: elevation (m), or None if void/missing.
        """
        lat_int = int(np.floor(lat))
        lon_int = int(np.floor(lon))

        # Load tile
        tile = self._load_tile(lat_int, lon_int)
        if tile is None:
            return None

        # Position within tile: (0,0) is NW corner
        # Rows go S (latitude decreases downward)
        # Cols go E (longitude increases rightward)
        frac_lon = lon - lon_int  # 0..1
        frac_lat = 1.0 - (lat - lat_int)  # 0..1 (inverted: rows increase southward)

        col = frac_lon * 3600.0
        row = frac_lat * 3600.0

        col_int = int(np.floor(col))
        row_int = int(np.floor(row))
        col_frac = col - col_int
        row_frac = row - row_int

        # Clamp to tile bounds
        col_int = np.clip(col_int, 0, 3599)
        row_int = np.clip(row_int, 0, 3599)

        # Bilinear interpolation
        z00 = tile[row_int, col_int]
        z01 = tile[row_int, col_int + 1]
        z10 = tile[row_int + 1, col_int]
        z11 = tile[row_int + 1, col_int + 1]

        # Void check
        if any(v == -32768 for v in [z00, z01, z10, z11]):
            return None

        z0 = z00 * (1 - col_frac) + z01 * col_frac
        z1 = z10 * (1 - col_frac) + z11 * col_frac
        z = z0 * (1 - row_frac) + z1 * row_frac

        return float(z)

    def sample_line(self, coords, step_m=50):
        """
        Sample elevation along a polyline.
        coords: list of (lon, lat) tuples.
        step_m: distance step in meters.
        Returns: list of (distance_m, elevation_m) tuples.
        """
        geod = Geod(ellps="WGS84")
        samples = []
        cumulative_dist = 0.0

        for i in range(len(coords) - 1):
            lon1, lat1 = coords[i]
            lon2, lat2 = coords[i + 1]

            # Get line info
            fwd_az, back_az, dist_m = geod.inv(lon1, lat1, lon2, lat2)

            # Sample points along segment
            num_steps = max(1, int(np.ceil(dist_m / step_m)))
            for j in range(num_steps + 1):
                if j == 0 and i > 0:
                    continue  # Skip duplicate start point
                t = min(1.0, j / num_steps)
                lon = lon1 + t * (lon2 - lon1)
                lat = lat1 + t * (lat2 - lat1)
                dist = cumulative_dist + t * dist_m
                elev = self.elevation(lon, lat)
                samples.append((dist, elev))

            cumulative_dist += dist_m

        return samples


if __name__ == "__main__":
    # Sanity checks
    dem = DEM("raw/dem")

    checks = [
        ("Kelimutu summit", 121.82, -8.77, 1500, 1650),
        ("Labuan Bajo harbour", 119.88, -8.49, 0, 50),
        ("Ruteng town", 120.47, -8.61, 1100, 1250),
        ("Sea (should be void)", 121.0, -8.98, None, None),
    ]

    print("DEM elevation sanity checks:")
    for name, lon, lat, elev_min, elev_max in checks:
        elev = dem.elevation(lon, lat)
        if elev_min is None:
            status = "void/missing" if elev is None else f"{elev} m (expected void)"
        else:
            if elev is None:
                status = "void/missing (expected land)"
            elif elev_min <= elev <= elev_max:
                status = f"OK ({elev:.0f} m)"
            else:
                status = f"OUT OF RANGE ({elev:.0f} m, expected {elev_min}-{elev_max})"
        print(f"  {name:25} ({lon:8.2f}, {lat:7.2f}): {status}")
