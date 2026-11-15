// Optional authoring tool. Requires Playwright and an installed Chrome/Chromium.
// Runtime application dependencies do not include this presentation-only tool.
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import fs from 'node:fs/promises';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
const app = process.env.GENAIUS_DEMO_URL || 'http://127.0.0.1:8783';
await fs.mkdir(path.join(root, 'assets'), { recursive: true });
const errors = [];
page.on('pageerror', e => errors.push(e.message));
if (process.argv.includes('--capture')) {
  const captures = [
    ['material-lab.html', '#s-scatter', 'material-lab.png', '#scatter svg'],
    ['fire.html', '#sc-out', 'scenario.png', '#sc-out .sc-badge'],
    ['fire.html', '#fp-cards', 'models.png', '#fp-card-k h3'],
    ['case-saffire.html', '#s-story', 'case-timeline.png', '#timeline-out .cs-track'],
    ['data.html', '#s-explorer', 'data-records.png', '#rows table']
  ];
  for (const [route, selector, filename, ready] of captures) {
    await page.goto(app + '/' + route, { waitUntil: 'networkidle' });
    await page.evaluate(() => window.FF?.i18n?.set('en'));
    await page.locator(ready).first().waitFor({ timeout: 30000 });
    if (filename === 'scenario.png') {
      await page.locator('#sc-fuel').selectOption('PMMA');
      await page.locator('#o2').evaluate(el => { el.value = '34'; el.dispatchEvent(new Event('input', { bubbles: true })); });
      await page.locator('#g').evaluate(el => { el.value = '0.166'; el.dispatchEvent(new Event('input', { bubbles: true })); });
      await page.waitForFunction(() => document.querySelector('#sc-out .sc-badge')?.textContent === 'GAP');
    }
    // Hide only shared floating chrome; leave the actual evidence/UI unchanged.
    await page.addStyleTag({ content: '.gn-nav,.gn-lang,.gc-launch,.gc-drawer{visibility:hidden!important}' });
    if (filename === 'data-records.png') {
      // Crop the table viewport to its first visible records; retain original values.
      await page.addStyleTag({ content: '#rows{max-height:420px!important;overflow:hidden!important}' });
    }
    await page.locator(selector).screenshot({ path: path.join(root, 'assets', filename), animations: 'disabled' });
    console.log('Captured ' + filename);
  }
}
await page.setViewportSize({ width: 1600, height: 900 });
await page.goto(pathToFileURL(path.join(root, 'index.html')).href, { waitUntil: 'networkidle' });
await page.evaluate(() => document.fonts.ready);
await page.emulateMedia({ media: 'print' });
await page.pdf({ path: path.join(root, 'genaius-presentation.pdf'), printBackground: true, preferCSSPageSize: true });
await page.emulateMedia({ media: 'screen' });
await page.evaluate(() => window.goSlide(0));
await page.keyboard.press('ArrowRight');
if (await page.locator('#counter').textContent() !== '2 / 7') throw Error('Keyboard navigation failed');
await page.keyboard.press('n');
if (!await page.locator('#speaker').isVisible()) throw Error('Presenter notes failed');
await page.keyboard.press('n');
await page.keyboard.press('End');
if (await page.locator('#counter').textContent() !== '7 / 7') throw Error('End navigation failed');
await page.keyboard.press('Home');
const previews = process.env.PRESENTATION_PREVIEW_DIR;
if (previews) {
  await fs.mkdir(previews, { recursive: true });
  for (let i = 0; i < 7; i++) {
    await page.evaluate(n => window.goSlide(n), i);
    await page.screenshot({ path: path.join(previews, 'slide-' + (i + 1) + '.png') });
  }
}
const overflow = await page.evaluate(() => Array.from(document.querySelectorAll('.slide')).map((s, i) => ({ slide: i + 1, overflow: s.scrollHeight > s.clientHeight + 2 })));
console.log(JSON.stringify({ pageErrors: errors, overflow }));
await browser.close();
if (errors.length || overflow.some(x => x.overflow)) process.exitCode = 1;
