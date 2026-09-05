# ADR-0002: Segment graph with variants and statuses

**Status:** Accepted

**Context**
The course is defined by its *intent* (where do we want to go?) and what the island *permits* (what track network exists?). Anchors (start, finish, checkpoints) are decided by humans; segments are candidate pathways between them. Multiple alternatives between the same anchors (A, B, C variants) reflect different tradeoffs: more remote, more rideable, more scenic. Each segment carries status (concept, scouted-go/no-go, confirmed) and geometry source (concept-sketch, overture-route, gpx-field, manual-trace).

**Decision**
Model the race as a directed graph of nodes (anchors) and segments (LineStrings between them). Segments form edges; variants (A/B/C) are alternatives. Every segment is immutable once a human has touched its geometry; the pipeline proposes candidates but never overwrites a human trace. Status and confidence are explicit at every level.

**Consequences**
- Scouts clearly see what is concept vs. verified.
- The route designer accepts/rejects/splits candidate segments; geometry edits come as GPX traces.
- Pipeline can regenerate candidates for untouched segments without losing field work.
- Totals (km, climbing, unpaved %) are always computed, never typed by hand, so they never stale.
- UI styling (dashed grey for concept, green for scouted-go) makes status visible at a glance.

**Alternatives considered**
1. *Single segment per node-pair:* Loses the ability to compare alternatives in the field; harder to evaluate tradeoffs.
2. *Geometry always editable:* Pipeline candidates get overwritten; field work gets lost.
3. *Implicit status via scouting history:* Status should be explicit; scouts use the history to audit how a verdict was reached.
