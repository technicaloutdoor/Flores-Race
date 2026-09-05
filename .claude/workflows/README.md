# Workflows

Reusable [Workflow tool](https://docs.claude.com) scripts for this repository. Each file is
a self-contained script (`export const meta = {...}` plus a body using `agent()`,
`parallel()`, `pipeline()`, `phase()`, `log()`) — see the workflow-authoring reference for
the full script API if you are editing one of these.

## What's here

- **`verify-data.js`** — verifies `data/*` with independent lenses (geo-plausibility against
  the DEM and land mask, an offline gazetteer cross-check via
  `pipeline/crosscheck_gazetteer.py`, a narrative/factual/safety check of the text fields,
  and — only when invoked with `args: { webSearch: true }` — three regional lenses that
  re-derive coordinates from live web sources), then a fixer agent applies blocker/major
  findings to `data/` and re-validates.
- **`review-fix.js`** — adversarial review of the built app: a code-correctness lens (reads
  `web/src` and `pipeline` for contract mismatches, runtime errors, security/accessibility
  issues) and a product-fit lens (runs the built app under Playwright and judges it against
  `ARCHITECTURE.md`'s principles — concept vs. scouted must be unmistakable, provenance
  visible). A fixer agent then applies findings and must leave typecheck, tests, build,
  `pipeline/validate.py`, and the screenshot script all green before returning `ok: true`.

Both scripts read `.claude/AGENT-BRIEF.md` first (the shared brief every agent they spawn
is told to read) and use repository-relative cache paths under `.cache/` — they assume
`pipeline/bootstrap_cache.sh` has already been run in this session, and tell their agents
to run it themselves if a needed `.cache/` subdirectory turns out to be empty.

## How to invoke

Use the Workflow tool with `name` set to the script's `meta.name`, and an optional `args`
object:

```
Workflow({ name: 'verify-data' })
Workflow({ name: 'verify-data', args: { webSearch: true } })
Workflow({ name: 'review-fix' })
Workflow({ name: 'review-fix', args: { skipCodeLens: true } })
```

Read each script's top-of-file comment block for the full list of `args` it accepts and
what they change.

## Workflow vs. a single Agent

Reach for one of these scripts, instead of a single Agent call or doing the work inline,
when the task genuinely needs:

- **Independent parallel lenses that must not see each other's conclusions** — e.g. a
  geo-plausibility check and a narrative-accuracy check are different failure modes; running
  them as one agent risks the first finding anchoring (or crowding out) the second. A
  Workflow's `parallel()` keeps them blind to each other until findings are merged.
- **A fixed sequence with a hard gate in the middle** — findings must be collected from
  every lens *before* the fixer runs (so contradictory findings can be reconciled in one
  place), and the fixer must re-validate before the run is considered done. That is a
  `parallel()` → merge → `agent()` pipeline shape, not something one agent should be trusted
  to self-referee in a single pass.
- **Enough independent work that wall-clock time matters** — three regional web-search
  lenses, or two review lenses that each run a full Playwright session, are worth running
  concurrently rather than one after another.

Use a single Agent call (or just do it yourself) instead when:

- The change is small and you can eyeball the result yourself (a one-line fix, a doc typo).
- Only one perspective is needed — there is no adversarial or independent-lens value to
  running the same check twice.
- You are mid-task and need one focused answer, not a structured multi-lens verification
  pass — save the workflow for before you consider the task done.

## File ownership

Every agent spawned by these scripts is told (via `.claude/AGENT-BRIEF.md`) to write only
inside the files or directories it was explicitly given for that step, and never two of them
hold write ownership of `data/` in the same phase. In both scripts here:

- Every **lens** (verify or review) is read-only — it returns findings, it never edits the
  repository (screenshots under `.cache/screenshots/` are the one sanctioned exception for
  the product-fit lens).
- Only the single **fixer** agent at the end of each script writes to the repository, and
  only after every lens has returned — so there is never more than one writer active on
  `data/`, `web/`, or `pipeline/` at a time within either script.

If you write a new workflow that fans out agents which *do* write files (not just read and
report), give each one an explicit, non-overlapping file list in its prompt, and if two
agents could otherwise race on the same file, run them sequentially (a `pipeline()` stage
boundary) or with `agent(..., { isolation: 'worktree' })`, not bare `parallel()`.

## Model tiers are invocation arguments

The scripts never name a model. Pass the tier values the Agent tool accepts in this session:

```
Workflow({ name: 'verify-data', args: { tiers: { mid: '<mid coding tier value>' }, webSearch: false } })
Workflow({ name: 'review-fix', args: { tiers: { mid: '<mid coding tier value>' } } })
```

Without `args.tiers` every agent inherits the session model (the top tier): correct, slower and
costlier. The tiering policy itself is in `docs/ai-workflow.md`.
