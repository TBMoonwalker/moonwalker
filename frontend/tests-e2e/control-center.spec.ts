import { expect, test } from '@playwright/test'

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

const strategyPalette = [
  {
    type: 'indicator',
    label: 'Indicator',
    category: 'Values',
    description: 'Technical indicator',
    params: { indicator: 'ema', length: 20, sample: 'current' },
  },
]

const builtinStrategy = {
  slug: 'ema_cross',
  name: 'EMA cross',
  description: 'EMA crossover',
  kind: 'builtin',
  is_builtin: true,
  duplicated_from: null,
  active_version: 1,
  draft_version: 1,
  lock_version: 1,
  validation_status: 'valid',
  available: true,
  missing_hooks: [],
}

const customStrategy = {
  ...builtinStrategy,
  slug: 'ema_cross_copy',
  name: 'EMA cross copy',
  kind: 'custom',
  is_builtin: false,
  duplicated_from: 'ema_cross',
}

function strategyDetail(strategy: Omit<typeof builtinStrategy, 'duplicated_from'> & { duplicated_from: string | null }) {
  return {
    ...strategy,
    ir: {
      schema_version: 1,
      slug: strategy.slug,
      name: strategy.name,
      description: strategy.description,
      kind: strategy.kind,
      root: 'ema',
      nodes: [
        {
          id: 'ema',
          type: 'indicator',
          params: { indicator: 'ema', length: 20, sample: 'current' },
          position: { x: 80, y: 80 },
        },
      ],
      connections: [],
    },
    validation: {
      status: 'valid',
      blocking_errors: [],
      required_history: { label: '20 candles', candles: 20 },
      hook_readiness: [
        { name: 'entry', ready: true, message: 'Ready' },
      ],
    },
    explanation: `${strategy.name} is ready.`,
    palette: strategyPalette,
  }
}

const openTrade = {
  id: 1,
  deal_id: 'deal-btc-usdc',
  campaign_id: 'campaign-btc-usdc',
  symbol: 'BTC/USDC',
  amount: 1,
  cost: 100,
  avg_price: 100,
  current_price: 101,
  tp_price: 102,
  profit: 1,
  profit_percent: 1,
  display_profit: 1,
  display_profit_percent: 1,
  so_count: 0,
  open_date: '2026-07-25T12:00:00Z',
  automation_paused: false,
  delisting_warning: false,
  delisting_check_unavailable: false,
}

const analyticsOverview = {
  summary: {
    total_trades: 12,
    profit_trades: 9,
    loss_trades: 3,
    win_rate: 75,
    total_profit: 42.5,
    avg_profit: 3.54,
    avg_profit_percent: 1.2,
    avg_duration_formatted: '4h 20m',
    total_cost: 1200,
  },
  heatmap_daily: [
    { timestamp: Date.parse('2026-07-24T00:00:00Z'), value: 5 },
    { timestamp: Date.parse('2026-07-25T00:00:00Z'), value: 7 },
  ],
  heatmap_weekly: [],
  per_symbol: Array.from({ length: 12 }, (_, index) => ({
    symbol: `COIN${index + 1}/USDC`,
    trades: 12 - index,
    win_rate: 75,
    total_profit: 20 - index,
    avg_profit: 2.5,
    avg_duration_formatted: '4h',
  })),
  duration_extremes: {
    longest: [],
    shortest: [],
  },
  drawdown: {
    max_drawdown: 8,
    max_drawdown_percent: 2.5,
  },
  distribution: {
    bins: [{ label: 'Positive', min: 0, max: 5, count: 9 }],
    median: 1.1,
    std_dev: 0.8,
    best: 5,
    worst: -2,
  },
  ai_trust: {
    enabled: true,
    enforce_warnings: false,
    configured: true,
    provider: 'ollama',
    model_name: 'local-test',
    status: 'ready',
    coverage: {
      total: 12,
      scored: 12,
      unscored: 0,
      closed: 12,
      coverage_rate: 100,
    },
    quality: {
      warning_hit_rate: 50,
      false_warning_rate: 10,
      bad_entry_capture_rate: 80,
      bad_entries: 3,
      warnings: 4,
    },
    provider_status_counts: { scored: 12 },
    calibration: {
      enabled: true,
      confidence: 'warming',
      confidence_thresholds: {
        warming: 10,
        usable: 30,
        confident: 100,
        symbol_usable: 10,
      },
      lookback_days: 90,
      sample_cap: 500,
      closed_samples: 12,
      shadow_effective_warning_threshold: 75,
      buckets: [],
      missed_bad_entry_clusters: [],
    },
    recent_predictions: [],
    bad_entry_review: [],
  },
}

