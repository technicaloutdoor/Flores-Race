export const meta = {
  name: 'verify-data',
  description: 'Verify data/ with independent lenses (geo-plausibility, offline gazetteer, narrative/safety, optional web-search regional lenses), then fix blocker/major findings and re-validate',
  whenToUse: 'After data/*.geojson|json changed (new curation, a course-design pass, an applied scouting patch) and before trusting the result. Not for routine small edits a single agent can eyeball — use this when several independent lenses catching different failure modes is worth more than one careful pass.',
  phases: [
    { title: 'Verify', detail: 'parallel independent lenses over data/nodes,pois,segments,sections,routes' },
    { title: 'Fix', detail: 'apply blocker/major findings to data/, re-validate' },
  ],
}

// -----------------------------------------------------------------------------------
// Reusable data-verification pattern for the Flores Race Planner.
//
// args (all optional):
//   args.webSearch === true   also run the three regional independent-source lenses
//                              (west/central/east), each spending a WebSearch budget to
//                              re-derive coordinates from scratch. Expensive — only turn
//                              this on when a WebSearch budget is actually available and
//                              the offline gazetteer lens alone is not enough (e.g. before
//                              a stakeholder review, not after every small edit).
//   args.dataDir               override for data/ (default: REPO + '/data')
//   args.cacheDir              override for .cache/ (default: REPO + '/.cache')
//
// Invoke with the Workflow tool: { name: 'verify-data' } or
// { name: 'verify-data', args: { webSearch: true } }.
// -----------------------------------------------------------------------------------

// Model tiers are passed at invocation and never written into this file:
//   Workflow({ name: '<this workflow>', args: { tiers: { mid: '<value the Agent tool accepts for the mid coding tier>' } } })
// Without args.tiers every agent inherits the session model (the top tier): correct but costlier.
const TIERS = (args && args.tiers) || {}
const MID = TIERS.mid

const REPO = '/home/user/Flores-Race'
const BRIEF = REPO + '/.claude/AGENT-BRIEF.md'
const DATA = (args && args.dataDir) || REPO + '/data'
const CACHE = (args && args.cacheDir) || REPO + '/.cache'
const PRE = 'First read ' + BRIEF + ' completely and then the design documents it names ' +
  '(ARCHITECTURE.md, docs/data-model.md, docs/route-concept.md). Obey its hard rules — ' +
  'in particular: this is a read-only verification pass unless you are the fixer agent. ' +
  'If .cache/ is missing what you need, the brief tells you to run pipeline/bootstrap_cache.sh first. '

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

// ---------------------------------------------------------------- lens prompts
const geoPrompt = PRE + `
VERIFY (lens: geographic plausibility). Read-only on ${DATA}/*. Write helper scripts only
under your own scratchpad, never in the repo.
Using Python (shapely, pyproj, pipeline/dem.py, the regency union from ${CACHE}/boundaries/flores_regencies.geojson),
check EVERY feature in nodes.geojson, pois.geojson and segments.geojson:
- point on land (inside the regency union, or within 300 m for beaches/ports/islands
  context); flag anything in the sea or on the wrong island.
- DEM elevation vs claims: for category volcano/viewpoint the DEM maximum within 1.5 km
  should be within 250 m of 'elevation_m' (if given); crater-lake DEM within 200 m of
  claim; a 'beach' must be under 40 m and within 800 m of the coast (distance to regency
  union boundary); highland towns (Ruteng, Bajawa) 900-1300 m; coastal towns under 150 m.
- segments: first/last vertex within 300 m of its from/to node coordinates; no vertex in
  the sea more than 1 km offshore; no self-intersection; geodesic length within +-40% of a
  plausible corridor (straight-line distance x 1.3 to x 2.5); consecutive vertices not
  more than 40 km apart.
- routes: chain integrity (segment[i].to_node == segment[i+1].from_node, first/last anchor
  match); total km vs target_km_range.
If ${CACHE}/dem is empty, run pipeline/bootstrap_cache.sh (or just its DEM stage) first.
Report each problem as a finding: feature id, severity (blocker = in the sea / wrong place
by >5 km / chain broken; major = 1.5-5 km or elevation mismatch >250 m; minor = else),
evidence (the numbers), and a concrete suggested fix (e.g. new coordinates derived from the
DEM, like snapping a summit to the local DEM maximum). Return checked_count too.`

