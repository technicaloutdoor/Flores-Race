# `.claude/`

What a session working on this repository needs to bootstrap itself.

## In this folder

- **`AGENT-BRIEF.md`** — the shared brief every agent (main session or spawned subagent)
  should read first: the project in one paragraph, the `.cache/` layout and how to rebuild
  it, the hard rules, the file-ownership rules for parallel agents, the sandbox's network
  reality, the tooling available, data conventions, and the geographic frame. It is written
  to be valid in any session — no session-specific paths.
- **`workflows/`** — reusable Workflow-tool scripts (`verify-data.js`, `review-fix.js`) that
  encode this project's multi-agent verification and review patterns, plus a `README.md`
  explaining when to reach for a Workflow versus a single Agent call. See that README before
  writing a new one.

Also relevant, elsewhere in the repo: `pipeline/bootstrap_cache.sh` rebuilds `.cache/` from
scratch (raw downloads and everything derived from them — DEM tiles, boundaries, Natural
Earth extracts, the Overture Maps extract, the routable network) and is always the first
thing to run in a fresh session before touching data that depends on it.

## Model tiering — rule of thumb

Pick the cheapest tier that won't need a redo:

- **Top reasoning tier** — judgement calls with real consequences: reconciling
  contradictory verification findings, course/route design decisions, anything where being
  wrong is expensive to unwind later.
- **Mid coding tier** — the default for actual work: writing or editing code, running and
  fixing a pipeline stage, curating data, most research (including agents that spend a
  WebSearch budget). This is what `verify-data.js` and `review-fix.js` use for their lenses
  and fixers.
- **Small fast tier** — mechanical, low-judgement work: generating boilerplate from a
  well-specified template (e.g. JSON Schemas straight out of `docs/data-model.md`), writing
  docs that mostly restate an existing source of truth, simple merges/formatting passes.

When in doubt, use the mid tier. Reserve the top tier for the step where a wrong call is
expensive; don't reach for it by default just because a task sounds important.

## WebSearch budget

A session's WebSearch budget is on the order of 200 searches — plenty for what actually
needs a live source, not enough to spend one-per-coordinate across hundreds of features.
Spend it deliberately:

- Prefer the **offline gazetteer cross-check** (`pipeline/crosscheck_gazetteer.py`, an
  independent Overture-derived dataset plus the DEM) for coordinate sanity — it costs zero
  WebSearch calls and catches most placement errors on its own. Only fall back to live
  WebSearch for a feature the gazetteer can't match, or when you specifically need
  confirmation from a second, human-readable source (e.g. before a stakeholder review).
  `verify-data.js`'s regional independent-source lenses (which do burn real WebSearch
  budget) are opt-in for exactly this reason — pass `args: { webSearch: true }` only when
  the budget is actually available and worth spending.
  - Checkable facts that change over time (volcano alert levels, anything dated) are worth
  a targeted search each; a coordinate that the gazetteer already confirmed is not.
- Don't re-search something a previous session already resolved — check `docs/DIARY.md`
  first.

## Project memory

`docs/DIARY.md` is the project's memory across sessions — what was tried, what worked, what
didn't, and why. Read it before repeating investigative work (especially anything that would
otherwise cost WebSearch budget or a full pipeline rebuild to rediscover); it is maintained
separately from this folder.

Workflow templates take the model tier values as invocation arguments (`args.tiers`, see `workflows/README.md`); no file in the repository names a model.
