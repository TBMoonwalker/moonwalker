// TEMP-FONTDIAG (2026-11-26): diagnose the ubuntu-24.04 chromium mono-width
// failure on PR #214 - remove after the root cause is fixed.
import { execSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'

/**
 * Rendered accessibility verification (TODOS.md "Verify remaining rendered
 * accessibility observations", planned 2026-11-10):
 *
 * - V2 pagination touch targets: 44x44px item boxes on phone width (the
 *   DESIGN.md "minimum 44px touch targets on mobile" rule), and the 28px Naive
 *   default at desktop and tablet width (the documented phone-width scope;
 *   the tablet outcome is a measured, recorded exception).
 * - V3 compact table typography: body 16px; statistics ledger at the
 *   documented 12px headers / 14px cells; trade ledger tables at the
 *   documented compact exception (11px headers / 13px cells, see the
 *   DESIGN.md deviation log); control-center mission summary 16px.
 * - V1 rendered half of dark-mode contrast: the forced dark/light themes
 *   resolve the token map — the `--mw-*` custom properties on `:root` match
 *   `frontend/src/theme/tokens.ts` and real elements resolve to their token
 *   colors. The offline WCAG contrast ratios for these exact values live in
 *   the verification report (all pairs pass AA in both schemes).
 */

const PHONE_TOUCH_TARGET_PX = 44
const NAIVE_DEFAULT_PAGINATION_PX = 28

const completeDryRunConfig = {
  timezone: 'Europe/Vienna',
  signal: 'csv_signal',
  signal_settings: JSON.stringify({ csv_source: 'signals.csv' }),
  exchange: 'binance',
  timeframe: '1h',
  key: 'test-key',
  secret: 'test-secret',
  currency: 'USDC',
  max_bots: 2,
  bo: 10,
  tp: 1,
  capital_max_fund: 100,
  history_lookback_time: '180d',
  dca: false,
  dry_run: true,
  mstc: 4,
  trading_paused: false,
  trade_mode: 'dynamic_dca',
  config_revision: 0,
  config_updated_at: '2026-07-25T12:00:00Z',
}

// Readiness with every essential present except `tp` -> `attention_needed`
// (not first-run, not complete) -> the mission panel renders its
// `.mission-summary` line (hidden only for the `healthy` view state).
const attentionDryRunConfig = { ...completeDryRunConfig, tp: null }

function closedTradeRow(index: number) {
  return {
    id: index + 1,
    symbol: `SYM${String(index).padStart(2, '0')}/USDC`,
    deal_id: null,
    execution_history_complete: true,
    amount: 1 + index,
    cost: 10,
    tp_price: 12,
    avg_price: 10,
    profit: 0.5,
    profit_percent: 5,
    so_count: 1,
    open_date: '2026-01-01T00:00:00Z',
    duration: '1 day',
    close_date: '2026-01-02T00:00:00Z',
    close_reason: 'take_profit',
    precision: 2,
    key: index + 1,
  }
}

function analyticsOverviewFixture(perSymbolCount: number) {
  return {
    summary: {
      total_trades: perSymbolCount,
      profit_trades: 1,
      loss_trades: 0,
      win_rate: 100,
      total_profit: 1,
      avg_profit: 1,
      avg_profit_percent: 1,
      avg_duration_formatted: '1 day',
      total_cost: 10,
    },
    heatmap_daily: [],
    heatmap_weekly: [],
    per_symbol: Array.from({ length: perSymbolCount }, (_, i) => ({
      symbol: `SYM${String(i).padStart(2, '0')}/USDC`,
      trades: perSymbolCount - i,
      win_rate: 50,
      total_profit: 1.5 * (i + 1),
      avg_profit: 0.2,
      avg_duration_formatted: '1 day',
    })),
    duration_extremes: { longest: [], shortest: [] },
    drawdown: { max_drawdown: 0, max_drawdown_percent: 0 },
    distribution: { bins: [], median: 0, std_dev: 0, best: 0, worst: 0 },
    ai_trust: {
      enabled: false,
      enforce_warnings: false,
      configured: false,
      provider: '',
      model_name: null,
      status: 'disabled',
      coverage: { total: 0, scored: 0, unscored: 0, closed: 0, coverage_rate: 0 },
      quality: {
        warning_hit_rate: 0,
        warning_false_positive_rate: 0,
        recent_window_trades: 0,
      },
      recent_predictions: [],
      bad_entry_review: [],
    },
  }
}

interface MockBootOptions {
  closedRows?: number
  perSymbol?: number
  config?: Record<string, unknown>
}

async function mockDashboardBoot(page: Page, options: MockBootOptions = {}) {
  const closedRows = options.closedRows ?? 12
  const perSymbol = options.perSymbol ?? 11
  const config = options.config ?? completeDryRunConfig
  const profit = {
    funds_available: 100,
    profit_overall: 1,
    funds_locked: 100,
    profit_overall_timestamp: '2026-10-29 08:00:00',
    performance_complete: true,
  }

  await page.routeWebSocket('**/trades/open*', (socket) => socket.send('[]'))
  await page.routeWebSocket('**/trades/closed', (socket) => {
    socket.send(JSON.stringify(Array.from({ length: closedRows }, (_, i) => closedTradeRow(i))))
  })
  await page.routeWebSocket('**/trades/unsellable', (socket) => socket.send('[]'))
  await page.routeWebSocket('**/statistic/profit*', (socket) => socket.send(JSON.stringify(profit)))
  await page.route('**/config/all', (route) => route.fulfill({ json: config }))
  await page.route('**/config/freshness', (route) => route.fulfill({ json: { config_revision: 1 } }))
  await page.route('**/analytics/overview**', (route) => route.fulfill({ json: analyticsOverviewFixture(perSymbol) }))
  await page.route('**/statistic/profit-overall/timeline', (route) => route.fulfill({ json: [] }))
  // Specific routes must precede the broader trade-page catch-all.
  await page.route('**/trades/closed/length', (route) => route.fulfill({ json: { result: closedRows } }))
  await page.route('**/trades/closed/**', (route) => route.fulfill({ json: { result: [] } }))
  await page.route('**/accumulation/**', (route) => route.fulfill({ status: 503, json: {} }))
  await page.route('**/orders/**', (route) => route.fulfill({ json: {} }))
}

type Box = { width: number; height: number }

function itemBoxes(selector: string) {
  return (page: Page) =>
    page.locator(`${selector} .n-pagination-item`).evaluateAll((items) =>
      items.map((el) => {
        const rect = el.getBoundingClientRect()
        return { width: rect.width, height: rect.height }
      }),
    )
}

async function openClosedTradesTable(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: /Closed trades/ }).click()
  await expect(page.locator('.ledger-panel .n-pagination').first()).toBeVisible()
}

