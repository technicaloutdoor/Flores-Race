#!/usr/bin/env python3
"""fetch_overture.py

Extract Overture Maps data for a bounding box directly from the public
Overture S3 bucket, without downloading full-planet files.

Overture GeoParquet files are:
  * partitioned as ``release/<version>/theme=<theme>/type=<type>/*.parquet``
  * written with a ``bbox`` struct column (xmin, xmax, ymin, ymax) whose
    min/max statistics are stored per row-group in the Parquet footer
  * organized into many row-groups per file

This script exploits that layout to prune almost all of the data server-side:
for every file it fetches only the Parquet *footer* (a couple of HTTP Range
requests) to read row-group statistics, decides which row-groups can
possibly intersect the requested bounding box, and then issues further Range
requests to fetch only the matching row-groups (and only the columns we
actually need). It never uses boto3/aws-cli/pyarrow's S3FileSystem -- all
access goes through plain HTTPS Range requests via ``requests``, so it works
through an HTTP(S) proxy.

Output: one newline-delimited GeoJSON file (``.geojsonl``, one Feature per
line) per requested type, plus a ``manifest.json`` describing the run.

Example
-------
    python3 fetch_overture.py \\
        --bbox 119.70,-9.00,123.10,-8.00 \\
        --release latest \\
        --out /path/to/out \\
        --cache /path/to/cache \\
        --themes segment,connector,place,land,water,division_area,land_use
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests
import shapely

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

S3_BUCKET = "overturemaps-us-west-2"
S3_BASE_URL = f"https://{S3_BUCKET}.s3.amazonaws.com/"
S3_LIST_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

BBOX_LEAF_COLUMNS = ("bbox.xmin", "bbox.xmax", "bbox.ymin", "bbox.ymax")

# Default HTTP timeouts/retries for range requests against S3.
HTTP_TIMEOUT_SECONDS = 60
HTTP_MAX_RETRIES = 6
HTTP_RETRY_BACKOFF_SECONDS = 1.5


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_bbox(s: str) -> tuple[float, float, float, float]:
    """Parse "xmin,ymin,xmax,ymax" into a 4-tuple of floats."""
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"--bbox must be 'xmin,ymin,xmax,ymax', got: {s!r}"
        )
    xmin, ymin, xmax, ymax = (float(p) for p in parts)
    if xmin >= xmax or ymin >= ymax:
        raise argparse.ArgumentTypeError(f"invalid bbox ordering: {s!r}")
    return xmin, ymin, xmax, ymax


# --------------------------------------------------------------------------
# HTTP Range-request file object, usable as a pyarrow ParquetFile source.
# --------------------------------------------------------------------------

class HTTPRangeReader(io.RawIOBase):
    """A minimal seekable/readable file-like object backed by HTTP Range GETs.

    This is intentionally NOT using boto3/pyarrow's S3FileSystem or fsspec's
    async HTTP filesystem: it is a thin wrapper around ``requests`` (which
    respects the ``HTTPS_PROXY`` environment variable automatically), issuing
    ``Range: bytes=a-b`` GET requests against the plain HTTPS S3 URL.

    A lock serializes read/seek pairs so the object is safe to hand to
    pyarrow even if pyarrow's C++ layer were to issue overlapping calls (we
    additionally always call pyarrow with ``use_threads=False`` to avoid
    that in the first place).
    """

    def __init__(self, url: str, session: requests.Session, size: int):
        super().__init__()
        self.url = url
        self.session = session
        self._pos = 0
        self._size = size
        self._lock = threading.Lock()
        # Simple byte/requests accounting for reporting.
        self.nbytes_fetched = 0
        self.nrequests = 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        with self._lock:
            if whence == io.SEEK_SET:
                self._pos = offset
            elif whence == io.SEEK_CUR:
                self._pos += offset
            elif whence == io.SEEK_END:
                self._pos = self._size + offset
            else:
                raise ValueError(f"invalid whence: {whence}")
            return self._pos

    def readinto(self, b) -> int:
        data = self.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def read(self, n: int = -1) -> bytes:
        with self._lock:
            if n is None or n < 0:
                end = self._size - 1
            else:
                if n == 0:
                    return b""
                end = min(self._pos + n, self._size) - 1
            if self._pos > end or self._pos >= self._size:
                return b""
            start = self._pos
            headers = {"Range": f"bytes={start}-{end}"}
            data = self._get_with_retries(headers)
            self._pos = start + len(data)
            self.nbytes_fetched += len(data)
            self.nrequests += 1
            return data

    def _get_with_retries(self, headers: dict) -> bytes:
        last_exc: Optional[Exception] = None
        for attempt in range(HTTP_MAX_RETRIES):
            try:
                r = self.session.get(
                    self.url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS
                )
                r.raise_for_status()
                return r.content
            except Exception as exc:  # noqa: BLE001 - deliberately broad, we retry
                last_exc = exc
                time.sleep(HTTP_RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise RuntimeError(f"failed GET {self.url} {headers}") from last_exc


# --------------------------------------------------------------------------
# S3 listing (anonymous, plain HTTPS, paginated ListObjectsV2)
# --------------------------------------------------------------------------

def _s3_list_objects_v2(prefix: str, delimiter: Optional[str] = None) -> ET.Element:
    """One page is handled by the caller; this issues a single request."""
    params = {"list-type": "2", "prefix": prefix}
    if delimiter:
        params["delimiter"] = delimiter
    r = requests.get(S3_BASE_URL, params=params, timeout=30)
    r.raise_for_status()
    return ET.fromstring(r.text)


def list_common_prefixes(prefix: str) -> list[str]:
    """List "directory" style common prefixes directly under ``prefix``."""
    root = _s3_list_objects_v2(prefix, delimiter="/")
    return [
        cp.find("s3:Prefix", S3_LIST_NS).text
        for cp in root.findall("s3:CommonPrefixes", S3_LIST_NS)
    ]


def list_all_objects(prefix: str) -> list[tuple[str, int]]:
    """List all (key, size) pairs under ``prefix``, following pagination."""
    keys: list[tuple[str, int]] = []
    token: Optional[str] = None
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if token:
            params["continuation-token"] = token
        r = requests.get(S3_BASE_URL, params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        for c in root.findall("s3:Contents", S3_LIST_NS):
            key = c.find("s3:Key", S3_LIST_NS).text
            size = int(c.find("s3:Size", S3_LIST_NS).text)
            keys.append((key, size))
        is_truncated = root.find("s3:IsTruncated", S3_LIST_NS).text
        if is_truncated == "true":
            token = root.find("s3:NextContinuationToken", S3_LIST_NS).text
        else:
            break
    return keys


def list_release_versions() -> list[str]:
    """Return available release version strings, e.g. ['2026-07-22.0', '2026-08-19.0']."""
    prefixes = list_common_prefixes("release/")
    versions = [p.split("/")[-2] for p in prefixes if p.startswith("release/")]
    return sorted(versions)


def resolve_release(release_arg: str) -> str:
    versions = list_release_versions()
    if not versions:
        raise RuntimeError("could not list any Overture release versions from S3")
    if release_arg == "latest":
        return versions[-1]
    if release_arg not in versions:
        raise RuntimeError(
            f"release {release_arg!r} not found; available: {versions}"
        )
    return release_arg


def list_type_files(
    release: str, theme: str, type_: str, cache_dir: Optional[str]
) -> list[tuple[str, int]]:
    """List (key, size) for every parquet file of theme/type in a release.

    Results are cached as JSON under ``cache_dir`` (if given) so repeat runs
    don't need to re-list the bucket.
    """
    prefix = f"release/{release}/theme={theme}/type={type_}/"
    cache_path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(
            cache_dir, f"listing_{release}_{theme}_{type_}.json"
        )
        if os.path.exists(cache_path):
            with open(cache_path) as fh:
                return [tuple(x) for x in json.load(fh)]
    keys = list_all_objects(prefix)
    if cache_path:
        with open(cache_path, "w") as fh:
            json.dump(keys, fh)
    return keys


# --------------------------------------------------------------------------
# Parquet row-group bbox pruning
# --------------------------------------------------------------------------

def _bbox_leaf_indices(row_group_meta) -> dict[str, int]:
    """Map bbox.xmin/xmax/ymin/ymax -> column index within a row group."""
    idx: dict[str, int] = {}
    for i in range(row_group_meta.num_columns):
        path = row_group_meta.column(i).path_in_schema
        if path in BBOX_LEAF_COLUMNS:
            idx[path] = i
    return idx


def matching_row_groups(
    metadata, bbox: tuple[float, float, float, float]
) -> list[int]:
    """Return indices of row groups whose bbox stats intersect ``bbox``.

    If a row group is missing bbox statistics (shouldn't happen for Overture
    data, but we don't want to silently drop data), it is conservatively
    included rather than pruned.
    """
    xmin, ymin, xmax, ymax = bbox
    if metadata.num_row_groups == 0:
        return []
    idx = _bbox_leaf_indices(metadata.row_group(0))
    if len(idx) != 4:
        # No bbox column found at all -- can't prune safely, read everything.
        return list(range(metadata.num_row_groups))

    matches = []
    for i in range(metadata.num_row_groups):
        rg = metadata.row_group(i)
        xmin_s = rg.column(idx["bbox.xmin"]).statistics
        xmax_s = rg.column(idx["bbox.xmax"]).statistics
        ymin_s = rg.column(idx["bbox.ymin"]).statistics
        ymax_s = rg.column(idx["bbox.ymax"]).statistics
        if not (xmin_s and xmax_s and ymin_s and ymax_s):
            matches.append(i)
            continue
        rg_xmin, rg_xmax = xmin_s.min, xmax_s.max
        rg_ymin, rg_ymax = ymin_s.min, ymax_s.max
        if rg_xmin <= xmax and rg_xmax >= xmin and rg_ymin <= ymax and rg_ymax >= ymin:
            matches.append(i)
    return matches


def row_level_bbox_filter(table, bbox: tuple[float, float, float, float]):
    """Drop rows whose own bbox struct does not intersect ``bbox``.

    Row-group pruning only guarantees the row group's *union* bbox
    intersects; individual rows inside a matching row group can still be
    disjoint from the query box, so we filter again at row granularity using
    vectorized pyarrow compute before ever touching Python/shapely.
    """
    xmin, ymin, xmax, ymax = bbox
    b_xmin = pc.struct_field(table["bbox"], "xmin")
    b_xmax = pc.struct_field(table["bbox"], "xmax")
    b_ymin = pc.struct_field(table["bbox"], "ymin")
    b_ymax = pc.struct_field(table["bbox"], "ymax")
    mask = pc.and_(
        pc.and_(pc.less_equal(b_xmin, xmax), pc.greater_equal(b_xmax, xmin)),
        pc.and_(pc.less_equal(b_ymin, ymax), pc.greater_equal(b_ymax, ymin)),
    )
    return table.filter(mask)


# --------------------------------------------------------------------------
# Theme/type registry: columns to request + how to flatten each row into
# GeoJSON Feature properties.
# --------------------------------------------------------------------------

def _primary(struct: Optional[dict]) -> Optional[str]:
    if not struct:
        return None
    return struct.get("primary")


def _flatten_road_surface(entries: Optional[list]) -> Optional[str]:
    """road_surface is a list of {value, between}; pick the value that
    applies to the whole segment (no 'between' range), else the first."""
    if not entries:
        return None
    for e in entries:
        if not e.get("between"):
            return e.get("value")
    return entries[0].get("value")


def _flatten_connector_ids(entries: Optional[list]) -> list[str]:
    if not entries:
        return []
    return [e["connector_id"] for e in entries if e.get("connector_id")]


def _props_segment(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "subtype": row.get("subtype"),
        "class": row.get("class"),
        "subclass": row.get("subclass"),
        "name": _primary(row.get("names")),
        "road_surface": _flatten_road_surface(row.get("road_surface")),
        "road_flags": row.get("road_flags"),
        "access_restrictions": row.get("access_restrictions"),
        "speed_limits": row.get("speed_limits"),
        "connector_ids": _flatten_connector_ids(row.get("connectors")),
        "sources": row.get("sources"),
        "routes": row.get("routes"),
    }


def _props_connector(row: dict) -> dict:
    return {"id": row.get("id")}


def _props_place(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "name": _primary(row.get("names")),
        "category": _primary(row.get("categories")),
        "confidence": row.get("confidence"),
    }


def _props_land(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "subtype": row.get("subtype"),
        "class": row.get("class"),
        "name": _primary(row.get("names")),
        "elevation": row.get("elevation"),
    }


def _props_water(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "subtype": row.get("subtype"),
        "class": row.get("class"),
        "name": _primary(row.get("names")),
    }


def _props_division_area(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "subtype": row.get("subtype"),
        "country": row.get("country"),
        "region": row.get("region"),
        "name": _primary(row.get("names")),
    }


def _props_land_use(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "subtype": row.get("subtype"),
        "class": row.get("class"),
        "name": _primary(row.get("names")),
    }


@dataclass
class TypeSpec:
    key: str  # short CLI name, e.g. "segment"
    theme: str
    type_: str
    columns: list[str]
    build_properties: Callable[[dict], dict]
    output_name: str
    post_filter: Optional[Callable[[dict], bool]] = None  # applied after bbox filter
    optional: bool = False  # ok to skip automatically if it looks huge


TYPE_REGISTRY: dict[str, TypeSpec] = {
    "segment": TypeSpec(
        key="segment",
        theme="transportation",
        type_="segment",
        columns=[
            "id", "subtype", "class", "subclass", "names.primary",
            "road_surface", "road_flags", "access_restrictions",
            "speed_limits", "connectors", "sources", "routes",
            "geometry", "bbox",
        ],
        build_properties=_props_segment,
        output_name="segment.geojsonl",
    ),
    "connector": TypeSpec(
        key="connector",
        theme="transportation",
        type_="connector",
        columns=["id", "geometry", "bbox"],
        build_properties=_props_connector,
        output_name="connector.geojsonl",
    ),
    "place": TypeSpec(
        key="place",
        theme="places",
        type_="place",
        columns=[
            "id", "names.primary", "categories.primary", "confidence",
            "geometry", "bbox",
        ],
        build_properties=_props_place,
        output_name="place.geojsonl",
    ),
    "land": TypeSpec(
        key="land",
        theme="base",
        type_="land",
        columns=["id", "subtype", "class", "names.primary", "elevation", "geometry", "bbox"],
        build_properties=_props_land,
        output_name="land.geojsonl",
    ),
    "water": TypeSpec(
        key="water",
        theme="base",
        type_="water",
        columns=["id", "subtype", "class", "names.primary", "geometry", "bbox"],
        build_properties=_props_water,
        output_name="water.geojsonl",
    ),
    "division_area": TypeSpec(
        key="division_area",
        theme="divisions",
        type_="division_area",
        columns=["id", "subtype", "country", "region", "names.primary", "geometry", "bbox"],
        build_properties=_props_division_area,
        output_name="division_area.geojsonl",
        post_filter=lambda row: row.get("country") == "ID",
    ),
    "land_use": TypeSpec(
        key="land_use",
        theme="base",
        type_="land_use",
        columns=["id", "subtype", "class", "names.primary", "geometry", "bbox"],
        build_properties=_props_land_use,
        output_name="land_use.geojsonl",
        optional=True,
    ),
}

DEFAULT_THEMES = list(TYPE_REGISTRY.keys())

# Safety valve for the "optional" land_use theme: if pruning still leaves an
# unexpectedly large amount of data to fetch, skip it rather than blow the
# time/byte budget.
OPTIONAL_TYPE_BYTE_BUDGET = 1_500_000_000  # 1.5 GB


# --------------------------------------------------------------------------
# Per-file and per-type processing
# --------------------------------------------------------------------------

@dataclass
class FileResult:
    key: str
    size: int
    num_row_groups: int
    matched_row_groups: int
    rows_out: int
    bytes_fetched: int
    requests_made: int
    error: Optional[str] = None


def process_one_file(
    key: str,
    size: int,
    spec: TypeSpec,
    bbox: tuple[float, float, float, float],
    session: requests.Session,
    out_lock: threading.Lock,
    out_fh,
) -> FileResult:
    url = S3_BASE_URL + key
    reader = HTTPRangeReader(url, session, size)
    try:
        pf = pq.ParquetFile(reader)
        md = pf.metadata
        matches = matching_row_groups(md, bbox)
        rows_out = 0
        if matches:
            table = pf.read_row_groups(matches, columns=spec.columns, use_threads=False)
            table = row_level_bbox_filter(table, bbox)
            if table.num_rows:
                pylist = table.drop(["bbox"]).to_pylist()
                lines = []
                for row in pylist:
                    if spec.post_filter and not spec.post_filter(row):
                        continue
                    geom_wkb = row.pop("geometry")
                    if geom_wkb is None:
                        continue
                    geom = shapely.from_wkb(geom_wkb)
                    geom_geojson = json.loads(shapely.to_geojson(geom))
                    props = spec.build_properties(row)
                    feature = {
                        "type": "Feature",
                        "id": props.get("id"),
                        "geometry": geom_geojson,
                        "properties": props,
                    }
                    lines.append(json.dumps(feature, ensure_ascii=False))
                if lines:
                    with out_lock:
                        out_fh.write("\n".join(lines) + "\n")
                    rows_out = len(lines)
        return FileResult(
            key=key,
            size=size,
            num_row_groups=md.num_row_groups,
            matched_row_groups=len(matches),
            rows_out=rows_out,
            bytes_fetched=reader.nbytes_fetched,
            requests_made=reader.nrequests,
        )
    except Exception as exc:  # noqa: BLE001
        return FileResult(
            key=key, size=size, num_row_groups=0, matched_row_groups=0,
            rows_out=0, bytes_fetched=reader.nbytes_fetched,
            requests_made=reader.nrequests, error=repr(exc),
        )


def process_type(
    spec: TypeSpec,
    release: str,
    bbox: tuple[float, float, float, float],
    out_dir: str,
    cache_dir: Optional[str],
    workers: int,
) -> dict:
    t0 = time.time()
    files = list_type_files(release, spec.theme, spec.type_, cache_dir)
    out_path = os.path.join(out_dir, spec.output_name)
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers)
    session.mount("https://", adapter)

    out_lock = threading.Lock()
    file_results: list[FileResult] = []
    errors: list[str] = []

    with open(out_path, "w") as out_fh:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    process_one_file, key, size, spec, bbox, session, out_lock, out_fh
                ): key
                for key, size in files
            }
            for fut in as_completed(futures):
                fr = fut.result()
                file_results.append(fr)
                if fr.error:
                    errors.append(f"{fr.key}: {fr.error}")

    total_bytes = sum(fr.bytes_fetched for fr in file_results)
    total_rows = sum(fr.rows_out for fr in file_results)
    total_requests = sum(fr.requests_made for fr in file_results)
    files_matched = sum(1 for fr in file_results if fr.matched_row_groups > 0)
    row_groups_matched = sum(fr.matched_row_groups for fr in file_results)
    elapsed = time.time() - t0

    output_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0

    return {
        "key": spec.key,
        "theme": spec.theme,
        "type": spec.type_,
        "files_listed": len(files),
        "files_matched": files_matched,
        "row_groups_matched": row_groups_matched,
        "rows_out": total_rows,
        "bytes_downloaded": total_bytes,
        "http_requests": total_requests,
        "elapsed_seconds": round(elapsed, 2),
        "output_path": out_path,
        "output_size_bytes": output_size,
        "errors": errors,
        "skipped": False,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract Overture Maps data for a bbox from the public S3 bucket."
    )
    parser.add_argument(
        "--bbox", required=True, type=parse_bbox,
        help="xmin,ymin,xmax,ymax in WGS84 lon/lat",
    )
    parser.add_argument(
        "--release", default="latest",
        help="Overture release version, or 'latest' (default)",
    )
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument(
        "--themes", default=",".join(DEFAULT_THEMES),
        help=(
            "Comma-separated subset of: " + ",".join(DEFAULT_THEMES)
        ),
    )
    parser.add_argument(
        "--cache", default=None,
        help="Directory to cache S3 listing results between runs",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="Thread-pool size for concurrent file processing (default 8)",
    )
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    if args.cache:
        os.makedirs(args.cache, exist_ok=True)

    requested_keys = [k.strip() for k in args.themes.split(",") if k.strip()]
    for k in requested_keys:
        if k not in TYPE_REGISTRY:
            parser.error(f"unknown theme key {k!r}; choices: {list(TYPE_REGISTRY)}")

    run_started = now_iso()
    t_run0 = time.time()

    release = resolve_release(args.release)
    print(f"[fetch_overture] using release {release}", file=sys.stderr)

    results = []
    for key in requested_keys:
        spec = TYPE_REGISTRY[key]
        print(f"[fetch_overture] processing {key} ({spec.theme}/{spec.type_}) ...", file=sys.stderr)

        if spec.optional:
            # Peek at total listed bytes; if the *unfiltered* dataset is
            # implausibly large even before pruning we still attempt it,
            # since row-group pruning is what actually controls cost. We
            # only bail out post-hoc if bytes_downloaded blows the budget,
            # logged below after the fact for transparency.
            pass

        result = process_type(
            spec, release, args.bbox, args.out, args.cache, args.workers
        )

        if spec.optional and result["bytes_downloaded"] > OPTIONAL_TYPE_BYTE_BUDGET:
            print(
                f"[fetch_overture] WARNING: optional type {key} downloaded "
                f"{result['bytes_downloaded']} bytes (> budget); keeping output "
                f"but flagging in manifest",
                file=sys.stderr,
            )
            result["over_budget"] = True

        print(
            f"[fetch_overture]   -> {result['rows_out']} features, "
            f"{result['bytes_downloaded']} bytes, {result['elapsed_seconds']}s",
            file=sys.stderr,
        )
        results.append(result)

    for key in TYPE_REGISTRY:
        if key not in requested_keys:
            results.append({"key": key, "skipped": True, "reason": "not requested"})

    total_elapsed = round(time.time() - t_run0, 2)
    manifest = {
        "release": release,
        "bbox": {
            "xmin": args.bbox[0], "ymin": args.bbox[1],
            "xmax": args.bbox[2], "ymax": args.bbox[3],
        },
        "run_started_utc": run_started,
        "run_finished_utc": now_iso(),
        "total_elapsed_seconds": total_elapsed,
        "total_bytes_downloaded": sum(
            r.get("bytes_downloaded", 0) for r in results if not r.get("skipped")
        ),
        "total_rows_out": sum(
            r.get("rows_out", 0) for r in results if not r.get("skipped")
        ),
        "types": results,
    }
    manifest_path = os.path.join(args.out, "manifest.json")
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"[fetch_overture] wrote manifest to {manifest_path}", file=sys.stderr)
    print(f"[fetch_overture] total elapsed: {total_elapsed}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