test.beforeEach(async ({ page }) => {
  let customExists = true
  let customDetail = strategyDetail(customStrategy)
  let saveAttempts = 0

  await page.routeWebSocket('**/trades/open', (socket) => {
    socket.send(JSON.stringify([openTrade]))
  })
  await page.routeWebSocket('**/trades/closed', (socket) => {
    socket.send('[]')
  })
  await page.routeWebSocket('**/trades/unsellable', (socket) => {
    socket.send('[]')
  })
  await page.routeWebSocket('**/trades/waiting', (socket) => {
    socket.send('[]')
  })
  await page.routeWebSocket('**/statistic/profit', (socket) => {
    socket.send(
      JSON.stringify({
        profit_overall: 42.5,
        upnl: 1,
        funds_locked: 100,
        funds_available: 500,
        funds_tradable: 400,
        autopilot: 'none',
      }),
    )
  })
  await page.route('**/config/all', async (route) => {
    await route.fulfill({ json: completeDryRunConfig })
  })
  await page.route('**/config/freshness', async (route) => {
    await route.fulfill({
      json: { updated_at: completeDryRunConfig.config_updated_at, config_revision: 0 },
    })
  })
  await page.route('**/analytics/overview**', async (route) => {
    await route.fulfill({ json: analyticsOverview })
  })
  await page.route('**/strategies**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/strategies') && request.method() === 'GET') {
      await route.fulfill({
        json: {
          strategies: [
            builtinStrategy,
            ...(customExists
              ? [
                  {
                    ...customStrategy,
                    name: customDetail.name,
                    active_version: customDetail.active_version,
                    draft_version: customDetail.draft_version,
                    lock_version: customDetail.lock_version,
                  },
                ]
              : []),
          ],
          palette: strategyPalette,
        },
      })
      return
    }
    if (path.endsWith('/strategies/duplicate')) {
      customExists = true
      customDetail = strategyDetail(customStrategy)
      await route.fulfill({ json: customDetail })
      return
    }
    if (path.endsWith('/strategies/validate')) {
      await route.fulfill({
        json: strategyDetail(customStrategy).validation,
      })
      return
    }
    if (
      path.endsWith(`/strategies/${customStrategy.slug}`) &&
      request.method() === 'PUT'
    ) {
      saveAttempts += 1
      if (saveAttempts > 1) {
        await route.fulfill({
          status: 409,
          json: { error: 'Strategy changed in another editor.' },
        })
        return
      }
      const payload = request.postDataJSON() as {
        ir: ReturnType<typeof strategyDetail>['ir']
      }
      customDetail = {
        ...customDetail,
        name: payload.ir.name,
        description: payload.ir.description,
        active_version: 2,
        draft_version: 2,
        lock_version: 2,
        ir: payload.ir,
      }
      await route.fulfill({ json: customDetail })
      return
    }
    if (
      path.endsWith(`/strategies/${customStrategy.slug}`) &&
      request.method() === 'DELETE'
    ) {
      customExists = false
      await route.fulfill({ status: 204, body: '' })
      return
    }
    const slug = path.split('/').at(-1)
    await route.fulfill({
      json:
        slug === customStrategy.slug
          ? customDetail
          : strategyDetail(builtinStrategy),
    })
  })
})

