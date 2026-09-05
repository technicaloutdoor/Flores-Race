# Flores Race Planner — instructions for the assistant

You are working on the planning tool for an ultra-distance adventure bike race across Flores
(Indonesia). This file is loaded automatically at the start of every session. Follow it.

## Start of every session

1. Read `docs/DIARY.md` completely. It is the project's memory: state, decisions and the reasoning
   behind them, environment quirks, open questions, and a log of every previous session. Trust it
   over your assumptions; verify against the repository when something looks stale.
2. Read `.claude/AGENT-BRIEF.md` before delegating anything to an agent, and hand agents its path.
3. Check `git status`, the current branch and the open pull request before changing anything.
4. The raw data cache is not committed. If a task needs the pipeline, run `pipeline/bootstrap_cache.sh`
   first (it recreates `.cache/` from open data in a few minutes).

## End of every session (not optional)

Update `docs/DIARY.md` before the last commit of the session:
- append a dated entry to the **Session log** (what was asked, what was done, agents and tiers used,
  what was verified, what is left);
- update **State of the project**, add or amend entries in the **Decision log** (never delete;
  mark superseded), and refresh **Open questions and next steps**;
- record every new environment or data quirk you discovered in the relevant section.
Commit the diary together with the work it describes.

## How work is split between models (the owner's explicit policy)

- **Top reasoning tier (the session's own model):** architecture, data model, route design and
  cultural or safety judgement, deciding between conflicting verification results, final review.
- **Mid coding tier:** writing pipeline and web code from a precise spec, research agents that
  gather and cross-check facts, adversarial reviewers, fixers.
- **Small fast tier:** schemas and types from a written contract, documentation from an outline,
  data formatting and merging, file inventories, screenshots.
Use the Agent tool's `model` parameter to pick the tier; omit it (inherit) only for judgement work.
Use the Workflow tool for fan-outs with verification stages (templates in `.claude/workflows/`,
pass the tier values as `args.tiers`); a single Agent for one well-scoped job. Give every agent an explicit list of files it owns; `data/` is
edited by one agent at a time. Details: `docs/ai-workflow.md`, `.claude/README.md`.

## Project map

| Path | What |
|---|---|
| `ARCHITECTURE.md` | system design; read before structural changes |
| `docs/data-model.md` | the data contract; schemas in `schemas/`, types in `web/src/data/types.ts` |
| `docs/route-concept.md` | the course concept and its status |
| `data/` | canonical, human-edited data; git is the database |
| `pipeline/` | Python 3.11 stages; `pipeline/README.md` lists order and flags |
| `web/` | Vite + TypeScript + MapLibre app; `npm run typecheck && npm test && npm run build` |
| `.github/workflows/` | validate on PR, deploy to GitHub Pages on `main` |

## Rules that always apply

- No model identifiers, vendor names or session links in files pushed to the repository.
- Never present a guess as a fact: every feature keeps `confidence`, `sources` and `status` honest.
- Never hand-edit generated files under `web/public/data/`; regenerate with the pipeline.
- Never disable TLS verification or work around the network proxy; report blocked hosts instead.
- Run the checks before pushing: `python pipeline/validate.py --data data --schemas schemas`,
  `python -m pytest pipeline/tests -q`, and the web checks above.
- Commit on the designated branch, push, keep the pull request description current.
