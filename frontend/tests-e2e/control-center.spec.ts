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

function strategyDetail(strategy: typeof builtinStrategy) {
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
      json: { updated_at: completeDryRunConfig.config_updated_at },
    })
  })
  await page.route('**/analytics/overview', async (route) => {
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

test('renders the safe dry-run control center mission', async ({ page }) => {
  await page.goto('/control-center')

  await expect(
    page.getByRole('heading', { name: 'Safe dry-run setup is ready' }),
  ).toBeVisible()
  await expect(
    page.getByText('Moonwalker is configured for safe dry-run operation.'),
  ).toBeVisible()
})

test('keeps the mission heading inside a 375px viewport', async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, 'mobile-only layout assertion')
  await page.goto('/control-center')

  const heading = page.getByRole('heading', {
    name: 'Safe dry-run setup is ready',
  })
  await expect(heading).toBeVisible()
  const box = await heading.boundingBox()

  expect(box).not.toBeNull()
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(375)
})

test('opens and duplicates a strategy through the desktop builder workflow', async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, 'desktop and tablet graph workflow')
  await page.goto(
    '/control-center?mode=strategy-builder&target=strategy-builder',
  )

  await expect(
    page.getByRole('heading', { name: 'Strategy Builder' }),
  ).toBeVisible()
  await expect(
    page.getByRole('main', { name: 'Strategy graph' }),
  ).toContainText('Read-only built-in preview')

  await page.getByRole('button', { name: 'Duplicate selected' }).click()

  await expect(page.getByText('Custom copy created')).toBeVisible()
  await expect(
    page.getByRole('main', { name: 'Strategy graph' }),
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
  )

  await page.getByRole('button', { name: /EMA cross copy/ }).click()
  await expect(
    page.getByRole('main', { name: 'Strategy graph' }),
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

  for (const [, userMessage] of failures) {
    await page.getByRole('button', { name: 'Sell BTC/USDC' }).click()
    const sellDialog = page.getByRole('dialog')
    await expect(sellDialog).toContainText('Selling deal')
    await sellDialog
      .getByRole('button', { name: 'Sell', exact: true })
      .click()
    await expect(page.getByText(userMessage, { exact: true })).toBeVisible()
    await expect(sellDialog).toBeHidden()
  }
  expect(failureIndex).toBe(failures.length)
})