test('closed-trades pagination items meet the 44px phone touch target', async ({ page, isMobile }, testInfo) => {
  test.skip(!isMobile, 'phone-width touch-target rule')
  await mockDashboardBoot(page, { closedRows: 12 })
  await openClosedTradesTable(page)
  const boxes = await itemBoxes('.ledger-panel .n-pagination')(page)
  expect(boxes.length).toBeGreaterThan(0)
  for (const box of boxes) {
    expect(box.width).toBeGreaterThanOrEqual(PHONE_TOUCH_TARGET_PX)
    expect(box.height).toBeGreaterThanOrEqual(PHONE_TOUCH_TARGET_PX)
  }
  await page.screenshot({ path: testInfo.outputPath('closed-trades-pagination-phone.png') })
})

test('statistics symbol-table pagination items meet the 44px phone touch target', async ({ page, isMobile }, testInfo) => {
  test.skip(!isMobile, 'phone-width touch-target rule')
  await mockDashboardBoot(page, { perSymbol: 11 })
  await page.goto('/stats')
  await expect(page.getByRole('heading', { name: 'Statistics', exact: true })).toBeVisible()
  const pagination = page.locator('.tab-content .n-pagination')
  await expect(pagination).toBeVisible()
  const boxes = await pagination.locator('.n-pagination-item').evaluateAll((items) =>
    items.map((el) => {
      const rect = el.getBoundingClientRect()
      return { width: rect.width, height: rect.height }
    }),
  )
  expect(boxes.length).toBeGreaterThan(0)
  for (const box of boxes) {
    expect(box.width).toBeGreaterThanOrEqual(PHONE_TOUCH_TARGET_PX)
    expect(box.height).toBeGreaterThanOrEqual(PHONE_TOUCH_TARGET_PX)
  }
  await page.screenshot({ path: testInfo.outputPath('statistics-pagination-phone.png') })
})