test('lazy routes still render dashboard charts and configuration forms', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/statistic/profit-overall/timeline', route => route.fulfill({
    json: [
      { timestamp: '2026-07-24 00:00:00', profit_overall: 35, funds_locked: 100 },
      { timestamp: '2026-07-25 00:00:00', profit_overall: 42.5, funds_locked: 100 },
    ],
  }))
  await page.route('**/statistic/profit/*/*', route => route.fulfill({
    json: { '2026-07-24': 5, '2026-07-25': 7 },
  }))
  await page.route('**/trades/closed/length', route => route.fulfill({ json: { result: 0 } }))

  await page.goto('/')
  await expect(page.locator('.performance-chart canvas').first()).toBeVisible()
  await page.getByRole('button', { name: '1D', exact: true }).click()
  await expect(page.locator('.performance-chart canvas').first()).toBeVisible()

  await page.goto('/stats')
  await expect(page.getByRole('heading', { name: 'Statistics', exact: true })).toBeVisible()
  await expect(page.locator('.heatmap-container .n-heatmap')).toBeVisible()

  await page.goto('/control-center')
  await expect(page.getByRole('heading', { name: 'Configuration', exact: true })).toBeVisible()
  await expect(page.getByText('Dry run', { exact: true })).toBeVisible()
  await expect(page.locator('input').first()).toBeVisible()
  expect(errors).toEqual([])
})

test('renders the safe dry-run control center mission', async ({ page }) => {
  await page.goto('/control-center')

    // The configuration-first redesign no longer shows a "Safe dry-run setup is
    // ready" mission banner; a ready dry-run renders the setup-first workspace
    // with a persistent "Dry run" mode indicator in the top bar.
  await expect(
    page.getByRole('heading', { name: 'Configuration' }),
  ).toBeVisible()
  await expect(page.getByText('Dry run', { exact: true })).toBeVisible()
})

test('keeps the control center inside a 375px viewport', async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, 'mobile-only layout assertion')
  await page.goto('/control-center')

    // No "Safe dry-run setup is ready" heading exists anymore. Guard the layout
    // invariant directly: the document must not overflow a 375px phone width
    // (the regression class the desktop-nav hide guards against).
  const { clientWidth, scrollWidth } = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth)
})

test('opens and duplicates a strategy through the desktop builder workflow', async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, 'desktop and tablet graph workflow')
  await page.goto(
     '/control-center?mode=strategy-builder&target=strategy-builder',
     { waitUntil: 'domcontentloaded' },
   )

  await expect(
    page.getByRole('heading', { name: 'Strategy Builder' }),
  ).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Strategy graph' }),
  ).toContainText('Read-only built-in preview')

  await page.getByRole('button', { name: 'Duplicate selected' }).click()

  await expect(page.getByText('Custom copy created')).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Strategy graph' }),
  ).toContainText('Editable custom graph')
})

