import { expect, test } from '@playwright/test'

const candleStart = Date.UTC(2026, 6, 1, 0, 0, 0)
const candleIntervalMs = 60 * 60 * 1000
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
  config_updated_at: '2026-08-02T12:00:00Z',
}
const candles = Array.from({ length: 40 }, (_, index) => {
  const wave = Math.sin(index / 4) * 2
  const open = 100 + wave
  const close = open + (index % 2 === 0 ? 0.8 : -0.6)
  return {
    time: candleStart + index * candleIntervalMs,
    open,
    high: Math.max(open, close) + 1,
    low: Math.min(open, close) - 1,
    close,
    volume: 1000 + index * 10,
  }
})

const backtestResult = {
  trades: [],
  chart: {
    candles,
    markers: [
      {
        time: candles[0].time,
        position: 'aboveBar',
        color: '#2E7D5B',
        shape: 'arrow_up',
        text: 'take_profit',
      },
      {
        time: candles[candles.length - 1].time,
        position: 'belowBar',
        color: '#B4443F',
        shape: 'arrow_down',
        text: 'SIDESTEP',
      },
    ],
    indicators: [],
  },
  stats: {
    summary: {
      total_trades: 0,
      win_rate: 0,
      total_profit: 0,
      avg_profit: 0,
      avg_profit_percent: 0,
      total_cost: 0,
    },
    drawdown: {
      max_drawdown: 0,
      max_drawdown_percent: 0,
    },
    candles_fetched: candles.length,
    candles_evaluated: candles.length,
    warmup_candles: 0,
    timeframe: '1h',
    symbol: 'BTC/USDC',
    strategy: 'ema20_swing',
    trade_mode: 'dynamic_dca',
    still_open_at_end: false,
  },
}

test('keeps first and last Backtest markers visible on mobile', async (
  { page },
  testInfo,
) => {
  test.skip(testInfo.project.name !== 'mobile-chromium')

  await page.route('**/strategies', async (route) => {
    await route.fulfill({
      json: {
        strategies: [{ slug: 'ema20_swing', name: 'EMA 20 swing' }],
      },
    })
  })
  await page.route('**/config/all', async (route) => {
    await route.fulfill({ json: completeDryRunConfig })
  })
  await page.route('**/data/exchange/symbols/USDC', async (route) => {
    await route.fulfill({ json: { symbols: ['BTC/USDC'] } })
  })
  await page.route('**/backtest/run', async (route) => {
    await route.fulfill({ json: backtestResult })
  })

  await page.goto('/backtest')
  const runButton = page.getByRole('button', { name: 'Run', exact: true })
  await expect(runButton).toBeEnabled()
  await runButton.click()

  const chart = page.locator('[data-backtest-chart-ready="true"]')
  await expect(chart).toBeVisible()
  await page.evaluate(async () => {
    await document.fonts.ready
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
    })
  })

  await chart.scrollIntoViewIfNeeded()
  const box = await chart.boundingBox()
  expect(box).not.toBeNull()
  if (!box) {
    return
  }
  const edgeWidth = Math.min(140, Math.floor(box.width / 2))
  const screenshotOptions = {
    animations: 'disabled' as const,
    maxDiffPixels: 20,
  }

  await expect(page).toHaveScreenshot('backtest-left-edge.png', {
    ...screenshotOptions,
    clip: {
      x: box.x,
      y: box.y,
      width: edgeWidth,
      height: box.height,
    },
  })
  await expect(page).toHaveScreenshot('backtest-right-edge.png', {
    ...screenshotOptions,
    clip: {
      x: box.x + box.width - edgeWidth,
      y: box.y,
      width: edgeWidth,
      height: box.height,
    },
  })

  const pageWidth = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(pageWidth.scrollWidth).toBeLessThanOrEqual(pageWidth.clientWidth)
})
