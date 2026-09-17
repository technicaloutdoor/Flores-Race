#!/usr/bin/env python3
"""crosscheck_gazetteer.py

Offline, independent check of the curated ``data/nodes.geojson`` and
``data/pois.geojson`` coordinates (and any ``elevation_m`` claims) against a
local, OSM-derived Overture Maps extract plus the project's SRTM DEM.

This exists because the team's web-search budget runs out long before its
curiosity does: every curated feature was placed by hand from web sources,
and someone still has to ask "does an independent, differently-sourced
dataset agree this is roughly the right spot?" without spending another web
search per feature. Overture's ``place`` / ``land`` / ``water`` /
``division_area`` / ``land_use`` layers (see ``pipeline/fetch_overture.py``)
carry thousands of named points and polygons for the same island -- villages
via their "Kantor Desa <name>" government office or their desa/kelurahan
polygon, peaks and volcanoes, lakes, beaches, hot springs, waterfalls, caves
-- independent of whatever web source the curated coordinate came from.

METHOD (see docs/data-model.md for the fields this reads)
  1. Build a flat gazetteer from the Overture extract: one entry per named
     point/polygon, with a normalised name (``normalise_name``) and a coarse
     "bucket" describing what kind of real-world thing it is (a peak, a
     lake, a village polygon, a generic place, ...).
  2. For every curated node/POI, normalise its name (and ``local_name`` if
     present) the same way, and look for gazetteer entries whose normalised
     name matches exactly or fuzzily (``difflib`` ratio >= 0.85, or one name
     contained in the other at length >= 4).
  3. Prefer matches whose bucket is compatible with the curated feature's
     ``kind``/``category`` (a volcano should match a peak, not a hotel named
     after it) -- see ``NODE_COMPAT`` / ``POI_COMPAT``. Among compatible
     matches, the *nearest* one (haversine) is "the" match: Overture is noisy
     enough (several identically-named POIs at unrelated coordinates is
     common) that string similarity alone is not a safe ranking signal, only
     a filter.
  4. Classify the curated coordinate against that match's distance into
     confirmed / plausible / suspect / wrong / unmatched (``classify``), with
     one override: a village-type node whose match is a division polygon
     (desa/kelurahan) and that actually *contains* the curated point is
     "confirmed" outright, regardless of centroid distance -- a point near
     the edge of a large, oddly-shaped village polygon can be many hundred
     metres from the polygon's centroid and still be correctly inside it.
  5. Independently, when a DEM is available: compare any claimed
     ``elevation_m`` against the DEM value at the curated point, and for
     volcano/crater-lake features, grid-search the DEM within 1.5 km for a
     higher point, suggesting a snap when the curated point sits well off
     the true local summit.

This is a report, not a gate: it always exits 0 (``pipeline/validate.py`` is
the schema/referential-integrity gate; this is a second, independent opinion
on geolocation, meant to be read by a human).

USAGE
    python3 crosscheck_gazetteer.py --data data --overture-dir DIR \\
        --dem-dir DIR --out report.md [--json report.json]

``--dem-dir`` is optional: omit it (or point it at a directory with no usable
tiles) to skip the DEM-dependent checks -- the location cross-check still
runs.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from shapely.geometry import Point, shape

import common

# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

#: Multi-word generic terms that must be removed as a unit -- each word on
#: its own is either meaningful elsewhere or, per BRIEF.md, only generic in
#: this combination.
GENERIC_PHRASES: tuple[str, ...] = (
    "taman nasional",
    "national park",
    "air terjun",
    "air panas",
    "hot springs",
    "hot spring",
)

#: Single generic words stripped from anywhere in the name (word-boundary
#: matched, so they never bite into a compound like "Kelimutu" or
#: "Wolojita"). Indonesian list per BRIEF.md, plus "kantor" -- not in the
#: brief's list verbatim, but needed so "Kantor Kelurahan <village>" collapses
#: to "<village>" the same way "Kantor Desa <village>" does; "kelurahan" is
#: already in the brief's list, so this only extends the *office* half of the
#: same pattern, never a bare toponym.
GENERIC_WORDS: frozenset[str] = frozenset(
    {
        # Indonesian
        "gunung", "poco", "wolo", "ile", "ili", "keli", "danau", "pantai",
        "desa", "kelurahan", "kampung", "kantor", "pulau", "gua", "bukit",
        # "sawah" (rice paddy), "batu" (stone/rock) and "benteng" (fort) are
        # not in BRIEF.md's list verbatim, but are the same pattern as
        # "danau"/"pantai": each is a bare, common Indonesian noun for a
        # feature type that recurs all over the island as if it were a proper
        # name (a land_use polygon literally named "Sawah", a "Kantor Desa
        # Benteng Poco" whose "Poco" half is already stripped as a generic
        # word here) -- without stripping these too, a distinctive local_name
        # like "Sawah Detusoko" or "Benteng Lohayong" can word-match some
        # unrelated place a hundred kilometres away on the strength of the
        # generic half alone, instead of the actual place name.
        "sawah", "batu", "benteng",
        # "fort" (English) is "benteng"'s counterpart, for the same reason.
        "fort",
        # English
        "mount", "mt", "lake", "beach", "village", "cave", "waterfall",
        "island",
    }
)

_PHRASE_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in GENERIC_PHRASES) + r")\b")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WS_RE = re.compile(r"\s+")


def strip_diacritics(text: str) -> str:
    """Drop combining diacritical marks (e cedilla, etc.) via NFKD."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalise_name(name: Optional[str]) -> str:
    """Normalise a place name for cross-source comparison.

    Lowercases, strips diacritics, removes punctuation, unifies hyphens to
    spaces, removes the generic prefixes/words listed above (Indonesian and
    English geographic generics, plus office words), and collapses
    whitespace. Returns "" for ``None``/empty input or a name that is
    *entirely* generic words (e.g. bare "Danau") -- both are treated as
    "nothing to match on" by callers.
    """
    if not name:
        return ""
    text = strip_diacritics(name).lower()
    text = text.replace("-", " ")
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _PHRASE_RE.sub(" ", text)
    words = [w for w in text.split() if w not in GENERIC_WORDS]
    return _WS_RE.sub(" ", " ".join(words)).strip()