const gazetteerPrompt = PRE + `
VERIFY (lens: offline gazetteer cross-check). Read-only on ${DATA}/*.
Run: python3 ${REPO}/pipeline/crosscheck_gazetteer.py --data ${DATA} --overture-dir ${CACHE}/overture --dem-dir ${CACHE}/dem --out ${CACHE}/verify/gazetteer_report.md --json ${CACHE}/verify/gazetteer_report.json
(create ${CACHE}/verify/ if missing; if ${CACHE}/overture is empty, run pipeline/bootstrap_cache.sh's Overture stage first — read its --help, don't guess flags).
Read the JSON report. For every node/POI classified 'suspect' or 'wrong', turn it into a
finding: severity 'blocker' for 'wrong' (or any 'suspect' whose distance is > 5 km), 'major'
for other 'suspect' entries or an elevation mismatch the report flags, 'minor' for a
plausible-but-unconfirmed ('unmatched') feature that would be cheap to firm up later.
Evidence = the report's own numbers (matched name, distance, elevation delta); suggested_fix
= the coordinate/elevation the report's nearest compatible match implies, when it gives one,
else "needs a human/WebSearch look". This is a report, not a gate, so also read it for any
DEM-suggested summit snaps and include those as findings even at 'minor' if nothing else
flags that feature. Return checked_count = total features the report covered.`

const narrativePrompt = PRE + `
VERIFY (lens: factual, cultural and safety accuracy of the TEXT). Read-only on ${DATA}/*
and ${REPO}/docs/route-concept.md.
Read every 'summary', 'story', 'cultural_protocol', 'hazard_level', section 'story', and
segment 'hazards'/'cultural_notes'. For every checkable factual claim (dates, elevations,
awards, eruption history, who found what when, names of villages/houses/ceremonies,
distances) use WebSearch to confirm or refute; check at least 40 distinct claims,
prioritising the ones a stakeholder or local partner would notice if wrong. Also flag:
culturally insensitive phrasing, claims about permissions or customs not supported by a
source, safety statements that are outdated (volcano alert levels change: report the latest
you can find with its date), and marketing fluff or invented superlatives. Report findings
with feature_id (or 'sec-..' / 'docs/route-concept.md'), severity (blocker = wrong fact a
partner would catch or a safety error; major = unsupported claim; minor = wording), evidence
with the URL, and the exact replacement text as suggested_fix.`

const REGIONS = [
  { key: 'west', region: 'west (lon < 121.0)' },
  { key: 'central', region: 'central (121.0 <= lon < 122.05)' },
  { key: 'east', region: 'east (lon >= 122.05)' },
]
const sourcePrompt = (region) => PRE + `
VERIFY (lens: independent source agreement) for features in the ${region} part of the
island. Read-only on ${DATA}/nodes.geojson and pois.geojson. Do not trust the existing
'sources' field: find your own.
For EVERY node and POI whose longitude falls in your region, run WebSearch (one to three
queries per feature, e.g. '<name> Flores coordinates', '<name> <regency> desa', '<name>
volcano elevation') and extract the best independent coordinate and, where applicable,
elevation, from result snippets. Compute the distance to the stored coordinate (haversine).
Findings: distance > 1.5 km (major; > 5 km blocker) with the coordinate you found and the
URL; elevation_m differing by > 150 m (major); name misspelt or a better-known name exists
(minor); the feature is on a different island or does not exist (blocker). ALSO return, in
the summary, the list of feature ids you could CONFIRM within 1 km from a source independent
of the stored one (so the fixer can upgrade 'confidence' to 'verified'), formatted as
'CONFIRMED: id1, id2, ...'. checked_count = features you actually searched.`

