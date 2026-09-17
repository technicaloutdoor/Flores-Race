# Deployment: GitHub Pages and CI/CD

The Flores Race Planner is deployed as a static site on GitHub Pages via GitHub Actions. This document covers the setup, the CI/CD workflows, and the public build option.

## One-time repository setup

1. **Enable GitHub Pages**:
   - Go to Settings → Pages.
   - Under "Build and deployment," select **Source: GitHub Actions**.
   - Save.
   - This authorizes Actions workflows to publish to the `gh-pages` branch and serve it at `https://github.com/<user>/<repo>/`.

2. **Base path configuration**:
   - The site is served at `/Flores-Race/` (not the root), because it is a repository's Pages site, not a user/org Pages site.
   - The build sets `VITE_BASE=/Flores-Race/` so all asset and data URLs are prefixed correctly.

That's all you need to do once. Every push to the `main` branch will trigger the deploy workflow (see below).

## CI/CD workflows

Two workflows automate validation and deployment:

### `validate.yml` (runs on every PR and push to main)

**Purpose:** Ensure data integrity and a working build before merging.

**What it does** (as specified in `pipeline/validate.py` and web build):
1. Validate `data/` against `schemas/` (JSON Schema + referential integrity).
2. Build the web app with Vite (`npm run build`).
3. Optionally run tests and linting.
4. Exit non-zero if there are errors; warnings are printed but do not block.

**Workflow file:** `.github/workflows/validate.yml`

### `deploy.yml` (runs on push to main only)

**Purpose:** Run the full pipeline and deploy the built site to GitHub Pages.

**What it does** (as specified in ARCHITECTURE.md, section 9):
1. Check out the repository.
2. Set up Python and Node.js.
3. Run `pip install -r pipeline/requirements.txt`.
4. Run pipeline stages to fetch open data and build the web bundle:
   - `fetch_overture.py --out .cache/overture ...`
   - `fetch_dem.py --out .cache/dem`
   - `fetch_boundaries.py --out .cache/boundaries`
   - `fetch_naturalearth.py --out .cache/naturalearth`
   - `build_network.py --overture-dir ... --dem-dir ... --out .cache/network`
   - `build_profiles.py --dem-dir ... --out .cache/profiles`
   - `validate.py --data data --schemas schemas`
   - `build_web_data.py --dem-dir ... --regencies ... --overture-dir ... --out web/public/data`
5. Install web dependencies and build: `cd web && npm install && npm run build`.
6. Deploy the built `web/dist/` to GitHub Pages.

**Workflow file:** `.github/workflows/deploy.yml`

**Notes:**
- `.cache/` (downloads, intermediate files) is not committed and does not persist between runs; re-downloading is intentional (always uses the latest open data).
- Build artifacts (GeoJSON files under `web/public/data/`) are generated in CI; only source data under `data/` is committed.
- The deploy workflow runs only on pushes to `main` (not on feature branches) to avoid polluting the deployed site during development.

## Public build mode

The `--public-build` flag in `build_web_data.py` filters the data bundle to exclude features not opted into the public site:

```bash
build_web_data.py --data data --dem-dir ... --regencies ... --public-build --out web/public/data
```

**What gets filtered:**
- **Nodes:** Dropped if `public != true`.
- **POIs:** Dropped if `public != true`.
- **Segments:** Dropped if `public != true`.
- **Sections:** Dropped if `public != true`.
- **Routes:** Dropped if `public` is not in the `audience` list.

**Why this exists:**
- During the planning phase, the team may want to keep sensitive details (controversial routing decisions, permission negotiations, land owner contacts) out of public view.
- Later, a public teaser site can be built from the same code, using the `--public-build` flag, and deployed to a separate GitHub Pages site or custom domain.

**Important: public mode is NOT a security boundary.**

The repository is public. Every file in `data/`, including all scouting notes, is readable by anyone who clones the repository. The `public` flag and `--public-build` filter only control what the *web app* displays; they do not hide files from git. If you need to keep material confidential during planning, either:

1. **Make the repository private** until the planning phase is complete (recommended during active scouting).
2. **Keep sensitive material outside the repository** (store permission agreements and contact details in a separate private document or email thread).
3. **Use a git pre-commit hook** to prevent accidental commits of sensitive files (e.g. a `private/` directory with a `.gitignore`).

## Custom domain

To serve the site from a custom domain (e.g. `flores-race.example.com`) instead of the GitHub Pages URL:

1. **Add a DNS CNAME record** pointing to `github.io`:
   ```
   flores-race.example.com  CNAME  <user>.github.io
   ```
   
2. **In the repository settings** (Settings → Pages), enter the custom domain under "Custom domain."

3. **Update `vite.config.ts`** to reflect the new base if needed (usually no change is required if the site is served from the root of the domain).

GitHub will auto-renew the HTTPS certificate and enforce HTTPS redirects.

## Rebuilding the site locally

To test the build pipeline on your laptop:

```bash
# Install Python and Node dependencies
pip install -r pipeline/requirements.txt
cd web && npm install && cd ..

# Run a subset of the pipeline (requires DEM tiles to be cached)
python3 pipeline/fetch_dem.py --out .cache/dem
python3 pipeline/fetch_boundaries.py --out .cache/boundaries
python3 pipeline/build_profiles.py --dem-dir .cache/dem --out web/public/data
python3 pipeline/validate.py --data data --schemas schemas

# Build the web app
cd web && npm run build && cd ..
```

The built site is in `web/dist/` and can be served locally with `npx http-server web/dist/`.

## References

- [GitHub Pages documentation](https://docs.github.com/en/pages)
- [GitHub Actions workflows](https://docs.github.com/en/actions/using-workflows)
- See `.github/workflows/validate.yml` and `.github/workflows/deploy.yml` for the actual workflow definitions.
- See `ARCHITECTURE.md` section 9 for the architecture rationale.