def name_variants(name: Optional[str], local_name: Optional[str] = None) -> list[str]:
    """Normalised, de-duplicated, non-empty name forms to try matching with."""
    out: list[str] = []
    for raw in (name, local_name):
        norm = normalise_name(raw)
        if len(norm) >= 2 and norm not in out:
            out.append(norm)
    return out


def _contains_word_bounded(shorter: str, longer: str) -> bool:
    """Is ``shorter`` a whole-word (boundary-respecting) run of tokens inside
    ``longer``? Deliberately stricter than a raw substring test: names here
    are short Indonesian toponyms that recur as fragments *inside* unrelated
    compound words (e.g. "nggela" is a plain substring of the unrelated
    "Maronggela", "denge" of "Denger") -- a bare ``shorter in longer`` check
    would "match" those and rank a village against a random unrelated place a
    hundred kilometres away. Requiring a word boundary on both sides (regular
    space-separated tokens here, since names are normalised) keeps the
    containment rule from BRIEF.md but only where it is actually the same
    word or phrase, not a coincidental fragment.
    """
    if len(shorter) < 4:
        return False
    return re.search(r"\b" + re.escape(shorter) + r"\b", longer) is not None


def name_match(query: str, candidate: str) -> Optional[tuple[float, str]]:
    """Compare two already-normalised names.

    Returns ``(score, match_type)`` if they match ("exact", "fuzzy-ratio" or
    "fuzzy-contains"), else ``None``. Per BRIEF.md: a difflib ratio >= 0.85,
    or one name contained in the other with length >= 4 -- "contained" here
    means as whole word(s), see ``_contains_word_bounded``.
    """
    if not query or not candidate:
        return None
    if query == candidate:
        return 1.0, "exact"
    ratio = SequenceMatcher(None, query, candidate).ratio()
    contains = _contains_word_bounded(query, candidate) or _contains_word_bounded(candidate, query)
    if ratio >= 0.85:
        return ratio, "fuzzy-ratio"
    if contains:
        return ratio, "fuzzy-contains"
    return None


# ---------------------------------------------------------------------------
# Gazetteer: flatten the Overture extract into one comparable shape
# ---------------------------------------------------------------------------


@dataclass
class GazEntry:
    """One named point/polygon from the Overture extract, flattened."""

    name: str
    normalised_name: str
    bucket: str  # coarse compatibility group, see *_BUCKET maps below
    kind_label: str  # human-readable, e.g. "land:volcano", "place:hotel"
    lon: float
    lat: float
    elevation: Optional[float]
    source_file: str
    source_id: str
    geometry: Optional[Any] = field(default=None, repr=False)  # shapely, polygons only


#: Overture place.geojsonl ``category`` -> compatibility bucket. Anything not
#: listed here falls back to the generic "place" bucket (a real place, but
#: not one whose category tells us much -- still useful as a last resort for
#: broad curated categories like "other").
PLACE_CATEGORY_BUCKET: dict[str, str] = {
    "mountain": "peak",
    "beach": "beach",
    "lake": "lake",
    "cave": "cave",
    "waterfall": "waterfall",
    "hot_springs": "hot_spring",
    "forest": "land_other",
    "national_park": "national_park",
    "landmark_and_historical_building": "place_landmark",
    "church_cathedral": "place_religious",
    "catholic_church": "place_religious",
    "mosque": "place_religious",
    "religious_organization": "place_religious",
    "central_government_office": "place_gov",  # covers "Kantor Desa/Kelurahan <village>"
    "public_service_and_government": "place_gov",
    "airport": "place_airport",
    "airport_terminal": "place_airport",
    "farmers_market": "place_market",
    "night_market": "place_market",
    "ferry_boat_company": "place_port",
    "hiking_trail": "place_viewpoint",
}

#: land.geojsonl ``class`` -> bucket. Both "peak" and "volcano" become "peak"
#: -- for our purposes (is this the right summit?) they are the same thing.
LAND_CLASS_BUCKET: dict[str, str] = {
    "peak": "peak",
    "volcano": "peak",
    "beach": "beach",
    "cave_entrance": "cave",
    "island": "island",
}