test('edits, validates, saves, detects conflicts, and deletes a custom strategy', async ({
  page,
  isMobile,
}, testInfo) => {
  test.skip(
    isMobile || testInfo.project.name !== 'chromium',
    'single desktop mutation workflow',
  )
  await page.goto(
     '/control-center?mode=strategy-builder&target=strategy-builder',
     { waitUntil: 'domcontentloaded' },
   )

  await page.getByRole('button', { name: /EMA cross copy/ }).click()
  await expect(
    page.getByRole('region', { name: 'Strategy graph' }),
  ).toContainText('Editable custom graph')

  await page.getByLabel('Strategy name').fill('EMA momentum')
  await page
    .getByLabel('Description')
    .fill('Validated momentum strategy')
  await page.getByRole('button', { name: 'Validate' }).click()
  await expect(page.getByText('valid', { exact: true })).toBeVisible()

  await page
    .getByRole('button', { name: 'Save active version' })
    .click()
  await expect(page.getByText('Saved active version v2.')).toBeVisible()
  await expect(
    page.getByRole('button', { name: /EMA momentum Custom · v2/ }),
  ).toBeVisible()

  await page.getByLabel('Strategy name').fill('Conflicting edit')
  await page.getByRole('button', { name: 'Validate' }).click()
  await page
    .getByRole('button', { name: 'Save active version' })
    .click()
  await expect(
    page.getByText(
      'This draft is stale. Reload the strategy before saving another active version.',
    ),
  ).toBeVisible()
  await expect(
    page.getByText('Strategy changed in another editor.'),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  const deleteDialog = page.getByRole('dialog')
  await expect(deleteDialog).toContainText(
    'Delete custom strategy "EMA momentum"?',
  )
  await deleteDialog
    .getByRole('button', { name: 'Delete', exact: true })
    .click()
  await expect(page.getByText('Custom strategy deleted.')).toBeVisible()
  await expect(
    page.getByRole('button', { name: /EMA momentum/ }),
  ).toHaveCount(0)
})

test('keeps mobile strategy review readable without exposing graph editing', async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, 'mobile-only strategy review assertion')
  await page.goto(
     '/control-center?mode=strategy-builder&target=strategy-builder',
     { waitUntil: 'domcontentloaded' },
   )

  const builder = page.getByLabel('Strategy library')
  await expect(builder).toBeVisible()
  await expect(
    page.getByText(
      'Graph editing is available on tablet and desktop. This screen keeps strategy review and selection readable on phones.',
    ),
  ).toBeVisible()
  await expect(page.getByLabel('Rete graph canvas')).toBeHidden()

  const box = await builder.boundingBox()
  expect(box).not.toBeNull()
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(375)
})

test('keeps statistics usable at mobile, tablet, and desktop widths', async ({
  page,
  isMobile,
}) => {
  await page.goto('/stats')

  await expect(page.getByText('Total Trades')).toBeVisible()
  await expect(page.getByText('12', { exact: true }).first()).toBeVisible()

  const viewport = page.viewportSize()
  expect(viewport).not.toBeNull()
  const documentWidth = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }))
  expect(documentWidth.scroll).toBeLessThanOrEqual(documentWidth.client + 1)

  const statisticsTabs = page.locator('.statistics-tabs')
  await expect(
    statisticsTabs.getByRole('columnheader', { name: 'Symbol' }),
  ).toBeVisible()
  if (isMobile) {
    await expect(
      statisticsTabs.getByRole('columnheader', { name: 'Avg Profit' }),
    ).toHaveCount(0)
    const paginationItem = statisticsTabs.locator('.n-pagination-item').first()
    await expect(paginationItem).toBeVisible()
    const paginationBox = await paginationItem.boundingBox()
    expect(paginationBox?.width ?? 0).toBeGreaterThanOrEqual(44)
    expect(paginationBox?.height ?? 0).toBeGreaterThanOrEqual(44)
  } else {
    await expect(
      statisticsTabs.getByRole('columnheader', { name: 'Avg Profit' }),
    ).toBeVisible()
  }

  const pageBox = await page.locator('.stats-page').boundingBox()
  expect(pageBox).not.toBeNull()
  expect((pageBox?.x ?? 0) + (pageBox?.width ?? 0)).toBeLessThanOrEqual(
    viewport?.width ?? 0,
  )
})

