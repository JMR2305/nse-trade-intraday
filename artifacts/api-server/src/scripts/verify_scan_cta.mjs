/* Browser E2E check — "Run Fresh Scan Now" clears the stale-scan block (mocked open market).
 * Run: node artifacts/api-server/src/scripts/verify_scan_cta.mjs (API server + dashboard workflows must be running) — verify "Run Fresh Scan Now" clears stale-scan block (mocked open market). */
const puppeteer = (await import('puppeteer-core')).default;

const BASE = 'http://localhost:80';
const PAGE = BASE + '/trading-dashboard/ai-paper-trader';

(async () => {
  const browser = await puppeteer.launch({
    executablePath: process.env.CHROMIUM_BIN || (await import('node:child_process')).execSync('which chromium').toString().trim(),
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1000 });

  let scanPosts = 0;
  let scanTriggered = false; // after button click, pipeline responses become "fresh"

  await page.setRequestInterception(true);
  page.on('request', async (req) => {
    const url = req.url();
    try {
      if (url.includes('/api/live-data/scan/run') && req.method() === 'POST') {
        scanPosts += 1;
        // delay 1200ms so a rapid second click lands while isPending
        await new Promise(r => setTimeout(r, 1200));
        scanTriggered = true;
        return req.respond({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ started: true, status: 'RUNNING' }),
        });
      }
      if (url.includes('/api/phase20/pipeline')) {
        // fetch real payload then mutate gate state
        const res = await fetch(BASE + '/api/phase20/pipeline');
        const d = await res.json();
        const gs = d.gate_summary || {};
        if (!scanTriggered) {
          // mocked OPEN market + stale scan
          gs.market_closed = false;
          gs.scan_stale = true;
          gs.failed_global_gates = ['scan_fresh'];
          gs.global_blocked_counts = { scan_fresh: gs.total_buy_signals };
        } else {
          // fresh scan landed: all global gates green
          gs.market_closed = false;
          gs.scan_stale = false;
          gs.failed_global_gates = [];
          gs.global_blocked_counts = {};
          d.first_blocker = null;
          for (const f of d.funnel || []) {
            if (f.stage === 'global_gates') {
              f.passed = true; f.blocker = false; f.count = 1;
              f.detail = 'All global gates green';
              for (const g of f.gates || []) { g.passed = true; }
            }
          }
        }
        d.gate_summary = gs;
        return req.respond({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(d),
        });
      }
      return req.continue();
    } catch (e) {
      try { req.continue(); } catch {}
    }
  });

  console.log('Loading page…');
  await page.goto(PAGE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await new Promise(r => setTimeout(r, 12000)); // let queries settle

  // Expand the Execution Pipeline panel
  const expanded = await page.evaluate(() => {
    const h2s = [...document.querySelectorAll('h2')];
    const h = h2s.find(x => /execution pipeline/i.test(x.textContent || ''));
    if (!h) return 'no-panel';
    const panel = h.closest('div.border.rounded-xl') || h.closest('div');
    const root = h.parentElement.parentElement.parentElement; // panel root
    const btn = [...root.querySelectorAll('button')].find(b => /expand/i.test(b.textContent || ''));
    if (!btn) return 'no-expand-btn';
    btn.click();
    return 'ok';
  });
  console.log('Expand:', expanded);
  await new Promise(r => setTimeout(r, 1000));

  const state1 = await page.evaluate(() => ({
    staleBanner: !!([...document.querySelectorAll('p')].find(p => /Scan data is stale/i.test(p.textContent || ''))),
    marketClosedGuidance: !!([...document.querySelectorAll('p')].find(p => /Market is closed\. Run a fresh scan during market hours/i.test(p.textContent || ''))),
    scanBtn: !!([...document.querySelectorAll('button')].find(b => /Run Fresh Scan Now/i.test(b.textContent || ''))),
    scanFreshChip: !!([...document.querySelectorAll('span')].find(s => /scan_fresh: blocks all/i.test(s.textContent || ''))),
  }));
  console.log('STATE 1 (stale + market open):', JSON.stringify(state1));

  await page.screenshot({ path: '/tmp/612-1-stale-open.png' });

  // Double-click rapidly — second click should be ignored (disabled while pending)
  const clicked = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find(b => /Run Fresh Scan Now/i.test(b.textContent || ''));
    if (!btn) return false;
    btn.click();
    // discrete follow-up clicks while the mutation is pending (button disabled)
    setTimeout(() => btn.click(), 100);
    setTimeout(() => btn.click(), 400);
    return true;
  });
  console.log('Clicked button:', clicked);
  await new Promise(r => setTimeout(r, 600));
  const pendingState = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find(b => /Fresh Scan|Scan started/i.test(b.textContent || ''));
    return btn ? { text: btn.textContent.trim(), disabled: btn.disabled } : null;
  });
  console.log('While pending:', JSON.stringify(pendingState), 'POSTs so far:', scanPosts);

  // onSuccess invalidates pipeline after 5s → wait, then check refreshed state
  await new Promise(r => setTimeout(r, 9000));
  const btnAfter = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find(b => /Fresh Scan|Scan started/i.test(b.textContent || ''));
    return btn ? btn.textContent.trim() : null;
  });
  console.log('Button after success:', JSON.stringify(btnAfter));

  const state2 = await page.evaluate(() => ({
    staleBanner: !!([...document.querySelectorAll('p')].find(p => /Scan data is stale/i.test(p.textContent || ''))),
    scanFreshChip: !!([...document.querySelectorAll('span')].find(s => /scan_fresh: blocks all/i.test(s.textContent || ''))),
    flowingChips: !!([...document.querySelectorAll('span')].find(s => /No gate blocks recorded/i.test(s.textContent || ''))),
    globalGatesGreen: !!([...document.querySelectorAll('span')].find(s => /All global gates green/i.test(s.textContent || ''))),
  }));
  console.log('STATE 2 (after fresh scan lands):', JSON.stringify(state2));
  console.log('TOTAL scan/run POSTs:', scanPosts);

  await page.screenshot({ path: '/tmp/612-2-cleared.png' });

  const pass =
    state1.staleBanner && state1.scanBtn && !state1.marketClosedGuidance && state1.scanFreshChip &&
    !state2.staleBanner && !state2.scanFreshChip && (state2.flowingChips || state2.globalGatesGreen) &&
    scanPosts === 1;
  console.log(pass ? 'RESULT: PASS' : 'RESULT: FAIL');
  await browser.close();
  process.exit(pass ? 0 : 1);
})().catch(e => { console.error('ERROR:', e); process.exit(2); });
