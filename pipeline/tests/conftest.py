"""Shared pytest configuration for pipeline/tests.

Puts pipeline/ (the directory *containing* tests/) on sys.path so test
modules can ``import common``, ``import validate``, etc. the same way the
CLIs do -- no package/__init__.py wrapping, matching the rest of pipeline/.

DEM- and regency-dependent tests are opt-in via environment variables
(pointing at the real SRTM tiles / geoBoundaries extract fetched by
fetch_dem.py / fetch_boundaries.py) so the suite stays runnable -- skipping
rather than failing -- anywhere those large downloads are not present.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent.parent
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))


@pytest.fixture()
def dem_dir() -> str:
    path = os.environ.get("FLORES_RACE_TEST_DEM_DIR")
    if not path or not Path(path).is_dir():
        pytest.skip(
            "FLORES_RACE_TEST_DEM_DIR not set to a directory of .hgt tiles "
            "(see pipeline/fetch_dem.py); skipping DEM-dependent test"
        )
    return path


@pytest.fixture()
def regencies_path() -> str:
    path = os.environ.get("FLORES_RACE_TEST_REGENCIES")
    if not path or not Path(path).is_file():
        pytest.skip(
            "FLORES_RACE_TEST_REGENCIES not set to a geoBoundaries Flores "
            "regency GeoJSON (see pipeline/fetch_boundaries.py); skipping"
        )
    return path