#: water.geojsonl ``class`` -> bucket. Kept separate from "hot_spring": a
#: plain (cold) "spring" should not silently satisfy a hot-spring check, but
#: it is still accepted as a compatible candidate since not every thermal
#: spring is tagged as such in OSM-derived data.
WATER_CLASS_BUCKET: dict[str, str] = {
    "lake": "lake",
    "hot_spring": "hot_spring",
    "spring": "spring",
    "waterfall": "waterfall",
}

#: division_area.geojsonl ``subtype`` -> bucket. "locality"/"neighborhood"
#: are desa/kelurahan-equivalent polygons -- the village-area match.
DIVISION_SUBTYPE_BUCKET: dict[str, str] = {
    "locality": "village_area",
    "neighborhood": "village_area",
    "county": "county",
}


#: Substrings (matched case-insensitively against the *raw* name) that mark a
#: "central_government_office"/"public_service_and_government" place as
#: regency- or province-scoped rather than village/kelurahan/kecamatan-scoped
#: -- a regency health/works/police department sits in the regency capital,
#: not in every village that happens to share the regency's name (Sikka
#: village vs. Kabupaten Sikka is exactly this trap). Kantor Desa/Kelurahan/
#: Camat, Koramil and Polsek stay in "place_gov": those are village- or
#: sub-district-level and are the ones BRIEF.md means by "Kantor Desa place".
_REGENCY_SCOPE_MARKERS: tuple[str, ...] = (
    "kabupaten", "kab.", "pemkab", "provinsi", "polres", "kodim", "kejaksaan",
    "pengadilan negeri", "rsud", "bupati", "dprd", "sekretariat daerah",
)


def _is_regency_scope_office(raw_name: str) -> bool:
    lname = raw_name.lower()
    return any(marker in lname for marker in _REGENCY_SCOPE_MARKERS)


def _point_or_centroid(geometry: dict) -> tuple[float, float]:
    """Return (lon, lat): the point itself, or a polygon's centroid."""
    if geometry.get("type") == "Point":
        lon, lat = geometry["coordinates"][:2]
        return float(lon), float(lat)
    geom = shape(geometry)
    c = geom.centroid
    return float(c.x), float(c.y)


def _iter_geojsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def load_gazetteer(overture_dir: Path) -> list[GazEntry]:
    """Flatten the Overture extract's five layers into one list of
    :class:`GazEntry`, skipping anything with no name (nothing to match on).
    """
    entries: list[GazEntry] = []

    for obj in _iter_geojsonl(overture_dir / "place.geojsonl"):
        props = obj.get("properties", {})
        norm = normalise_name(props.get("name"))
        if not norm:
            continue
        category = props.get("category")
        bucket = PLACE_CATEGORY_BUCKET.get(category, "place")
        if bucket == "place_gov" and _is_regency_scope_office(props["name"]):
            bucket = "place"
        lon, lat = _point_or_centroid(obj["geometry"])
        entries.append(
            GazEntry(
                props["name"], norm, bucket, f"place:{category or 'uncategorized'}", lon, lat, None,
                "place", str(props.get("id", obj.get("id", ""))),
            )
        )

    for obj in _iter_geojsonl(overture_dir / "land.geojsonl"):
        props = obj.get("properties", {})
        norm = normalise_name(props.get("name"))
        if not norm:
            continue
        cls = props.get("class")
        bucket = LAND_CLASS_BUCKET.get(cls, "land_other")
        lon, lat = _point_or_centroid(obj["geometry"])
        entries.append(
            GazEntry(
                props["name"], norm, bucket, f"land:{cls}", lon, lat, props.get("elevation"),
                "land", str(props.get("id", obj.get("id", ""))),
            )
        )

    for obj in _iter_geojsonl(overture_dir / "water.geojsonl"):
        props = obj.get("properties", {})
        norm = normalise_name(props.get("name"))
        if not norm:
            continue
        cls = props.get("class")
        bucket = WATER_CLASS_BUCKET.get(cls, "water_other")
        lon, lat = _point_or_centroid(obj["geometry"])
        entries.append(
            GazEntry(
                props["name"], norm, bucket, f"water:{cls}", lon, lat, None,
                "water", str(props.get("id", obj.get("id", ""))),
            )
        )

    for obj in _iter_geojsonl(overture_dir / "division_area.geojsonl"):
        props = obj.get("properties", {})
        norm = normalise_name(props.get("name"))
        if not norm:
            continue
        subtype = props.get("subtype")
        bucket = DIVISION_SUBTYPE_BUCKET.get(subtype, "division_other")
        geom = shape(obj["geometry"])
        c = geom.centroid
        # Only polygons carry real inside/outside information; a division
        # entry that came back as a Point has no polygon to test against, so
        # the geometry is dropped and the "confirmed if inside" override
        # never fires for it (regular distance thresholds apply instead).
        keep_geom = geom if obj["geometry"].get("type") in ("Polygon", "MultiPolygon") else None
        entries.append(
            GazEntry(
                props["name"], norm, bucket, f"division:{subtype}", float(c.x), float(c.y), None,
                "division_area", str(props.get("id", obj.get("id", ""))), geometry=keep_geom,
            )
        )

    for obj in _iter_geojsonl(overture_dir / "land_use.geojsonl"):
        props = obj.get("properties", {})
        norm = normalise_name(props.get("name"))
        if not norm:
            continue
        cls = props.get("class")
        bucket = "national_park" if cls == "national_park" else "landuse_other"
        lon, lat = _point_or_centroid(obj["geometry"])
        entries.append(
            GazEntry(
                props["name"], norm, bucket, f"land_use:{cls}", lon, lat, None,
                "land_use", str(props.get("id", obj.get("id", ""))),
            )
        )

    return entries