test('pagination items stay at the Naive default above phone width', async ({ page, isMobile }) => {
  test.skip(isMobile, 'phone projects apply the 44px rule instead')
  await mockDashboardBoot(page, { closedRows: 12, perSymbol: 11 })

  await openClosedTradesTable(page)
  let boxes = await itemBoxes('.ledger-panel .n-pagination')(page)
  expect(boxes.length).toBeGreaterThan(0)
  for (const box of boxes) {
    expect(box.height).toBe(NAIVE_DEFAULT_PAGINATION_PX)
    expect(box.width).toBe(NAIVE_DEFAULT_PAGINATION_PX)
  }

  await page.goto('/stats')
  await expect(page.getByRole('heading', { name: 'Statistics', exact: true })).toBeVisible()
  await expect(page.locator('.tab-content .n-pagination')).toBeVisible()
  boxes = await itemBoxes('.tab-content .n-pagination')(page)
  expect(boxes.length).toBeGreaterThan(0)
  for (const box of boxes) {
    expect(box.height).toBe(NAIVE_DEFAULT_PAGINATION_PX)
    expect(box.width).toBe(NAIVE_DEFAULT_PAGINATION_PX)
  }
})

test('document typography matches the rendered DESIGN.md scale in light', async ({ page, isMobile }) => {
  test.skip(isMobile, 'desktop scale check')
  await mockDashboardBoot(page, { closedRows: 12, perSymbol: 11 })
  await openClosedTradesTable(page)
  const tradeMetrics = await page.evaluate(() => {
    const table = document.querySelector('.ledger-panel .n-data-table')
    const th = table?.querySelector('.n-data-table-th')
    const td = table?.querySelector('.n-data-table-td')
    const rootStyle = getComputedStyle(document.documentElement)
    return {
      body: getComputedStyle(document.body).fontSize,
      bodyColor: getComputedStyle(document.body).color,
      th: th ? getComputedStyle(th).fontSize : null,
      thColor: th ? getComputedStyle(th).color : null,
      td: td ? getComputedStyle(td).fontSize : null,
      mutedToken: rootStyle.getPropertyValue('--mw-color-text-muted').trim(),
      primaryToken: rootStyle.getPropertyValue('--mw-color-primary').trim(),
    }
  })
  expect(tradeMetrics.body).toBe('16px')
  // The trade ledger is the documented compact exception (DESIGN.md
  // deviation log): 11px uppercase headers, 13px cells — intentionally
  // outside the 12/14/16 scale, pinned here so it cannot drift silently.
  expect(tradeMetrics.th).toBe('11px')
  expect(tradeMetrics.td).toBe('13px')
  expect(tradeMetrics.mutedToken).toBe('#65656f')
  expect(tradeMetrics.primaryToken).toBe('#276b47')
  expect(tradeMetrics.bodyColor).toBe('rgb(69, 69, 78)')
  expect(tradeMetrics.thColor).toBe('rgb(101, 101, 111)')

  // The statistics ledger has no scoped override, so it renders at the
  // documented scale: 12px headers, 14px cells.
  await page.goto('/stats')
  await expect(page.getByRole('heading', { name: 'Statistics', exact: true })).toBeVisible()
  const statsMetrics = await page.evaluate(() => {
    const table = document.querySelector('.tab-content .n-data-table')
    const th = table?.querySelector('.n-data-table-th')
    const td = table?.querySelector('.n-data-table-td')
    return {
      th: th ? getComputedStyle(th).fontSize : null,
      td: td ? getComputedStyle(td).fontSize : null,
    }
  })
  expect(statsMetrics.th).toBe('12px')
  expect(statsMetrics.td).toBe('14px')
})