test('shows accumulation holdings and restarts changed activity', async ({ page, isMobile }) => {
  await page.route('**/config/all', route => route.fulfill({ json: { ...completeDryRunConfig, trade_mode: 'accumulation', dca: true, market: 'spot', accumulation_available: true, accumulation_strategy_version_id: 17 } }))
  await page.routeWebSocket('**/accumulation/performance/stream', socket => socket.send(JSON.stringify({ type: 'snapshot', activity_revision: 1, performance: {
    observed_at_ms: Date.now(), valid_until_ms: Date.now() + 10000, includes_csv_declarations: false,
    holdings: [{ symbol: 'BTC/USDC', quantity: '1', remaining_cost: '100', average_cost: '100', market_value: '110', unrealized: '10', complete: true, basis_provenance: 'exchange_fills' }],
    by_quote: [{ quote: 'USDC', contributed_quote: '100', remaining_cost: '100', market_value: '110', realized: '0', unrealized: '10', total_return: '10', complete: true, live_holding_count: 1, unknown_deal_count: 0 }],
  } })))
  let activityLoads = 0
  await page.route('**/accumulation/activity**', route => {
    if (route.request().url().includes('cursor=')) return route.fulfill({ status: 409, json: { error: 'Activity changed.' } })
    activityLoads++
    return route.fulfill({ json: { items: [{ kind: 'order', id: 1, updated_at: '2026-01-01T00:00:00Z', symbol: 'BTC/USDC', side: 'buy', quantity: '1', quote_cost: '100', price_per_coin: '100', fees_complete: true, terminal: true }], next_cursor: 'next' } })
  })
  await page.goto('/stats')
  await expect(page.getByText('Live mode: Accumulation')).toBeVisible()
  if (isMobile) {
    const summary = page.locator('.mobile-holdings summary').first()
    await expect(summary).toContainText('BTC/USDC')
    await expect(summary).toContainText('1.0000')
    await summary.click()
    await expect(page.locator('.mobile-holdings')).toContainText('Average cost per coin: 100.00')
  } else {
    await expect(page.getByRole('columnheader', { name: 'Average cost per coin' })).toBeVisible()
  }
  await expect(page.getByText('buy order summary')).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Price per coin' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '1.0000' }).last()).toBeVisible()
  const beforeReload = activityLoads
  await page.getByRole('button', { name: 'Load older activity' }).click()
  await expect.poll(() => activityLoads).toBeGreaterThan(beforeReload)
  await expect(page.getByText('buy order summary')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Restart history' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /View managed holdings and order history/ })).toHaveCount(0)
  const width = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
  expect(width.scroll).toBeLessThanOrEqual(width.client + 1)
})

test('two clients retain their selected history independently across refresh', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'two-client desktop workflow')
  const second = await page.context().newPage()
  const config = { ...completeDryRunConfig, trade_mode: 'accumulation', dca: true, market: 'spot', accumulation_available: true, accumulation_strategy_version_id: 17 }
  for (const client of [page, second]) {
    await client.route('**/config/all', route => route.fulfill({ json: config }))
    await client.route('**/analytics/overview**', route => route.fulfill({ json: analyticsOverview }))
    await client.route('**/accumulation/activity**', route => route.fulfill({ json: { items: [], next_cursor: null } }))
    await client.routeWebSocket('**/accumulation/performance/stream', socket => socket.send(JSON.stringify({ type: 'snapshot', activity_revision: 1, performance: {
      observed_at_ms: Date.now(), valid_until_ms: Date.now() + 10000, includes_csv_declarations: false, holdings: [], by_quote: [],
    } })))
    await client.goto('/stats')
    await expect(client.getByText('Live mode: Accumulation')).toBeVisible()
  }
  await page.getByRole('button', { name: 'Dynamic DCA history' }).click()
  await expect(page.getByText(/Viewing Dynamic DCA history/)).toBeVisible()
  await expect(second.getByRole('heading', { name: 'Accumulation', exact: true })).toBeVisible()
  await second.reload()
  await expect(second.getByRole('heading', { name: 'Accumulation', exact: true })).toBeVisible()
  await expect(page.getByText(/Viewing Dynamic DCA history/)).toBeVisible()
  await expect(page.getByText('Live mode: Accumulation')).toBeVisible()
  await second.close()
})