# ---------------------------------------------------------------------------
# Compatibility: which gazetteer buckets count as "the same kind of thing"
# ---------------------------------------------------------------------------

#: Every bucket that ultimately comes from the Overture *place* layer,
#: regardless of specific category. A local school, church, market or office
#: literally named after a village is decent circumstantial evidence of
#: where that village is -- Overture's category tagging for such POIs is
#: noisy enough (see ``PLACE_CATEGORY_BUCKET``) that splitting hairs between
#: "a government office" and "a shop" would just create false negatives, not
#: more precision. None of these are trusted enough to source a suggested
#: coordinate fix on their own, though -- see the generic-"place" exclusion
#: in ``process_feature``.
ALL_PLACE_BUCKETS: frozenset[str] = frozenset(
    {
        "place", "place_gov", "place_religious", "place_landmark",
        "place_market", "place_port", "place_airport", "place_viewpoint",
    }
)

#: data/pois.geojson ``category`` -> acceptable gazetteer buckets: each
#: category's authoritative bucket(s) (a volcano should match a peak) unioned
#: with ``ALL_PLACE_BUCKETS`` -- Overture's place-layer categorisation is
#: noisy enough (a lake tagged "lake" 20 km from six independent "Sano
#: Nggoang"-named schools/police posts clustered where the real lake is; a
#: waterfall showing up only as an "active_life" POI) that a same-named
#: local institution is worth accepting as a fallback for anything, not only
#: settlements. "airport" is the one deliberate exception: it stays strict to
#: ``place_airport`` since diluting it risks matching an unrelated business
#: that merely mentions the airport's name.
POI_COMPAT: dict[str, frozenset[str]] = {
    "volcano": frozenset({"peak"}) | ALL_PLACE_BUCKETS,
    "crater-lake": frozenset({"peak", "lake"}) | ALL_PLACE_BUCKETS,
    "lake": frozenset({"lake"}) | ALL_PLACE_BUCKETS,
    "traditional-village": frozenset({"village_area"}) | ALL_PLACE_BUCKETS,
    "beach": frozenset({"beach"}) | ALL_PLACE_BUCKETS,
    "hot-spring": frozenset({"hot_spring", "spring"}) | ALL_PLACE_BUCKETS,
    "waterfall": frozenset({"waterfall"}) | ALL_PLACE_BUCKETS,
    "cave": frozenset({"cave"}) | ALL_PLACE_BUCKETS,
    "heritage": frozenset({"village_area", "national_park"}) | ALL_PLACE_BUCKETS,
    "viewpoint": frozenset({"peak"}) | ALL_PLACE_BUCKETS,
    "market": ALL_PLACE_BUCKETS,
    "port": ALL_PLACE_BUCKETS,
    "airport": frozenset({"place_airport"}),
    "national-park": frozenset({"national_park"}) | ALL_PLACE_BUCKETS,
    "weaving": frozenset({"village_area"}) | ALL_PLACE_BUCKETS,
    "religious": frozenset({"place_religious"}) | ALL_PLACE_BUCKETS,
    "hazard": frozenset({"peak"}) | ALL_PLACE_BUCKETS,
    "forest": frozenset({"land_other"}) | ALL_PLACE_BUCKETS,
    "savanna": frozenset({"land_other"}) | ALL_PLACE_BUCKETS,
    "rice-terrace": frozenset({"landuse_other", "land_other"}) | ALL_PLACE_BUCKETS,
    # "other" is a grab-bag by design (data-model.md) -- accept broadly.
    "other": frozenset({"village_area", "peak", "island", "land_other", "water_other", "national_park", "lake", "beach"})
    | ALL_PLACE_BUCKETS,
}

#: data/nodes.geojson ``kind`` -> acceptable gazetteer buckets. Every kind
#: except "airport" is fundamentally "a named settlement/spot", so all admit
#: the division-polygon match plus any place-layer match; "checkpoint" adds
#: peak/lake/beach on top since this course's checkpoints are a mix of
#: villages, volcanoes, lakes and beaches (Bena, Kelimutu, Koka, Wae Rebo).
NODE_COMPAT: dict[str, frozenset[str]] = {
    "start": frozenset({"village_area"}) | ALL_PLACE_BUCKETS,
    "finish": frozenset({"village_area"}) | ALL_PLACE_BUCKETS,
    "checkpoint": frozenset({"village_area", "peak", "lake", "beach"}) | ALL_PLACE_BUCKETS,
    "town": frozenset({"village_area"}) | ALL_PLACE_BUCKETS,
    "village": frozenset({"village_area"}) | ALL_PLACE_BUCKETS,
    "junction": frozenset({"village_area"}) | ALL_PLACE_BUCKETS,
    "trailhead": frozenset({"village_area"}) | ALL_PLACE_BUCKETS,
    "port": frozenset({"village_area"}) | ALL_PLACE_BUCKETS,
    "airport": frozenset({"place_airport"}),
}

