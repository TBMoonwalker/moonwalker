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
