// Builds nothing itself — run `npm run build` first. Serves `web/dist` with `vite preview` on a
// free port, opens each mode at desktop and mobile sizes with `base=none` (see BRIEF: tile/glyph
// servers are blocked from this sandbox, so `none` is the only basemap that screenshots our own
// data), waits for the map's first 'idle' event (exposed as `window.__mapIdle` by main.ts), and
// saves PNGs. Fails the run if any console/page error looks like it came from our own code —
// network failures for tiles/glyphs are expected here and ignored.
import { chromium } from 'playwright';
import { preview } from 'vite';
import { mkdirSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const OUT_DIR =
  '/tmp/claude-0/-home-user-Flores-Race/b0c9f08e-484f-59bd-8f71-53c6d7b99ea1/scratchpad/screenshots';

const MODES = ['stakeholder', 'scout', 'public'];
const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
];

// No `route=` is pinned here on purpose: the app now picks its own default (the first route in
// routes.json whose audience includes the current mode -- see data/visibility.ts's
// `defaultRouteId`), and these screenshots are meant to show that real default, not override it.
// `SEL_ID` still names a concrete segment id so the inspector (and the elevation profile) always
// has something real to draw, regardless of which route ends up selected.
const SEL_ID = 's-labuan-bajo-sano-nggoang-a';

// r-traverse is the hand-sketched "concept corridor" Traverse variant, visible in every mode (its
// `audience` includes stakeholder, scout and public -- see data/routes.json) but not the default
// for stakeholder/scout (they default to r-traverse-remote, the network-routed variant). One extra
// desktop shot with it explicitly selected keeps the sketch-corridor view covered too.
const EXTRA_ROUTE_ID = 'r-traverse';

// Expected in this build sandbox (BRIEF "Sandbox network reality"): tile servers, MapLibre demo
// glyphs, and our own network.geojson.gz (deliberately absent from the fixture) all fail to load.
const IGNORE_PATTERNS = [
  /opentopomap/i,
  /arcgisonline/i,
  /tile\.openstreetmap/i,
  /openstreetmap\.org/i,
  /demotiles\.maplibre/i,
  /elevation-tiles-prod/i,
  /network\.geojson\.gz/i,
  /favicon/i,
  /net::ERR_/i,
  /ERR_CONNECTION/i,
  /ERR_NAME_NOT_RESOLVED/i,
  /ERR_PROXY_CONNECTION_FAILED/i,
  /Failed to fetch/i,
  /NetworkError when attempting to fetch resource/i,
  /404 \(Not Found\)/i,
  /403 \(Forbidden\)/i,
];

function isIgnorable(text) {
  return IGNORE_PATTERNS.some((re) => re.test(text));
}

const CHROMIUM_PATH = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });

  const server = await preview({ root: ROOT, preview: { host: '127.0.0.1', strictPort: false } });
  const baseURL = server.resolvedUrls?.local?.[0];
  if (!baseURL) throw new Error('vite preview did not report a local URL');
  console.log(`Preview server: ${baseURL}`);

  const browser = await chromium.launch({
    executablePath: existsSync(CHROMIUM_PATH) ? CHROMIUM_PATH : undefined,
    args: ['--no-sandbox'],
  });

  /** @type {Array<{ label: string, errors: string[] }>} */
  const failures = [];

  /** Opens `label` at `viewport` and `hash`, waits for the map to settle, and saves a PNG. */
  async function shoot(label, viewport, hash) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
    });
    const page = await context.newPage();
    const errors = [];

    page.on('console', (msg) => {
      if (msg.type() !== 'error') return;
      const text = msg.text();
      if (!isIgnorable(text)) errors.push(`console: ${text}`);
    });
    page.on('pageerror', (err) => {
      errors.push(`pageerror: ${err.message ?? String(err)}`);
    });

    const url = `${baseURL}#${hash}`;
    await page.goto(url, { waitUntil: 'load' });
    await page.waitForFunction(() => window.__mapIdle !== undefined, undefined, {
      timeout: 15000,
    });
    await page.evaluate(() => window.__mapIdle);
    await page.waitForTimeout(300); // let the last paint settle

    const filePath = path.join(OUT_DIR, `${label}.png`);
    await page.screenshot({ path: filePath });
    console.log(`Saved ${filePath}`);

    if (errors.length) failures.push({ label, errors });
    await context.close();
  }

  try {
    for (const mode of MODES) {
      for (const viewport of VIEWPORTS) {
        // No `z=`/`c=` either: with neither in the hash, the app fits the whole island itself on
        // load (map/fit.ts's `fitIsland`) -- these screenshots are the check that it actually does.
        await shoot(`${mode}-${viewport.name}`, viewport, `mode=${mode}&base=none&sel=${SEL_ID}`);
      }
    }

    // One extra desktop shot with the hand-sketched "concept corridor" Traverse variant explicitly
    // selected (see EXTRA_ROUTE_ID above) -- stakeholder/scout otherwise only ever see the
    // network-routed default, and the sketch-corridor view is worth keeping covered too.
    await shoot(
      'stakeholder-desktop-concept-sketch',
      VIEWPORTS.find((v) => v.name === 'desktop'),
      `mode=stakeholder&base=none&route=${EXTRA_ROUTE_ID}&sel=${SEL_ID}`,
    );
  } finally {
    await browser.close();
    await server.close();
  }

  if (failures.length) {
    console.error(`\n${failures.length} page(s) had console/page errors that look like our bugs:`);
    for (const f of failures) {
      console.error(`  ${f.label}:`);
      for (const e of f.errors) console.error(`    ${e}`);
    }
    process.exitCode = 1;
    return;
  }

  console.log('\nAll screenshots captured with no unexpected console errors.');
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
