import { expect, test, type WebSocketRoute } from '@playwright/test'
import type { AccumulationDetail } from '../src/types/accumulation'

test('puts entry state and its reviewed next action before secondary information', async ({ page }, testInfo) => {
  let live: WebSocketRoute | undefined
  await page.routeWebSocket('**/accumulation/stream**', socket => { live = socket })
  await page.routeWebSocket('**/trades/*', socket => socket.send('[]'))
  await page.routeWebSocket('**/statistic/profit', socket => socket.send('{}'))
  await page.route('**/trades/*/length', route => route.fulfill({ json: { result: 0 } }))
  await page.clock.install()
  await page.route('**/config/all', route => route.fulfill({ json: {
    timezone: 'Europe/Vienna', signal: 'asap', symbol_list: 'BTC/USDC', exchange: 'binance',
    timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
    bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d', dca: false, dry_run: true, mstc: 4,
  } }))
  const entry = { operation_id: 'entry', action: 'activate', status: 'pending', result_state: 'validating', result_revision: 1, reason: 'validation_required', source: 'asap' as const, declaration_invalid: false, declaration: null }
  const detail: AccumulationDetail = {
    activation_id: 'outlook', symbol: 'BTC/USDC', state: 'validating', explicitly_paused: true,
    revision: 1, reason: 'validation_required', runtime_wait_reason: 'WAIT_ENTRY_VALIDATION', observations_initialized: false,
    strategy_version_id: 7, strategy_slug: 'accumulation_variant_dip_atr', strategy_version: 1,
    holding_integrity: 'unlinked', holding: null, entry, operations: [entry], older_operations_available: false,
  }
  let commands = 0
  await page.route('**/accumulation/**', route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'POST') commands++
    return route.fulfill({ json: path.endsWith('/strategies') ? { versions: [{ id: 7, name: 'Accumulation dip (ATR)', version: 1, parameters: { timeframe: '1h' } }], next_after_id: null }
      : path.endsWith('/activations') ? { activations: [detail], next_after: null, portfolio: { holding_count: 0, unverified_holding_count: 0, by_quote: [] } } : detail })
  })
  await page.goto('/?symbol=BTC%2FUSDC')
  const panel = page.getByRole('region', { name: 'BTC/USDC trade information', exact: true })
  await expect(panel.getByRole('heading', { name: 'Entry check incomplete' })).toBeVisible()
  await expect(panel.getByRole('list', { name: 'How accumulation works' })).toHaveCount(0)
  await expect(panel.getByText(/ASAP registers the symbol/)).toHaveCount(0)
  await expect(panel.getByText('Buy sizing', { exact: true })).toHaveCount(0)
  await expect(panel.getByText('Exit', { exact: true })).toHaveCount(0)
  await expect(panel.getByText('Buying rules', { exact: true })).toHaveCount(0)
  await expect(panel.getByText('Entry check details', { exact: true })).toHaveCount(0)
  await expect(panel.locator('.accumulation-management')).toHaveCount(0)
  const action = panel.getByRole('button', { name: 'Retry entry check', exact: true })
  await expect(action).toBeEnabled()
  expect(await panel.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  if (testInfo.project.name === 'mobile-chromium') expect((await action.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  await panel.screenshot({ path: testInfo.outputPath(`accumulation-outlook-${testInfo.project.name}.png`) })
  // Preparing an action still requires the existing confirmation; reading never trades.
  await action.click()
  await expect(panel.getByRole('button', { name: 'Confirm retry entry check', exact: true })).toBeVisible()
  expect(commands).toBe(0)
  await panel.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect.poll(() => !!live).toBe(true)
  const waiting: AccumulationDetail = { ...detail, state: 'enabled', explicitly_paused: false, revision: 2, observations_initialized: true, entry: null, operations: [], runtime_wait_reason: 'WAIT_DEPTH', wait_condition: {
    reason: 'WAIT_DEPTH', timeframe: '1h', observed_close_ms: Date.now(), next_close_ms: Date.now() + 3600000,
    observed_price: '100', levels: [{ kind: 'depth', direction: 'at_or_below', target_price: '98', change_percent: '-2' }],
  } }
  let reads = 0
  page.on('request', request => { if (new URL(request.url()).pathname === '/accumulation/activation') reads++ })
  live!.send(JSON.stringify({ type: 'snapshot', page: { activations: [waiting], next_after: null }, detail: waiting }))
  await expect(panel.getByRole('heading', { name: 'Waiting for entry', exact: true })).toBeVisible()
  await expect(panel.getByText('≈ 2.00% fall', { exact: true })).toBeVisible()
  await expect(panel.getByLabel('Accumulation strategy version', { exact: true })).not.toBeVisible()
  waiting.runtime_wait_reason = 'WAIT_REARM'
  waiting.wait_condition!.reason = 'WAIT_REARM'
  waiting.wait_condition!.levels = [
    { kind: 'further_decline', direction: 'at_or_below', target_price: '99', change_percent: '-1' },
    { kind: 'recovery_then_correction', direction: 'at_or_above', target_price: '101', change_percent: '1' },
  ]
  live!.send(JSON.stringify({ type: 'snapshot', page: { activations: [waiting], next_after: null }, detail: waiting }))
  await expect(panel.getByRole('heading', { name: 'Recovery needed before another dip buy' })).toBeVisible()
  await expect(panel.getByRole('list', { name: 'Current buy conditions' })).not.toContainText('rise')
  await expect(panel.getByText('No buy on this rise. A fresh correction must follow.', { exact: true })).toBeVisible()
  waiting.runtime_wait_reason = 'WAIT_BASELINE'
  waiting.wait_condition!.reason = 'WAIT_BASELINE'
  waiting.wait_condition!.levels = []
  live!.send(JSON.stringify({ type: 'snapshot', page: { activations: [waiting], next_after: null }, detail: waiting }))
  await expect(panel.getByRole('heading', { name: 'Waiting for the next 1h close', exact: true })).toBeVisible()
  await expect(panel.getByText('No price target yet. Waiting for the next completed candle to evaluate a new buy signal; a buy is not guaranteed.', { exact: true })).toBeVisible()
  await expect(panel.getByText(/^Next close:.*UTC$/)).toBeVisible()
  await expect(panel.getByRole('list', { name: 'Current buy conditions' })).toHaveCount(0)
  await page.clock.fastForward(15000)
  expect(reads).toBe(0)
  await page.getByRole('button', { name: 'Dark theme', exact: true }).click()
  await panel.screenshot({ path: testInfo.outputPath(`accumulation-outlook-dark-${testInfo.project.name}.png`) })
  await page.getByRole('button', { name: 'Light theme', exact: true }).click()
})