// ---------------------------------------------------------------- assemble lenses
phase('Verify')
const lenses = [
  { key: 'geo', prompt: geoPrompt },
  { key: 'gazetteer', prompt: gazetteerPrompt },
  { key: 'narrative', prompt: narrativePrompt },
]
if (args && args.webSearch === true) {
  log('webSearch=true: adding the three regional independent-source lenses')
  for (const r of REGIONS) lenses.push({ key: 'sources-' + r.key, prompt: sourcePrompt(r.region) })
} else {
  log('webSearch not requested: skipping the three regional independent-source lenses (offline gazetteer + geo + narrative still run)')
}

const verdicts = await parallel(lenses.map((l) => () =>
  agent(l.prompt, { model: MID, phase: 'Verify', label: 'verify:' + l.key, schema: FINDINGS })))
const all = verdicts.filter(Boolean)
const findings = all.flatMap((v, i) => (v.findings || []).map((f) => ({ lens: lenses[i] ? lenses[i].key : 'unknown', ...f })))
const confirmed = all.map((v) => v.summary || '').join('\n')
log('Verification: ' + all.length + '/' + lenses.length + ' lenses returned. Findings: ' + findings.length +
  ' (blockers ' + findings.filter((f) => f.severity === 'blocker').length +
  ', major ' + findings.filter((f) => f.severity === 'major').length +
  ', minor ' + findings.filter((f) => f.severity === 'minor').length + ')')

// ---------------------------------------------------------------- fix
phase('Fix')
if (findings.length === 0) {
  log('No findings — skipping the fixer, nothing to apply')
  return { findings: 0, fix: null }
}

const fix = await agent(PRE + `
TASK: apply verification findings to ${DATA}/* (you own nodes.geojson, pois.geojson,
segments.geojson, sections.json, routes.json for this step — no other agent may be writing
to ${DATA} at the same time).
FINDINGS (JSON, from independent verifiers; lens 'geo' = DEM/land checks, 'gazetteer' =
offline Overture cross-check, 'sources-*' = live web sources, 'narrative' = text facts):
${JSON.stringify(findings, null, 1)}

VERIFIER SUMMARIES (may contain 'CONFIRMED: ...' lists of ids independently confirmed):
${confirmed}

Rules:
1. Apply every 'blocker' and 'major' finding unless two findings contradict each other; in
   that case use your own judgement (WebSearch if you have budget) and record the decision
   in the feature's 'notes' (nodes) or keep it out and list it in your return. Apply 'minor'
   findings when the fix is unambiguous and cheap.
2. When a coordinate moves, also move the first/last vertex of any segment that starts/ends
   at that node, and re-check the sketch stays on land.
3. Confidence: set 'verified' for ids in CONFIRMED lists that also had no geo/gazetteer
   finding against them; downgrade to 'unverified' anything a verifier could not find at
   all; otherwise leave as is. Append verifier URLs to 'sources' when given.
4. Update hazard_level texts with the latest dated status given by the narrative lens.
5. Re-validate all five files: python3 ${REPO}/pipeline/validate.py --data ${DATA} --schemas ${REPO}/schemas
   and re-check referential integrity/chains. Fix mechanical validation failures your own
   edits introduced.
Return ok=true only if validation passes; list files changed and the findings you
deliberately skipped with the reason.`, { model: MID, phase: 'Fix', label: 'apply-fixes', schema: RESULT })

log('Fix: ' + (fix && fix.ok ? 'ok' : 'issues remain') + ' — ' + (fix ? fix.summary : 'fixer agent returned nothing'))
return { findingsByLens: Object.fromEntries(lenses.map((l) => [l.key, findings.filter((f) => f.lens === l.key).length])), findings: findings.length, fix }
