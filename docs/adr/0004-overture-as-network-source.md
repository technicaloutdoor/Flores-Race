# ADR-0004: Overture Maps on S3 as the track-network source

**Status:** Accepted

**Context**
Building a routable graph of roads, tracks, and paths is a core task. OpenStreetMap data is the obvious source but Overpass API is slow and not available offline; live queries do not fit a static-first workflow. Overture Maps (OSM-derived, on public S3 buckets) offers the same data with better distribution.

**Decision**
Use Overture Maps (`segment` and `connector` themes) from S3 as the primary track network source. Extract only the Flores bbox via row-group pruning in Parquet, avoiding a full-planet download. The `build_network.py` pipeline turns segments + connectors into a routable graph classified by road type and surface.

**Consequences**
- The full island extract is ~500 MB raw; row-group pruning reduces it to hundreds of MB.
- Reproducible, versioned Overture release; easy to re-run if bugs are found.
- Route candidates are computed from the network graph, giving real-world route options.
- Static data means the network is not live; new tracks added to OSM after a release are not reflected until the next pipeline run.

**Alternatives considered**
1. *Overpass API live:* Slow; no offline mode; introduces a network dependency at plan time.
2. *Geofabrik PBF extracts:* Smaller downloads than raw Overture but still a heavy monolithic file; less granular than Parquet row-group pruning.
3. *Manual tracing:* Infeasible for a whole-island network; reserved for segments where Overture is inaccurate or missing.
