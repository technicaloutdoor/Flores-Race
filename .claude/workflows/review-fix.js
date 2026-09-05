export const meta = {
  name: 'review-fix',
  description: 'Adversarial review of the built app (code correctness; product fit via a real Playwright run), then fix findings and leave typecheck/tests/build/validate/screenshots green',
  whenToUse: 'After a round of web/ or pipeline/ changes that you believe work, before calling the feature done. Two independent lenses catch different failure classes (silent code bugs vs. a confusing or misleading product) that one self-review tends to miss.',
  phases: [
    { title: 'Review', detail: 'two adversarial lenses: code correctness, product fit' },
    { title: 'Fix', detail: 'apply findings; typecheck, tests, build, validate, screenshots must all pass' },
  ],
}

// -----------------------------------------------------------------------------------
// Reusable adversarial-review pattern for the Flores Race Planner web app + pipeline.
//
// args (all optional):
//   args.screenshotDir   override for where the product-fit lens writes its screenshots
//                         (default: REPO + '/.cache/screenshots/review')
//   args.skipCodeLens    true to run only the product-fit lens (rare — e.g. a pure content
//                         change with no code touched)
//
// Invoke with the Workflow tool: { name: 'review-fix' }.
// -----------------------------------------------------------------------------------

// Model tiers are passed at invocation and never written into this file:
//   Workflow({ name: '<this workflow>', args: { tiers: { mid: '<value the Agent tool accepts for the mid coding tier>' } } })
// Without args.tiers every agent inherits the session model (the top tier): correct but costlier.
const TIERS = (args && args.tiers) || {}
const MID = TIERS.mid

const REPO = '/home/user/Flores-Race'
const BRIEF = REPO + '/.claude/AGENT-BRIEF.md'
const SCREENSHOTS = (args && args.screenshotDir) || REPO + '/.cache/screenshots/review'
const PRE = 'First read ' + BRIEF + ' completely and then the design documents it names ' +
  '(ARCHITECTURE.md, docs/data-model.md, docs/route-concept.md). Obey its hard rules — ' +
  'in particular: this is a read-only review pass unless you are the fixer agent. '

const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          feature_id: { type: 'string' },
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          claim: { type: 'string' },
          evidence: { type: 'string' },
          suggested_fix: { type: 'string' },
        },
        required: ['feature_id', 'severity', 'claim', 'evidence', 'suggested_fix'],
      },
    },
    checked_count: { type: 'number' },
    summary: { type: 'string' },
  },
  required: ['findings', 'summary'],
}

const RESULT = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    summary: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['ok', 'summary'],
}

// ---------------------------------------------------------------- lenses
const codePrompt = PRE + `
REVIEW (lens: code correctness) of ${REPO}/web/src and ${REPO}/pipeline (read-only; write
nothing in the repo; scratch scripts go in your own scratchpad).
Read the code adversarially: contract mismatches with docs/data-model.md and schemas/
(field names, enums, optional handling), runtime errors on missing/optional fields,
URL-state bugs, localStorage overlay merge bugs, GPX validity (well-formed XML, escaping),
profile maths (ascent smoothing, units), off-by-one in chaining checks, Python exceptions
on empty inputs, path handling, non-idempotent writes, security (XSS in the markdown
renderer or when injecting names into innerHTML, no unsafe innerHTML with untrusted data),
accessibility basics (focusable controls, contrast), performance traps (re-adding map
layers on every store change, loading network.geojson.gz eagerly).
For each finding give the file:line, severity (blocker = crash, data corruption, or XSS;
major = wrong behaviour; minor = else), evidence, and a concrete fix. Verify at least 3
findings by actually running the code (node/python) before reporting them as confirmed —
say which are confirmed and which are unverified suspicions.`

