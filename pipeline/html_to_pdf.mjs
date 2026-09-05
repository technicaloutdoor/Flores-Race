// html_to_pdf.mjs -- print a local HTML file to PDF with Chromium (Playwright).
// Usage: NODE_PATH=/opt/node22/lib/node_modules node pipeline/html_to_pdf.mjs in.html out.pdf
import { createRequire } from 'node:module';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const [,, input, output] = process.argv;
if (!input || !output) { console.error('usage: html_to_pdf.mjs in.html out.pdf'); process.exit(2); }
const exe = process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium';
const browser = await chromium.launch({ executablePath: exe });
const page = await browser.newPage({ viewport: { width: 1240, height: 1754 } });
await page.goto('file://' + path.resolve(input), { waitUntil: 'load' });
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(500);
await page.pdf({ path: output, format: 'A4', printBackground: true, preferCSSPageSize: true, displayHeaderFooter: false });
await browser.close();
console.log('wrote', output);