test('forced dark theme renders the dark token set on real elements', async ({ page, isMobile }, testInfo) => {
  test.skip(isMobile, 'token check runs at desktop width')
  await page.addInitScript(() => {
    window.localStorage.setItem('mw-theme-mode', 'dark')
  })
  await mockDashboardBoot(page, { closedRows: 12 })
  await openClosedTradesTable(page)
  const metrics = await page.evaluate(() => {
    const root = document.documentElement
    const rootStyle = getComputedStyle(root)
    const table = root.querySelector('.ledger-panel .n-data-table')
    const th = table?.querySelector('.n-data-table-th')
    return {
      dataMwTheme: root.getAttribute('data-mw-theme'),
      primary: rootStyle.getPropertyValue('--mw-color-primary').trim(),
      panel: rootStyle.getPropertyValue('--mw-color-surface-panel').trim(),
      textPrimary: rootStyle.getPropertyValue('--mw-color-text-primary').trim(),
      textSecondary: rootStyle.getPropertyValue('--mw-color-text-secondary').trim(),
      muted: rootStyle.getPropertyValue('--mw-color-text-muted').trim(),
      bodyColor: getComputedStyle(document.body).color,
      thColor: th ? getComputedStyle(th).color : null,
    }
  })
  expect(metrics.dataMwTheme).toBe('dark')
  expect(metrics.primary).toBe('#9cdb73')
  expect(metrics.panel).toBe('#222227')
  expect(metrics.textPrimary).toBe('#f5f5f7')
  expect(metrics.textSecondary).toBe('#c7c7d0')
  expect(metrics.muted).toBe('#a4a4af')
  expect(metrics.bodyColor).toBe('rgb(199, 199, 208)')
  expect(metrics.thColor).toBe('rgb(164, 164, 175)')
  await page.screenshot({ path: testInfo.outputPath('dashboard-forced-dark.png') })
})

test('control-center mission summary renders at 16px', async ({ page, isMobile }) => {
  test.skip(isMobile, 'desktop control-center check')
  await mockDashboardBoot(page, { config: attentionDryRunConfig })
  await page.goto('/control-center')
  const missionSummary = page.locator('.mission-summary')
  await expect(missionSummary).toBeVisible()
  expect(await missionSummary.evaluate((el) => getComputedStyle(el).fontSize)).toBe('16px')
})

/**
 * Self-hosted font-face contract (2026-11-25 design review, DV-1..DV-6):
 * the 9 declared faces must resolve to the vendored woff2 files (a missing,
 * corrupted, or misnamed file degrades to the fallback stack), the unused
 * Zodiak faces carried by the old Fontshare CSS must not be vendored, and
 * the mono face must keep its exact metrics (IBM Plex Mono is a true
 * monospace: every glyph advances 600/1000em).
 *
 * The face-state gate is what makes this spec real: document.fonts.check()
 * returns true vacuously when no @font-face matches the requested family at
 * all (verified 2026-11-26), so a check()-only gate stays green when the
 * rules or files are missing entirely - the probe then silently renders in
 * the platform fallback, and only the metric assertion notices, and only if
 * the platform fallback differs from 0.6em (a coincidence that holds on
 * macOS, where `monospace` resolves to a 600-unit face). Every declared
 * face must therefore exist in the document as a FontFace that is loaded
 * and whose unicode-range covers the probe digits; with that in place the
 * width assertion pins the exact metrics of the loaded bytes.
 */
const MONO_PROBE_STRING = '1,234.56'
const MONO_PROBE_BASELINE_PX = 76.8 // 8 glyphs x 0.6em at 16px
const MONO_PROBE_TOLERANCE = 0.02 // subpixel/platform rounding guard

