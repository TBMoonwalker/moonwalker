import { expect, test } from '@playwright/test'

test('runs accumulation in the existing Backtest form, chart and results tabs', async ({ page }, testInfo) => {
  await page.route('**/config/all', route => route.fulfill({ json: {
    timezone: 'Europe/Vienna', signal: 'asap', symbol_list: 'BTC/USDC', exchange: 'binance', timeframe: '1h',
    key: 'fixture', secret: 'fixture', currency: 'USDC', max_bots: 2, bo: 10, tp: 1, capital_max_fund: 100,
    history_lookback_time: '180d', dca: false, dry_run: true, mstc: 4,
  } }))
  await page.route('**/strategies', route => route.fulfill({ json: { strategies: [{ slug: 'ema20_swing', name: 'EMA swing' }] } }))
  await page.route('**/data/exchange/symbols/USDC', route => route.fulfill({ json: { symbols: ['BTC/USDC'] } }))
  await page.route('**/accumulation/strategies*', route => route.fulfill({ json: { versions: [{ id: 17, name: 'Patient dip', version: 1, parameters: { timeframe: '4h' } }], next_after_id: null } }))
  let commands = 0
  await page.route('**/accumulation/commands', route => { commands++; return route.abort() })
  const requests: Record<string, unknown>[] = []
  const start = Date.UTC(2025, 0, 1)
  const candles = Array.from({ length: 10 }, (_, index) => ({ time: (start + index * 14400000) / 1000, open: 100 - index, high: 102 - index, low: 98 - index, close: 99 - index }))
  const fill = { signal_close_ms: start + 14400000, execution_open_ms: start + 14400000, quantity: '0.1234567890123456789', spent: '12.1', fee: '0.1', execution_price: '97.2' }
  await page.route('**/backtest/run', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: {
      trades: [], chart: { candles, markers: [{ time: fill.execution_open_ms / 1000, position: 'belowBar', color: '#2E7D5B', shape: 'arrow_up', text: 'Buy' }], indicators: [] },
      stats: { symbol: 'BTC/USDC', strategy: 'patient · v1', trade_mode: 'accumulation', timeframe: '4h', candles_fetched: 263, candles_evaluated: 10, warmup_candles: 253, still_open_at_end: true },
      accumulation: { funding: '1000', strategy_version_id: 17, gap_count: 0, trades_truncated: false, accumulation_trades: [fill],
        results: ['accumulation', 'buy_and_hold', 'fixed_interval_dca'].map(strategy => ({ strategy, contributed_quote: '1000', units: '0.1234567890123456789', spent_quote_including_fees: '12.1', fees_quote: '0.1', cash_quote: '987.9', ending_value_quote: '1020', maximum_drawdown_fraction: '0.05', buy_count: 1 })),
        caveats: ['Historical symbol selection can introduce survivorship bias. This simulation does not predict returns.'] },
    } })
  })
  await page.goto('/backtest')
  await page.getByLabel('Backtest trade mode', { exact: true }).click()
  await page.locator('.n-base-select-option').filter({ hasText: 'Accumulation' }).click()
  await expect(page.getByLabel('Backtest accumulation strategy', { exact: true })).toBeVisible()
  await expect(page.getByText('Patient dip · v1 · 4h', { exact: true })).toBeVisible()
  await expect(page.getByText('Take profit %', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Base order', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Completed OHLC candles', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  await expect(page.locator('[aria-label="Backtest stats"]').getByText('Coins accumulated', { exact: true })).toBeVisible()
  await expect(page.locator('[data-backtest-chart-ready="true"]')).toBeVisible()
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ symbol: 'BTC/USDC', trade_mode: 'accumulation', strategy_version_id: 17, timeframe: '4h', funding: '1000', fee: 0.001, slippage_bps: '20', fixed_interval_candles: 24 })
  expect(requests[0]).not.toHaveProperty('take_profit_pct')
  expect(requests[0]).not.toHaveProperty('candles')
  await expect(page.getByRole('columnheader', { name: 'Bought', exact: true })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Exit', exact: true })).toHaveCount(0)
  await page.locator('.n-tabs-tab').filter({ hasText: /^Comparison$/ }).click()
  await expect(page.getByRole('cell', { name: 'buy and hold', exact: true })).toBeVisible()
  await page.locator('.n-tabs-tab').filter({ hasText: /^Run$/ }).click()
  await expect(page.getByText('patient · v1', { exact: true })).toBeVisible()
  expect(commands).toBe(0)
  expect(await page.locator('.backtest-page').evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ animations: 'disabled', path: `/private/tmp/backtest-accumulation-${testInfo.project.name}.png`, fullPage: true })
})