DEFAULT_COMPAT: frozenset[str] = frozenset({"place"})


# ---------------------------------------------------------------------------
# Matching a curated feature against the gazetteer
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    entry: GazEntry
    distance_km: float
    match_type: str
    score: float
    inside_polygon: bool

    def as_dict(self) -> dict:
        return {
            "name": self.entry.name,
            "kind_label": self.entry.kind_label,
            "source_file": self.entry.source_file,
            "source_id": self.entry.source_id,
            "lon": round(self.entry.lon, 6),
            "lat": round(self.entry.lat, 6),
            "elevation_m": self.entry.elevation,
            "distance_km": round(self.distance_km, 3),
            "match_type": self.match_type,
            "inside_polygon": self.inside_polygon,
        }


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    return common.haversine_m(lon1, lat1, lon2, lat2) / 1000.0


def find_candidates(
    lon: float, lat: float, variants: list[str], gazetteer: list[GazEntry], compat_buckets: frozenset[str]
) -> tuple[list[Candidate], list[Candidate]]:
    """Return (compatible, all) name-matching candidates, each sorted nearest
    first. ``all`` includes bucket-incompatible name matches too (used only
    to report "a same-named thing exists, but of the wrong kind" caveats);
    ``compatible`` is the list actual verdicts are computed from.
    """
    best_by_key: dict[tuple[str, str], Candidate] = {}
    for entry in gazetteer:
        best_local: Optional[tuple[float, str]] = None
        for qn in variants:
            m = name_match(qn, entry.normalised_name)
            if m is not None and (best_local is None or m[0] > best_local[0]):
                best_local = m
        if best_local is None:
            continue
        score, mtype = best_local
        dist_km = haversine_km(lon, lat, entry.lon, entry.lat)
        inside = False
        if entry.geometry is not None:
            try:
                inside = bool(entry.geometry.contains(Point(lon, lat)))
            except Exception:
                inside = False
        key = (entry.source_file, entry.source_id)
        cand = Candidate(entry, dist_km, mtype, score, inside)
        prev = best_by_key.get(key)
        if prev is None or dist_km < prev.distance_km:
            best_by_key[key] = cand

    all_candidates = sorted(best_by_key.values(), key=lambda c: c.distance_km)
    compatible = [c for c in all_candidates if c.entry.bucket in compat_buckets]
    return compatible, all_candidates


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------

CONFIRMED_KM = 1.0
PLAUSIBLE_KM = 3.0
SUSPECT_KM = 8.0


def classify(distance_km: Optional[float]) -> str:
    """Distance-only verdict. The village-inside-polygon override is applied
    by the caller *before* falling back to this (it does not need a distance
    at all)."""
    if distance_km is None:
        return "unmatched"
    if distance_km <= CONFIRMED_KM:
        return "confirmed"
    if distance_km <= PLAUSIBLE_KM:
        return "plausible"
    if distance_km <= SUSPECT_KM:
        return "suspect"
    return "wrong"


# ---------------------------------------------------------------------------
# DEM checks
# ---------------------------------------------------------------------------

ELEVATION_MISMATCH_M = 200.0
LOCAL_MAX_RADIUS_M = 1500.0
LOCAL_MAX_STEP_M = 120.0
LOCAL_MAX_SNAP_M = 800.0
#: Volcano/crater categories the "is there a higher point nearby" check
#: applies to (data-model.md's poi ``category`` enum has no separate "peak").
PEAK_LIKE_CATEGORIES = frozenset({"volcano", "crater-lake"})


def elevation_check(dem, lon: float, lat: float, claimed_m: Optional[float]) -> Optional[dict]:
    """Compare a curated ``elevation_m`` claim against the DEM. None if there
    is no claim to check."""
    if claimed_m is None:
        return None
    dem_val = common.clamp_elevation(dem.elevation(lon, lat))
    diff = abs(dem_val - float(claimed_m))
    return {
        "claimed_elevation_m": claimed_m,
        "dem_elevation_m": round(dem_val, 1),
        "diff_m": round(diff, 1),
        "major": diff > ELEVATION_MISMATCH_M,
    }