test.beforeAll(() => {
  try {
    console.log(
      '[fontdiag] fc-match monospace:',
      execSync('fc-match monospace', { encoding: 'utf8' }).trim(),
    )
  } catch (e) {
    console.log('[fontdiag] fc-match unavailable:', (e as Error).message.slice(0, 200))
  }
  try {
    console.log(
      '[fontdiag] spacing=10 fonts:',
      execSync('fc-list :spacing=10 family 2>/dev/null | sort -u | head -15', { encoding: 'utf8' })
        .trim()
        .split('\n')
        .join(' | '),
    )
  } catch {
    console.log('[fontdiag] fc-list unavailable (no fontconfig)')
  }
})

test('self-hosted font faces resolve to the vendored faces', async ({ page, isMobile }) => {
  test.skip(isMobile, 'desktop font-face check')
  await mockDashboardBoot(page, { closedRows: 12, perSymbol: 11 })
  await openClosedTradesTable(page)

  const fontState = await page.evaluate(async (probeString: string) => {
    const faces: Array<[string, number]> = [
      ['Inter', 400],
      ['Inter', 500],
      ['Inter', 600],
      ['Inter', 700],
      ['IBM Plex Mono', 400],
      ['IBM Plex Mono', 500],
      ['Source Sans 3', 400],
      ['Source Sans 3', 500],
      ['Source Sans 3', 600],
    ]
    // load() forces every declared face to fetch and parse; a face whose
    // @font-face src is missing or broken resolves in the error state, and
    // the face-state assertions below then fail for it.
    await Promise.all(faces.map(([family, weight]) => document.fonts.load(`${weight} 16px '${family}'`)))
    const coversCodePoint = (unicodeRange: string, code: number) =>
      unicodeRange
        .split(',')
        .map((part) => part.trim().replace(/^U\+?/i, ''))
        .some((part) => {
          const [lo, hi] = part.split('-').map((s) => parseInt(s, 16))
          return code >= lo && code <= (hi ?? lo)
        })
    const faceStates = faces.map(([family, weight]) => {
      const matching = [...document.fonts].filter(
        (face) => face.family === family && face.weight === String(weight),
      )
      return {
        family,
        weight: String(weight),
        present: matching.length > 0,
        loadedCovering: matching.some(
          (face) => face.status === 'loaded' && coversCodePoint(face.unicodeRange, 0x31),
        ),
      }
    })
    const probe = document.createElement('span')
    probe.style.cssText =
      'position:absolute;visibility:hidden;white-space:pre;font-family:var(--mw-font-mono);font-size:16px;font-weight:400'
    probe.textContent = probeString
    document.body.appendChild(probe)
    const monoWidth = probe.getBoundingClientRect().width
    const probeStyle = (() => {
      const cs = getComputedStyle(probe)
      return {
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        letterSpacing: cs.letterSpacing,
        fontStretch: cs.fontStretch,
      }
    })()
    probe.remove()
    // TEMP-FONTDIAG: isolate which family each probe renders in
    const measureWith = (family: string) => {
      const s = document.createElement('span')
      s.style.cssText = `position:absolute;visibility:hidden;white-space:pre;font-family:${family};font-size:16px;font-weight:400`
      s.textContent = probeString
      document.body.appendChild(s)
      const w = s.getBoundingClientRect().width
      s.remove()
      return w
    }
    // TEMP-FONTDIAG: font-metric (canvas) vs layout (getBoundingClientRect)
    // quantization check - canvas reads the font's hmtx advances without the
    // layout engine's pixel-grid rounding
    const canvasMeasure = (font: string) => {
      const c = document.createElement('canvas').getContext('2d')
      c.font = font
      return c.measureText(probeString).width
    }
    const measureGeometric = (family: string) => {
      const s = document.createElement('span')
      s.style.cssText = `position:absolute;visibility:hidden;white-space:pre;text-rendering:geometricPrecision;font-family:${family};font-size:16px;font-weight:400`
      s.textContent = probeString
      document.body.appendChild(s)
      const w = s.getBoundingClientRect().width
      s.remove()
      return w
    }
    const brand = document.querySelector('.brand-title')
    const brandStyle = brand ? getComputedStyle(brand) : null
    // The old Fontshare CSS also declared unused 'Zodiak' faces. A system
    // font named Zodiak would make document.fonts.check() lie, so assert on
    // the declared @font-face rules instead: the vendored set must not
    // include them.
    let zodiakFaceDeclared = false
    for (const sheet of Array.from(document.styleSheets)) {
      let rules: CSSRuleList
      try {
        rules = sheet.cssRules
      } catch {
        continue // cross-origin sheet; ours are local
      }
      for (const rule of Array.from(rules)) {
        if (
          rule instanceof CSSFontFaceRule &&
          (rule.style.fontFamily || '').includes('Zodiak')
        ) {
          zodiakFaceDeclared = true
        }
      }
    }
    return {
      faceStates,
      zodiakFaceDeclared,
      monoWidth,
      probeStyle,
      devicePixelRatio,
      // TEMP-FONTDIAG: per-family probe widths (remove with the diagnostics)
      diagWidths: {
        plexMonoOnly: measureWith("'IBM Plex Mono'"),
        systemMono: measureWith('monospace'),
        canvasPlexMono: canvasMeasure('400 16px "IBM Plex Mono"'),
        canvasSystemMono: canvasMeasure('400 16px monospace'),
        geometricPlexMono: measureGeometric("'IBM Plex Mono'"),
        geometricSystemMono: measureGeometric('monospace'),
      },
      brandFamily: brandStyle ? brandStyle.fontFamily : null,
      brandWeight: brandStyle ? brandStyle.fontWeight : null,
    }
  }, MONO_PROBE_STRING)

  // TEMP-FONTDIAG: log the full state for the CI run (remove after diagnosis)
  console.log('[fontdiag]', JSON.stringify(fontState))

  // Face-state gate: every declared face must be a real, loaded @font-face
  // whose unicode-range covers the probe digits. check() alone cannot prove
  // this - with no matching rule at all it returns true (vacuously) and the
  // probe silently renders in the platform fallback.
  for (const faceState of fontState.faceStates) {
    expect(
      faceState.present,
      `${faceState.family} ${faceState.weight}: no @font-face in the document - the probe would render in the platform fallback`,
    ).toBe(true)
    expect(
      faceState.loadedCovering,
      `${faceState.family} ${faceState.weight}: no loaded face covering the probe digits - the probe would render in the platform fallback`,
    ).toBe(true)
  }
  expect(fontState.zodiakFaceDeclared).toBe(false)
  // With a loaded, probe-covering face guaranteed by the gate above, the
  // width must be that face's own metrics. A wrong, corrupted, or
  // mis-substituted file that still parses and loads shows up here (any
  // non-0.6em fallback would as well); subpixel rounding stays inside the
  // tolerance.
  expect(Math.abs(fontState.monoWidth - MONO_PROBE_BASELINE_PX) / MONO_PROBE_BASELINE_PX).toBeLessThan(
    MONO_PROBE_TOLERANCE,
  )
  expect(fontState.brandFamily).toContain('Inter')
  expect(fontState.brandWeight).toBe('700')
})

test('mission alert title renders at the declared 600 emphasis', async ({ page, isMobile }) => {
  // 550 was never an importable weight: CSS matching already resolved it to
  // Inter 600 (static face set; search-up-first), so this change is a
  // declaration normalization and the rendered result is pinned here (DV-7,
  // 2026-11-25 design review; Inter replaced General Sans 2026-11-26 for
  // license compliance - see LICENSES/inter-OFL.txt).
  test.skip(isMobile, 'desktop control-center check')
  await mockDashboardBoot(page, { config: attentionDryRunConfig })
  await page.goto('/control-center')
  const title = page.locator('.mission-panel .n-alert-body__title').first()
  await expect(title).toBeVisible()
  const style = await title.evaluate((el) => {
    const s = getComputedStyle(el)
    return { family: s.fontFamily, weight: s.fontWeight }
  })
  expect(style.family).toContain('Inter')
  expect(style.weight).toBe('600')
})