const productPrompt = PRE + `
REVIEW (lens: product fit) of the built app (read-only; write nothing in the repo except
screenshots under ${SCREENSHOTS}/).
Run the app: cd ${REPO}/web && npm run build && npx vite preview --port 4173 in the
background, then use Playwright (chromium at /opt/pw-browsers; set
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers) to open each mode with base=none and interact:
select segments, sections, POIs, switch routes, open the scouting form in scout mode and
export a patch, play the story, export a GPX, check the URL updates and reloads to the same
state, resize to 390 px. Take your own screenshots under ${SCREENSHOTS}/.
Judge against ARCHITECTURE.md sections 1, 2 (principles 3 and 4 especially: concept vs
scouted must be unmistakable; provenance visible) and 7, and docs/route-concept.md: does a
stakeholder understand the course, its numbers and its uncertainty in 60 seconds? Can a
scout find what to check next (open questions, priorities)? Is anything presented as fact
that the data marks approximate/unverified? Are the licenses/attributions shown?
Report findings with severity and concrete fixes, referencing files.`

// ---------------------------------------------------------------- review
phase('Review')
const lensThunks = []
if (!(args && args.skipCodeLens === true)) {
  lensThunks.push(() => agent(codePrompt, { model: MID, phase: 'Review', label: 'review:code', schema: FINDINGS }))
} else {
  log('args.skipCodeLens=true: running only the product-fit lens')
}
lensThunks.push(() => agent(productPrompt, { model: MID, phase: 'Review', label: 'review:product', schema: FINDINGS }))

const reviews = await parallel(lensThunks)
const lensKeys = (args && args.skipCodeLens === true) ? ['product'] : ['code', 'product']
const reviewFindings = reviews.filter(Boolean).flatMap((r, i) => (r.findings || []).map((f) => ({ lens: lensKeys[i], ...f })))
log('Review findings: ' + reviewFindings.length +
  ' (blockers ' + reviewFindings.filter((f) => f.severity === 'blocker').length +
  ', major ' + reviewFindings.filter((f) => f.severity === 'major').length +
  ', minor ' + reviewFindings.filter((f) => f.severity === 'minor').length + ')')

// ---------------------------------------------------------------- fix
phase('Fix')
if (reviewFindings.length === 0) {
  log('No findings — skipping the fixer')
  return { reviewFindings: 0, fixed: null }
}

const fixed = await agent(PRE + `
TASK: fix review findings in ${REPO}/web and ${REPO}/pipeline (and data/ only for
presentation-related property fixes, e.g. a wrong 'public' flag surfaced by the product
lens — never geometry or narrative content, that belongs to the data-verification
workflow, not this one). Apply all blocker and major findings, and minor ones that are
cheap. Do not change the data contract (schemas/, docs/data-model.md) or the architecture;
if a finding asks for that, skip it and explain why.
FINDINGS:
${JSON.stringify(reviewFindings, null, 1)}

Before returning, ALL of these must pass, in this order, and you must re-run any that your
own fix could have affected:
1. cd ${REPO}/web && npm run typecheck
2. cd ${REPO}/web && npm test
3. cd ${REPO}/web && npm run build
4. python3 ${REPO}/pipeline/validate.py --data ${REPO}/data --schemas ${REPO}/schemas
5. If you touched anything build_web_data.py reads or writes, re-run it with the same
   flags the last real build used (check ${REPO}/pipeline/README.md or the script's own
   --help for the exact flags — do not guess; .cache/ must already hold what it needs, or
   run pipeline/bootstrap_cache.sh first) so web/public/data is fresh.
6. cd ${REPO}/web && npm run screenshot (writes to its configured output dir) — open the
   PNGs (Read tool) and confirm your fix actually shows.
Return ok=true only if every one of those passed on your last run; list fixes applied and
findings skipped with reasons.`, { model: MID, phase: 'Fix', label: 'apply-review-fixes', schema: RESULT })

log('Fix: ' + (fixed && fixed.ok ? 'ok — typecheck/tests/build/validate/screenshots green' : 'issues remain') +
  ' — ' + (fixed ? fixed.summary : 'fixer agent returned nothing'))
return { reviewFindings: reviewFindings.length, fixed }