test('two clients preserve a draft when a stale configuration save conflicts', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'two-client desktop workflow')
  const second = await page.context().newPage()
  const config = { ...completeDryRunConfig }
  let saves = 0
  for (const client of [page, second]) {
    await client.route('**/config/all', route => route.fulfill({ json: config }))
    await client.route('**/config/freshness', route => route.fulfill({ json: { updated_at: config.config_updated_at, config_revision: 0 } }))
    await client.route('**/config/multiple', route => {
      if (route.request().headers()['x-moonwalker-config-revision'] !== String(config.config_revision)) {
        return route.fulfill({ status: 409, json: { message: 'Configuration changed since this form was loaded.' } })
      }
      config.config_revision += 1
      saves += 1
      return route.fulfill({ json: { message: 'Config updated', config_revision: config.config_revision } })
    })
    await client.goto('/control-center?mode=setup&target=dca')
    await expect(client.getByPlaceholder('BO', { exact: true })).toBeVisible()
  }
  await page.getByPlaceholder('BO', { exact: true }).fill('12')
  await second.getByPlaceholder('BO', { exact: true }).fill('15')
  await second.getByRole('button', { name: 'Save changes', exact: true }).first().click()
  await expect.poll(() => saves).toBe(1)
  await page.getByRole('button', { name: 'Save changes', exact: true }).first().click()
  await expect(page.getByPlaceholder('BO', { exact: true })).toHaveValue('12')
  await expect(page.getByText(/Configuration changed since this form was loaded/i).first()).toBeVisible()
  expect(saves).toBe(1)
  await second.close()
})

test('surfaces every typed sell failure from the mounted Open Trades UI', async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== 'chromium',
    'single desktop mutation workflow',
  )
  const failures = [
    ['rejected', 'Sell rejected by lifecycle policy.'],
    ['stale', 'Sell request used stale trade state.'],
    ['indeterminate', 'Exchange outcome is indeterminate.'],
    ['quarantined', 'Sell outcome was quarantined for review.'],
  ] as const
  let failureIndex = 0

  await page.route('**/orders/sell/btc-usdc', async (route) => {
    const [status, userMessage] = failures[failureIndex]
    failureIndex += 1
    await route.fulfill({
      json: {
        result: 'sell_failed',
        mutation: {
          operation_id: `sell-${status}`,
          symbol: 'BTC/USDC',
          action: 'sell',
          status,
          reason_code: `test_${status}`,
          user_message: userMessage,
          exchange_order_id: null,
          client_order_id: null,
          persisted_execution_id: null,
        },
      },
    })
  })

  await page.goto('/')
  await expect(
    page.getByRole('row', {
      name: 'Toggle trade details for BTC/USDC',
    }),
  ).toBeVisible()

  for (const [status, userMessage] of failures) {
    await page.getByRole('button', { name: 'Sell BTC/USDC' }).click()
    const sellDialog = page.getByRole('dialog')
    await expect(sellDialog).toContainText('Selling deal')
    await sellDialog
      .getByRole('button', { name: 'Sell', exact: true })
      .click()
    await expect(page.getByText(userMessage, { exact: false })).toBeVisible()
    if (status === 'indeterminate' || status === 'quarantined') {
      await expect(sellDialog).toBeVisible()
      await sellDialog.getByRole('button', { name: 'close' }).click()
    }
    await expect(sellDialog).toBeHidden()
  }
  expect(failureIndex).toBe(failures.length)
})

test('enables accumulation and edits shared indicators in the existing builder', async ({ page, isMobile }, testInfo) => {
  test.skip(isMobile, 'graph editing uses desktop and tablet')
  await page.goto('/control-center?mode=strategy-builder&target=strategy-builder')
  await page.getByRole('button', { name: 'Duplicate selected' }).click()
  await page.getByRole('checkbox', { name: 'Use with accumulation' }).check()
  await page.getByText('Accumulation execution settings', { exact: true }).click()
  await expect(page.getByText('Minimum dip (ATR)', { exact: true })).toBeVisible()
  await page.getByLabel('Minimum dip (ATR)').fill('2')
  const saved = page.waitForRequest(request => request.method() === 'PUT' && request.url().includes('/strategies/'))
  await page.getByRole('button', { name: 'Validate', exact: true }).click()
  await page.getByRole('button', { name: 'Save active version' }).click()
  const request = await saved
  expect(request.postDataJSON().ir.accumulation).toMatchObject({ entry_atr: '2', timeframe: '1h' })
  await expect(page.getByText('Saved active version v2.')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath(`moonwalker-shared-builder-${page.viewportSize()?.width}.png`), fullPage: true })
  await expect(page.getByRole('region', { name: 'Accumulation strategies', exact: true })).toHaveCount(0)
})
