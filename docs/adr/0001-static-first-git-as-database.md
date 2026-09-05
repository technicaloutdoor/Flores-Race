# ADR-0001: Static site, git as the database

**Status:** Accepted

**Context**
Organizing a remote, multi-week ultra-distance race requires collaborative planning across a small team with limited infrastructure. The planning state (route variants, scouting verdicts, POI metadata) is constantly changing and must be attributed, reviewable, and reversible. Hosting costs and ongoing server operations are constraints.

**Decision**
Deploy as a static site on GitHub Pages. The canonical source of truth (`data/`) is versioned in git, not a database. Every feature carries provenance (`sources`) and status. Edits from the field become pull requests: reviewable, diff-able, and reversible. The entire planning state is cloneable to a laptop for offline work.

**Consequences**
- No server operations, API keys, or hosting costs.
- Scouting team can work offline; edits are exported as patches and committed via PR.
- Every team member's fork + laptop is a full backup.
- Git history is the audit trail and undo mechanism.
- If collaboration becomes a bottleneck, a small hosted database can be added behind the `RouteStore` interface without touching the web app.

**Alternatives considered**
1. *Hosted database (e.g. Firebase, Supabase):* Adds infrastructure, keys, and cost; git-as-database provides the same collaboration without the bill.
2. *Google My Maps / Caltopo:* Vendor lock-in; no git history; hard to script analysis and reproducibility.
3. *Headless CMS (e.g. Strapi, Contentful):* Overkill for a fixed data schema; git provides version control and provenance for free.