def local_dem_max(
    dem, lon: float, lat: float, radius_m: float = LOCAL_MAX_RADIUS_M, step_m: float = LOCAL_MAX_STEP_M
) -> Optional[dict]:
    """Grid-search the DEM within ``radius_m`` of (lon, lat) for its highest
    point. Returns None if the DEM has no data at the query point at all
    (e.g. it is over open water / off the loaded tiles).
    """
    center_elev = dem.elevation(lon, lat)
    if center_elev is None:
        return None
    center_elev = common.clamp_elevation(center_elev)

    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    if m_per_deg_lon <= 1.0:
        return None

    steps = int(radius_m // step_m) + 1
    best_lon, best_lat, best_elev = lon, lat, center_elev
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            dx_m, dy_m = i * step_m, j * step_m
            if math.hypot(dx_m, dy_m) > radius_m:
                continue
            plon = lon + dx_m / m_per_deg_lon
            plat = lat + dy_m / m_per_deg_lat
            elev = common.clamp_elevation(dem.elevation(plon, plat))
            if elev > best_elev:
                best_lon, best_lat, best_elev = plon, plat, elev

    return {
        "lon": round(best_lon, 6),
        "lat": round(best_lat, 6),
        "elevation_m": round(best_elev, 1),
        "center_elevation_m": round(center_elev, 1),
        "distance_m": round(common.haversine_m(lon, lat, best_lon, best_lat), 1),
    }


# ---------------------------------------------------------------------------
# Per-feature processing
# ---------------------------------------------------------------------------

#: A runner-up compatible candidate counts as making the match "ambiguous"
#: (i.e. not safe to auto-suggest a coordinate fix from) when it is not
#: clearly farther away *from the curated point* than the best one...
AMBIGUITY_MARGIN_KM = 1.0
AMBIGUITY_RATIO = 2.0
#: ...AND it is not simply the same real-world spot as the best match under a
#: different Overture record (duplicate/nearby POIs for one place -- a second
#: "Koka Beach" 40 m from the first, a school metres from the desa office it
#: shares a courtyard with -- are commonplace and are not a location
#: disagreement worth flagging). Only candidates genuinely separated *from
#: each other* by more than this count as competing, different answers.
AMBIGUITY_MIN_SEPARATION_KM = 0.3


def process_feature(
    file_label: str,
    feature: dict,
    kind_field: str,
    compat_map: dict[str, frozenset[str]],
    gazetteer: list[GazEntry],
    dem: Optional[Any],
) -> dict:
    """Cross-check one curated Feature; returns a plain, JSON-safe dict."""
    props = feature["properties"]
    fid = props["id"]
    name = props.get("name")
    local_name = props.get("local_name")
    lon, lat = feature["geometry"]["coordinates"][:2]
    key = props.get(kind_field)
    compat = compat_map.get(key, DEFAULT_COMPAT)

    variants = name_variants(name, local_name)
    compatible, all_candidates = find_candidates(lon, lat, variants, gazetteer, compat)

    # "best" is always the single nearest compatible candidate, so the report
    # shows the most informative evidence available (a 0.00 km "Kantor
    # Kelurahan Reo" beats a 0.85 km desa-polygon centroid as *evidence*, even
    # though the polygon is what the inside-the-polygon rule below keys off
    # of). A village-type match that actually *contains* the curated point
    # forces the verdict to "confirmed" regardless of centroid distance (see
    # module docstring) -- but only the verdict, not which candidate is shown.
    best = compatible[0] if compatible else None
    verdict = classify(best.distance_km) if best is not None else "unmatched"
    if any(c.entry.bucket == "village_area" and c.inside_polygon for c in compatible):
        verdict = "confirmed"

    runner_up = next((c for c in compatible if c is not best), None) if best is not None else None
    ambiguous = False
    if best is not None and runner_up is not None:
        close_to_query = runner_up.distance_km <= max(best.distance_km * AMBIGUITY_RATIO, AMBIGUITY_MARGIN_KM)
        separated_from_best = (
            haversine_km(best.entry.lon, best.entry.lat, runner_up.entry.lon, runner_up.entry.lat)
            > AMBIGUITY_MIN_SEPARATION_KM
        )
        ambiguous = close_to_query and separated_from_best

    off_kind_note = None
    if best is None and all_candidates:
        nearest_other = all_candidates[0]
        off_kind_note = (
            f"name matches {nearest_other.entry.kind_label} '{nearest_other.entry.name}' "
            f"{nearest_other.distance_km:.2f} km away, but that kind is not compatible with '{key}'"
        )

    elev_check = None
    local_max = None
    dem_note_parts: list[str] = []
    if dem is not None:
        elev_check = elevation_check(dem, lon, lat, props.get("elevation_m"))
        if elev_check and elev_check["major"]:
            dem_note_parts.append(
                f"elevation_m={elev_check['claimed_elevation_m']} vs DEM "
                f"{elev_check['dem_elevation_m']:.0f} m (diff {elev_check['diff_m']:.0f} m)"
            )
        if key in PEAK_LIKE_CATEGORIES:
            local_max = local_dem_max(dem, lon, lat)
            if local_max and local_max["distance_m"] > LOCAL_MAX_SNAP_M and (
                local_max["elevation_m"] > local_max["center_elevation_m"]
            ):
                dem_note_parts.append(
                    f"DEM local max within 1.5 km is {local_max['elevation_m']:.0f} m at "
                    f"({local_max['lon']}, {local_max['lat']}), {local_max['distance_m']:.0f} m away "
                    "-- consider snapping"
                )

    # The generic "place" bucket means only "some place's name happens to
    # match" (no specific category tells us it is authoritative) -- good
    # enough as circumstantial evidence for a verdict, not solid enough to
    # recommend overwriting a coordinate with.
    suggested_fix = None
    if verdict in ("suspect", "wrong") and best is not None and not ambiguous and best.entry.bucket != "place":
        suggested_fix = [round(best.entry.lon, 6), round(best.entry.lat, 6)]

    return {
        "file": file_label,
        "id": fid,
        "name": name,
        "local_name": local_name,
        "kind_or_category": key,
        "confidence": props.get("confidence"),
        "lon": round(float(lon), 6),
        "lat": round(float(lat), 6),
        "match": best.as_dict() if best is not None else None,
        "runner_up": runner_up.as_dict() if runner_up is not None else None,
        "ambiguous": ambiguous,
        "verdict": verdict,
        "off_kind_note": off_kind_note,
        "elevation_check": elev_check,
        "local_max": local_max,
        "dem_note": "; ".join(dem_note_parts) if dem_note_parts else None,
        "suggested_fix": suggested_fix,
    }


def process_features(
    file_label: str,
    features: list[dict],
    kind_field: str,
    compat_map: dict[str, frozenset[str]],
    gazetteer: list[GazEntry],
    dem: Optional[Any],
) -> list[dict]:
    return [
        process_feature(file_label, feat, kind_field, compat_map, gazetteer, dem)
        for feat in sorted(features, key=lambda f: f["properties"]["id"])
    ]


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

VERDICTS = ("confirmed", "plausible", "suspect", "wrong", "unmatched")


def summarise(results: list[dict]) -> dict[str, int]:
    counts = {v: 0 for v in VERDICTS}
    for r in results:
        counts[r["verdict"]] += 1
    return counts


def build_caveats(all_results: list[dict]) -> list[str]:
    caveats = [
        "The Overture extract is a raw, community-sourced dataset: the same "
        "real place can appear multiple times under slightly different "
        "names, at different precisions, or (rarely) mistagged at an "
        "unrelated location -- e.g. duplicate 'airport' points for the same "
        "field a hundred kilometres apart. Matching picks the nearest "
        "compatible, name-matching candidate for exactly this reason: string "
        "similarity alone is not a safe ranking signal here, only a filter.",
        "Generic Indonesian toponyms (Golo-, Poco-, Wolo-, Watu-, 'Kantor "
        "Desa') recur across many villages on Flores; a normalised-name match "
        "close to the curated point is good evidence, but a match far away "
        "under the same generic name is not evidence of anything.",
    ]
    for r in all_results:
        if r["ambiguous"] and r["match"] and r["runner_up"]:
            caveats.append(
                f"{r['id']} ({r['name']}): more than one similarly-close compatible match -- "
                f"best '{r['match']['name']}' at {r['match']['distance_km']:.2f} km, "
                f"runner-up '{r['runner_up']['name']}' at {r['runner_up']['distance_km']:.2f} km; "
                "verify by hand before trusting either."
            )
    return caveats


def collect_findings(all_results: list[dict]) -> list[dict]:
    """Flatten verdict + elevation issues into the {feature_id, severity,
    claim, evidence, suggested_fix} shape the caller asked for."""
    findings: list[dict] = []
    for r in all_results:
        if r["verdict"] in ("suspect", "wrong"):
            severity = "blocker" if r["verdict"] == "wrong" else "major"
            if r["match"]:
                evidence = (
                    f"nearest compatible gazetteer match is '{r['match']['name']}' "
                    f"({r['match']['kind_label']}, {r['match']['source_file']}:{r['match']['source_id']}) "
                    f"at ({r['match']['lon']}, {r['match']['lat']}), {r['match']['distance_km']:.2f} km away"
                )
            else:
                evidence = r["off_kind_note"] or "no compatible gazetteer entry found nearby"
            findings.append(
                {
                    "feature_id": r["id"],
                    "severity": severity,
                    "claim": f"{r['name']} is at ({r['lon']}, {r['lat']})",
                    "evidence": evidence,
                    "suggested_fix": (
                        {"lon": r["suggested_fix"][0], "lat": r["suggested_fix"][1]}
                        if r["suggested_fix"]
                        else None
                    ),
                }
            )
        elif r["verdict"] == "unmatched":
            findings.append(
                {
                    "feature_id": r["id"],
                    "severity": "minor",
                    "claim": f"{r['name']} is at ({r['lon']}, {r['lat']})",
                    "evidence": r["off_kind_note"] or "no name match found in the gazetteer",
                    "suggested_fix": None,
                }
            )
        if r["elevation_check"] and r["elevation_check"]["major"]:
            findings.append(
                {
                    "feature_id": r["id"],
                    "severity": "major",
                    "claim": f"{r['name']} elevation_m={r['elevation_check']['claimed_elevation_m']}",
                    "evidence": (
                        f"DEM elevation at the curated point is "
                        f"{r['elevation_check']['dem_elevation_m']:.0f} m "
                        f"(diff {r['elevation_check']['diff_m']:.0f} m)"
                    ),
                    "suggested_fix": {"elevation_m": r["elevation_check"]["dem_elevation_m"]},
                }
            )
    return findings


def render_markdown(report: dict) -> str:
    lines: list[str] = ["# Gazetteer cross-check report", ""]
    lines.append(
        "Independent, offline check of `data/nodes.geojson` and `data/pois.geojson` "
        "coordinates against a local Overture Maps extract and the SRTM DEM. "
        "This is a report, not a validator -- see `pipeline/validate.py` for the schema/"
        "referential-integrity gate."
    )
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| File | confirmed | plausible | suspect | wrong | unmatched | total |")
    lines.append("|---|---|---|---|---|---|---|")
    for file_label in ("nodes", "pois"):
        c = report["summary"][file_label]
        total = sum(c.values())
        lines.append(
            f"| {file_label} | {c['confirmed']} | {c['plausible']} | {c['suspect']} | "
            f"{c['wrong']} | {c['unmatched']} | {total} |"
        )
    c = report["summary"]["overall"]
    total = sum(c.values())
    lines.append(
        f"| **overall** | **{c['confirmed']}** | **{c['plausible']}** | **{c['suspect']}** | "
        f"**{c['wrong']}** | **{c['unmatched']}** | **{total}** |"
    )
    lines.append("")
    lines.append(
        f"Elevation mismatches (DEM vs claimed `elevation_m`, diff > {ELEVATION_MISMATCH_M:.0f} m): "
        f"{report['summary']['elevation_mismatches']}. "
        f"DEM local-max snap suggestions (volcano/crater-lake features): "
        f"{report['summary']['local_max_suggestions']}."
    )
    lines.append("")

    for file_label, title in (("nodes", "## data/nodes.geojson"), ("pois", "## data/pois.geojson")):
        lines.append(title)
        lines.append("")
        lines.append(
            "| id | name | curated lon,lat | confidence | best match (name / kind / source) | "
            "dist km | verdict | DEM note | suggested fix |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in report["features"][file_label]:
            if r["match"]:
                m = r["match"]
                match_cell = f"{m['name']} ({m['kind_label']}, {m['source_file']}:{m['source_id'][:8]})"
                dist_cell = f"{m['distance_km']:.2f}"
            else:
                match_cell = r["off_kind_note"] or "-"
                dist_cell = "-"
            dem_cell = (r["dem_note"] or "-").replace("|", "/")
            fix_cell = f"{r['suggested_fix'][0]}, {r['suggested_fix'][1]}" if r["suggested_fix"] else "-"
            match_cell = match_cell.replace("|", "/")
            lines.append(
                f"| {r['id']} | {r['name']} | {r['lon']}, {r['lat']} | {r['confidence']} | "
                f"{match_cell} | {dist_cell} | {r['verdict']} | {dem_cell} | {fix_cell} |"
            )
        lines.append("")

    lines.append("## Caveats")
    lines.append("")
    for cav in report["caveats"]:
        lines.append(f"- {cav}")
    lines.append("")

    lines.append("## Confirmed ids")
    lines.append("")
    lines.append(", ".join(report["confirmed_ids"]) if report["confirmed_ids"] else "(none)")
    lines.append("")

    return "\n".join(lines) + "\n"


def build_report(node_results: list[dict], poi_results: list[dict]) -> dict:
    all_results = node_results + poi_results
    findings = collect_findings(all_results)
    elevation_mismatches = sum(
        1 for r in all_results if r["elevation_check"] and r["elevation_check"]["major"]
    )
    local_max_suggestions = sum(
        1
        for r in all_results
        if r["local_max"]
        and r["local_max"]["distance_m"] > LOCAL_MAX_SNAP_M
        and r["local_max"]["elevation_m"] > r["local_max"]["center_elevation_m"]
    )
    return {
        "summary": {
            "nodes": summarise(node_results),
            "pois": summarise(poi_results),
            "overall": summarise(all_results),
            "elevation_mismatches": elevation_mismatches,
            "local_max_suggestions": local_max_suggestions,
        },
        "features": {"nodes": node_results, "pois": poi_results},
        "findings": findings,
        "caveats": build_caveats(all_results),
        "confirmed_ids": [r["id"] for r in all_results if r["verdict"] == "confirmed"],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(data_dir: Path, overture_dir: Path, dem_dir: Optional[Path]) -> dict:
    gazetteer = load_gazetteer(overture_dir)

    dem = None
    if dem_dir is not None:
        candidate_dem = common.load_dem(dem_dir)
        # Cheap presence check: any .hgt tile at all. An empty/missing
        # directory means "skip DEM checks", not "crash".
        if any(Path(dem_dir).glob("*.hgt")):
            dem = candidate_dem

    nodes = common.read_geojson(data_dir / "nodes.geojson")
    pois = common.read_geojson(data_dir / "pois.geojson")

    node_results = process_features("nodes", nodes["features"], "kind", NODE_COMPAT, gazetteer, dem)
    poi_results = process_features("pois", pois["features"], "category", POI_COMPAT, gazetteer, dem)

    return build_report(node_results, poi_results)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True, help="directory with nodes.geojson and pois.geojson")
    parser.add_argument(
        "--overture-dir", required=True,
        help="directory with place/land/water/division_area/land_use .geojsonl",
    )
    parser.add_argument(
        "--dem-dir", default=None,
        help="directory of SRTM .hgt tiles (optional; DEM checks are skipped without it)",
    )
    parser.add_argument("--out", required=True, help="markdown report output path")
    parser.add_argument("--json", default=None, help="optional JSON report output path")
    args = parser.parse_args(argv)

    report = run(Path(args.data), Path(args.overture_dir), Path(args.dem_dir) if args.dem_dir else None)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(report), encoding="utf-8")

    if args.json:
        common.write_json(args.json, report)

    return 0  # report, not a gate -- always succeeds


if __name__ == "__main__":
    raise SystemExit(main())
