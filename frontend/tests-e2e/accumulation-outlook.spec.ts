import { expect, test } from '@playwright/test'
import type { AccumulationDetail } from '../src/types/accumulation'

test('puts entry state and its reviewed next action before secondary information', async ({ page }, testInfo) => {
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
  await page.goto('/')
  const panel = page.getByRole('region', { name: 'Accumulation', exact: true })
  await expect(panel.getByRole('heading', { name: 'Entry check incomplete' })).toBeVisible()
  await expect(panel.getByRole('list', { name: 'How accumulation works' })).toHaveCount(0)
  await expect(panel.getByText(/ASAP registers the symbol/)).toHaveCount(0)
  await expect(panel.getByText('Buy sizing', { exact: true })).toHaveCount(0)
  await expect(panel.getByText('Exit', { exact: true })).toHaveCount(0)
  await expect(panel.getByText('Buying rules', { exact: true })).toHaveCount(0)
  await panel.getByText('Entry check details', { exact: true }).click()
  await expect(panel.getByText(/The first check runs automatically/)).toBeVisible()
  await panel.getByText('Entry check details', { exact: true }).click()
  const action = panel.getByRole('button', { name: 'Retry entry check', exact: true })
  await expect(action).toBeEnabled()
  await expect(action).toHaveClass(/n-button--primary-type/)
  expect(await panel.locator('.accumulation-outlook').evaluate(element => {
    const details = document.querySelector('.accumulation-history')!
    return !!(element.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING)
  })).toBe(true)
  expect(await panel.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  if (testInfo.project.name === 'mobile-chromium') expect((await action.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  await panel.screenshot({ path: `/private/tmp/accumulation-outlook-${testInfo.project.name}.png` })
  // Preparing an action still requires the existing confirmation; reading never trades.
  await action.click()
  await expect(panel.getByRole('button', { name: 'Confirm retry entry check', exact: true })).toBeVisible()
  expect(commands).toBe(0)
  await panel.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.getByRole('button', { name: 'Dark theme', exact: true }).click()
  await panel.screenshot({ path: `/private/tmp/accumulation-outlook-dark-${testInfo.project.name}.png` })
  await page.getByRole('button', { name: 'Light theme', exact: true }).click()
})
