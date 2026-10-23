import { expect, test } from '@playwright/test'
import type { AccumulationDetail } from '../src/types/accumulation'

test.beforeEach(async ({ page }) => {
  await page.routeWebSocket('**/accumulation/stream**', () => {})
  await page.routeWebSocket('**/trades/*', socket => socket.send('[]'))
  await page.routeWebSocket('**/statistic/profit', socket => socket.send('{}'))
  await page.route('**/trades/*/length', route => route.fulfill({ json: { result: 0 } }))
})

test('reviews an exact inventory declaration without adding it to order history', async ({ page }, testInfo) => {
  await page.route('**/config/all', route => route.fulfill({ json: {
    timezone: 'Europe/Vienna', signal: 'csv_signal', signal_settings: JSON.stringify({ csv_source: 'signals.csv' }), exchange: 'binance',
    timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
    bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d', dca: false, dry_run: true, mstc: 4,
  } }))
  const detail: AccumulationDetail = {
    activation_id: 'correction', symbol: 'BTC/USDC', state: 'paused', explicitly_paused: true, account_matches: true,
    revision: 20, reason: null, runtime_wait_reason: null, observations_initialized: true,
    strategy_version_id: 5, strategy_slug: 'Patient dip', strategy_version: 1,
    holding_integrity: 'owned', holding: { net_quantity: '0.100000000000000001', remaining_cost: '12.000000000000000001', contributed_quote: '12.000000000000000001', disposal_proceeds: '0', basis_provenance: 'csv_declared', execution_history_complete: false, fees: { totals: {}, pending_reports: 0 } },
    entry: null, operations: [], older_operations_available: false,
  }
  const requests: Record<string, unknown>[] = []
  await page.route('**/accumulation/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/performance')) return route.fulfill({ json: { complete: false, observed_at_ms: 1000, basis: 'fresh_bid_before_future_sale_fees', reason: null, by_quote: [{ quote: 'USDC', complete: false, unknown_deal_count: 1, live_holding_count: 1, market_value: '15.000000000000000009', realized: null, unrealized: null, total_return: null }] } })
    if (route.request().method() === 'POST') {
      expect(path).toBe('/accumulation/repair')
      const command = route.request().postDataJSON()
      requests.push(command)
      detail.revision = 21
      detail.holding!.net_quantity = '0.100000000000000002'
      detail.holding!.remaining_cost = '12.000000000000000010'
      detail.holding!.basis_provenance = 'operator_adjusted'
      detail.operations = [{ operation_id: command.operation_id, action: 'adjust_inventory', status: 'applied', result_state: 'paused', result_revision: 21, reason: 'inventory_adjusted_paused', adjustment: {
        direction: 'add', quantity: command.quantity, note: command.note, before_quantity: '0.100000000000000001', after_quantity: '0.100000000000000002', before_cost: '12.000000000000000001', after_cost: '12.000000000000000010',
      } }]
      return route.fulfill({ json: { operation: { operation_id: command.operation_id, activation_id: detail.activation_id, status: 'applied', state: 'paused', revision: 21, reason: null } } })
    }
    return route.fulfill({ json: path.endsWith('/strategies') ? { versions: [], next_after_id: null } : path.endsWith('/activations') ? { activations: [detail], next_after: null } : detail })
  })
  await page.goto('/?symbol=BTC%2FUSDC')
  const panel = page.getByRole('region', { name: 'BTC/USDC trade information', exact: true })
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
  await panel.getByText('Inventory correction', { exact: true }).click()
  await panel.getByLabel('Correction quantity · BTC', { exact: true }).fill('0.000000000000000001')
  await panel.getByLabel('Acquisition cost of added coins · USDC', { exact: true }).fill('0.000000000000000009')
  await panel.getByLabel('Correction reason', { exact: true }).fill('Correct imported net coins')
  await panel.getByRole('button', { name: 'Correct managed inventory', exact: true }).click()
  expect(requests).toHaveLength(0)
  await expect(panel.getByText(/this correction is not an exchange fill/)).toBeVisible()
  await panel.getByRole('button', { name: 'Confirm correct managed inventory', exact: true }).click()
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ action: 'adjust_inventory', direction: 'add', quantity: '0.000000000000000001', acquisition_cost: '0.000000000000000009', note: 'Correct imported net coins', expected_revision: 20 })
  await expect(panel.getByRole('button', { name: 'Resume accumulation', exact: true })).toBeEnabled()
  expect(await panel.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  await panel.screenshot({ path: `/private/tmp/moonwalker-accumulation-adjustment-${testInfo.project.name}.png` })
})

test('reviews rotated credentials and keeps the holding paused after proof retry', async ({ page }, testInfo) => {
  await page.route('**/config/all', route => route.fulfill({ json: {
    timezone: 'Europe/Vienna', signal: 'csv_signal', signal_settings: JSON.stringify({ csv_source: 'signals.csv' }), exchange: 'binance',
    timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
    bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d', dca: false, dry_run: true, mstc: 4,
  } }))
  const detail: AccumulationDetail = {
    activation_id: 'rotation', symbol: 'BTC/USDC', state: 'enabled', explicitly_paused: false, account_matches: false,
    revision: 20, reason: null, runtime_wait_reason: null, observations_initialized: true,
    strategy_version_id: 5, strategy_slug: 'Patient dip', strategy_version: 1,
    holding_integrity: 'owned', holding: { net_quantity: '0.100000000000000001', remaining_cost: '12.000000000000000001', contributed_quote: '12.000000000000000001', disposal_proceeds: '0', basis_provenance: 'exchange_fills', execution_history_complete: true, fees: { totals: {}, pending_reports: 0 } },
    entry: null, operations: [], older_operations_available: false,
  }
  const requests: Record<string, unknown>[] = []
  await page.route('**/accumulation/**', route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'POST') {
      expect(path).toBe('/accumulation/repair')
      const command = route.request().postDataJSON()
      requests.push(command)
      detail.state = 'paused'; detail.explicitly_paused = true; detail.revision = 21
      const status = requests.length === 1 ? 'quarantined' : 'applied'
      if (status === 'applied') detail.account_matches = true
      return route.fulfill({ json: { operation: { operation_id: command.operation_id, activation_id: detail.activation_id, status, state: 'paused', revision: 21, reason: null } } })
    }
    return route.fulfill({ json: path.endsWith('/strategies') ? { versions: [], next_after_id: null } : path.endsWith('/activations') ? { activations: [detail], next_after: null } : detail })
  })
  await page.goto('/?symbol=BTC%2FUSDC')
  const panel = page.getByRole('region', { name: 'BTC/USDC trade information', exact: true })
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
  await panel.getByRole('button', { name: 'Revalidate rotated API key', exact: true }).click()
  expect(requests).toHaveLength(0)
  await expect(panel.getByText(/This does not transfer coins/)).toBeVisible()
  await panel.getByRole('button', { name: 'Confirm revalidate rotated api key', exact: true }).click()
  await expect(panel.getByText(/Account ownership evidence is incomplete/)).toBeVisible()
  await page.reload()
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
  await panel.getByRole('button', { name: 'Retry same request', exact: true }).click()
  await expect(panel.getByText(/Recorded outcome: applied/)).toBeVisible()
  expect(requests).toHaveLength(2)
  expect(requests[1]).toEqual(requests[0])
  expect(Object.keys(requests[0]).sort()).toEqual(['action', 'expected_revision', 'operation_id', 'symbol'])
  await expect(panel.getByRole('button', { name: 'Resume accumulation', exact: true })).toBeEnabled()
  expect(await panel.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  await panel.screenshot({ path: `/private/tmp/moonwalker-accumulation-account-rebind-${testInfo.project.name}.png` })
})

test('retires an unsent close while preserving Closing and requiring a separate sale request', async ({ page }, testInfo) => {
  await page.route('**/config/all', route => route.fulfill({ json: {
    timezone: 'Europe/Vienna', signal: 'csv_signal', signal_settings: JSON.stringify({ csv_source: 'signals.csv' }), exchange: 'binance',
    timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
    bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d', dca: false, dry_run: true, mstc: 4,
  } }))
  const previous = { operation_id: 'unsent-close', action: 'close', status: 'quarantined', result_state: 'closing', result_revision: 19, reason: 'restore_validation_required' }
  const detail: AccumulationDetail = {
    activation_id: 'retirement', symbol: 'BTC/USDC', state: 'closing', explicitly_paused: true,
    revision: 20, reason: 'restore_validation_required', runtime_wait_reason: null, observations_initialized: true,
    strategy_version_id: 5, strategy_slug: 'Patient dip', strategy_version: 1,
    holding_integrity: 'owned', holding: { net_quantity: '0.100000000000000001', remaining_cost: null, contributed_quote: null, disposal_proceeds: '0', basis_provenance: 'unknown', execution_history_complete: false, fees: null },
    entry: null, operations: [], older_operations_available: false,
    quarantined_commands: [previous], quarantined_orders: [],
  }
  const requests: Array<{ path: string; payload: Record<string, unknown> }> = []
  await page.route('**/accumulation/**', route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON()
      requests.push({ path, payload })
      detail.revision += 1
      detail.quarantined_commands = []
      detail.close_predecessor = { ...previous, status: 'cancelled', reason: 'restore_intent_retired', result_revision: detail.revision }
      return route.fulfill({ json: { operation: { operation_id: payload.operation_id, activation_id: detail.activation_id, status: payload.action === 'retire_command' ? 'applied' : 'pending', state: 'closing', revision: detail.revision, reason: null } } })
    }
    return route.fulfill({ json: path.endsWith('/strategies') ? { versions: [], next_after_id: null } : path.endsWith('/activations') ? { activations: [detail], next_after: null } : detail })
  })
  await page.goto('/?symbol=BTC%2FUSDC')
  const panel = page.getByRole('region', { name: 'BTC/USDC trade information', exact: true })
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
  await panel.getByRole('button', { name: 'Retire interrupted command', exact: true }).click()
  expect(requests).toHaveLength(0)
  await expect(panel.getByText(/Coins, cost basis, strategy binding and purchase guards stay unchanged/)).toBeVisible()
  await panel.getByRole('button', { name: 'Confirm retire interrupted command', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Retry remaining sale', exact: true })).toBeEnabled()
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ path: '/accumulation/repair', payload: { action: 'retire_command', previous_operation_id: 'unsent-close', expected_revision: 20 } })
  await expect(panel.getByRole('button', { name: 'Resume accumulation', exact: true })).toHaveCount(0)
  expect(await panel.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  await panel.screenshot({ path: `/private/tmp/moonwalker-accumulation-retirement-${testInfo.project.name}.png` })
  await panel.getByRole('button', { name: 'Retry remaining sale', exact: true }).click()
  expect(requests).toHaveLength(1)
  await panel.getByRole('button', { name: 'Confirm retry remaining sale', exact: true }).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests[1]).toMatchObject({ path: '/accumulation/commands', payload: { action: 'retry_close', previous_operation_id: 'unsent-close', expected_revision: 21 } })
  expect(requests[1].payload.operation_id).not.toBe(requests[0].payload.operation_id)
})

test('reviews a restored order and retries the same evidence lookup after reload', async ({ page }, testInfo) => {
  await page.route('**/config/all', route => route.fulfill({ json: {
    timezone: 'Europe/Vienna', signal: 'csv_signal', signal_settings: JSON.stringify({ csv_source: 'signals.csv' }), exchange: 'binance',
    timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
    bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d', dca: false, dry_run: true, mstc: 4,
  } }))
  const requests: Record<string, unknown>[] = []
  const detail: AccumulationDetail = {
    activation_id: 'restored', symbol: 'BTC/USDC', state: 'paused', explicitly_paused: true,
    revision: 20, reason: 'restore_validation_required', runtime_wait_reason: 'WAIT_REPAIR', observations_initialized: true,
    strategy_version_id: 5, strategy_slug: 'Patient dip', strategy_version: 1,
    holding_integrity: 'unlinked', holding: null, entry: null, operations: [], older_operations_available: false,
    quarantined_orders: [{ placement_operation_id: 'restored-buy', side: 'buy', has_lookup_identity: true }],
  }
  await page.route('**/accumulation/**', route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'POST') {
      requests.push(route.request().postDataJSON())
      detail.revision = 21
      const status = requests.length === 1 ? 'quarantined' : 'applied'
      if (status === 'applied') detail.quarantined_orders = []
      return route.fulfill({ json: { operation: { operation_id: requests[0].operation_id, activation_id: detail.activation_id, status, state: 'paused', revision: 21, reason: 'terminal_evidence_required' } } })
    }
    return route.fulfill({ json: path.endsWith('/strategies') ? { versions: [], next_after_id: null } : path.endsWith('/activations') ? { activations: [detail], next_after: null } : detail })
  })
  await page.goto('/?symbol=BTC%2FUSDC')
  const panel = page.getByRole('region', { name: 'BTC/USDC trade information', exact: true })
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Resume accumulation', exact: true })).toHaveCount(0)
  await panel.getByRole('button', { name: 'Reconcile restored order', exact: true }).click()
  expect(requests).toHaveLength(0)
  await expect(panel.getByText(/This cannot submit or cancel an order/)).toBeVisible()
  await panel.getByRole('button', { name: 'Confirm reconcile restored order', exact: true }).click()
  await expect(panel.getByText(/Terminal order evidence is not available/)).toBeVisible()
  await page.reload()
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
  await panel.getByRole('button', { name: 'Retry same request', exact: true }).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests[1]).toEqual(requests[0])
  expect(requests[0]).toMatchObject({ action: 'repair_order', placement_operation_id: 'restored-buy', expected_revision: 20 })
  await expect(panel.getByText(/Recorded outcome: applied/)).toBeVisible()
  expect(await panel.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  await panel.screenshot({ path: `/private/tmp/moonwalker-accumulation-repair-${testInfo.project.name}.png` })
})

test('keeps retained order history without duplicate accumulation portfolio sections', async ({ page }, testInfo) => {
  await page.route('**/config/all', route => route.fulfill({ json: {
    timezone: 'Europe/Vienna', signal: 'csv_signal', signal_settings: JSON.stringify({ csv_source: 'signals.csv' }), exchange: 'binance',
    timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
    bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d', dca: false, dry_run: true, mstc: 4,
  } }))
  const detail: AccumulationDetail = {
    activation_id: 'closed', symbol: 'BTC/USDC', state: 'stopped', explicitly_paused: true,
    revision: 20, reason: null, runtime_wait_reason: null, observations_initialized: true,
    strategy_version_id: 5, strategy_slug: 'Patient dip', strategy_version: 1,
    holding_integrity: 'unlinked', holding: null, entry: null, operations: [], older_operations_available: false,
    portfolio: { holding_count: 2, unverified_holding_count: 0, valuation_available: false, by_quote: [{ quote: 'USDC', holding_count: 2, known_remaining_cost: '0.300000000000000003', remaining_cost: null, unknown_cost_count: 1 }] },
    orders: [{ checkpoint_id: 5, deal_id: 'closed-deal', side: 'sell', filled_quantity: '0.100000000000000001', quote_cost: '12.000000000000000001', fees: { BNB: '0.000000000000000001' }, fees_complete: true, terminal: true, updated_at: '2026-10-21T10:00:00Z', inventory_at_update: { net_quantity: '0', remaining_cost: null, contributed_quote: null, disposal_proceeds: '12.000000000000000001', fees: {}, pending_fee_reports: 0, basis_provenance: 'unknown' } }],
    older_orders_available: false,
  }
  await page.route('**/accumulation/**', route => {
    const path = new URL(route.request().url()).pathname
    return route.fulfill({ json: path.endsWith('/strategies') ? { versions: [], next_after_id: null }
      : path.endsWith('/activations') ? { activations: [detail], next_after: null, portfolio: detail.portfolio } : detail })
  })
  await page.goto('/?symbol=BTC%2FUSDC')
  const panel = page.getByRole('region', { name: 'BTC/USDC trade information', exact: true })
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Portfolio exposure', exact: true })).toBeVisible()
  await expect(page.getByLabel('Accumulation portfolio accounting')).toHaveCount(0)
  await expect(page.getByText('All accumulation holdings', { exact: false })).toHaveCount(0)
  await expect(page.getByText('Accumulation value and returns', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Refresh valuation', exact: true })).toHaveCount(0)
  await expect(panel.getByText('No managed inventory.', { exact: true })).toBeVisible()
  await expect(page.getByText('Order size: 12.000000000000000001 | Amount: 0.100000000000000001 | Price: Unknown', { exact: true })).toBeVisible()
  expect(await panel.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  await panel.screenshot({ path: `/private/tmp/moonwalker-accumulation-history-${testInfo.project.name}.png` })
})

test('reviews manual sales and retains an uncertain request across reload', async ({ page }, testInfo) => {
  const detail: AccumulationDetail = {
    activation_id: 'simulated-activation', symbol: 'BTC/USDC', state: 'enabled',
    explicitly_paused: false, revision: 12, reason: null, runtime_wait_reason: null,
    observations_initialized: true, strategy_version_id: 5, strategy_slug: 'accumulation_dip_v1', strategy_version: 2,
    holding_integrity: 'owned', holding: {
      net_quantity: '0.100000000000000001', remaining_cost: null,
      contributed_quote: '12.000000000000000001', disposal_proceeds: '0',
      basis_provenance: 'unknown', execution_history_complete: false, fees: null,
    }, entry: null, operations: [], older_operations_available: false,
  }
  const requests: Record<string, unknown>[] = []
  await page.route('**/config/all', route => route.fulfill({ json: {
    timezone: 'Europe/Vienna', signal: 'csv_signal', signal_settings: JSON.stringify({ csv_source: 'signals.csv' }), exchange: 'binance',
    timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
    bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d',
    dca: false, dry_run: true, mstc: 4, trading_paused: false,
  } }))
  await page.route('**/accumulation/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/strategies')) return route.fulfill({ json: { versions: [], next_after_id: null } })
    if (route.request().method() === 'POST') {
      requests.push(route.request().postDataJSON())
      detail.state = 'closing'
      detail.revision = 13
      detail.runtime_wait_reason = 'WAIT_MINIMUM'
      detail.holding!.net_quantity = '0.000000000000000001'
      detail.operations = [{ operation_id: String(requests[0].operation_id), action: 'close', status: 'pending', result_state: 'closing', result_revision: 13, reason: null }]
      if (requests.length === 1) return route.abort('failed')
      return route.fulfill({ json: { operation: { operation_id: requests[0].operation_id, activation_id: detail.activation_id, status: 'pending', state: 'closing', revision: 13, reason: null } } })
    }
    return route.fulfill({ json: url.pathname.endsWith('/activations') ? { activations: [detail], next_after: null } : detail })
  })
  await page.goto('/?symbol=BTC%2FUSDC')
  const panel = page.getByRole('region', { name: 'BTC/USDC trade information', exact: true })
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
  await expect(panel).toBeVisible()
  await panel.scrollIntoViewIfNeeded()
  await panel.getByRole('button', { name: 'Sell and close', exact: true }).click()
  expect(requests).toHaveLength(0)
  await panel.getByRole('button', { name: 'Confirm close holding', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Retry same request' })).toBeVisible()
  await page.reload()
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Retry same request' })).toBeEnabled()
  await panel.getByRole('button', { name: 'Retry same request' }).click()
  await expect(panel.getByText(/Request recorded. Work is pending/)).toBeVisible()
  expect(requests).toHaveLength(2)
  expect(requests[1]).toEqual(requests[0])
  await expect(panel.getByRole('button', { name: 'Retry remaining sale', exact: true })).toBeEnabled()
  const overflow = await panel.evaluate(element => element.scrollWidth > element.clientWidth)
  expect(overflow).toBe(false)
  if (testInfo.project.name === 'mobile-chromium') {
    const targets = await panel.getByRole('button').evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().height))
    expect(targets.every(height => height >= 44)).toBe(true)
  }
  await panel.screenshot({ path: `/private/tmp/moonwalker-accumulation-${testInfo.project.name}.png` })
})

test('creates an accumulation variant and explicitly switches a holding to its exact version', async ({ page }, testInfo) => {
  const parameters = { timeframe: '1h', peak_length: 168, atr_length: 14, entry_atr: '1.5', spacing_atr: '1', recovery_atr: '1', min_fraction: '0.02', slope: '0.03', max_fraction: '0.20' }
  const versions: Array<Record<string, unknown>> = []
  const switches: Record<string, unknown>[] = []
  let pin = 5
  await page.route('**/config/all', route => route.fulfill({ json: {
    timezone: 'Europe/Vienna', signal: 'csv_signal', signal_settings: JSON.stringify({ csv_source: 'signals.csv' }), exchange: 'binance',
    timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
    bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d', dca: true, dry_run: true, mstc: 4, trading_paused: false,
    trade_mode: 'accumulation', accumulation_available: true, accumulation_strategy_version_id: 5, market: 'spot',
  } }))
  await page.route('**/strategies', route => route.fulfill({ json: { strategies: [], palette: [] } }))
  await page.route('**/accumulation/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/strategies')) {
      if (route.request().method() === 'POST') {
        const payload = route.request().postDataJSON()
        versions.push({ id: 17, slug: 'simulated-variant', name: payload.name, version: 1, parameters: payload.parameters, required_history_candles: 253 })
        return route.fulfill({ json: { id: 17, name: payload.name, version: 1 } })
      }
      return route.fulfill({ json: { versions, defaults: parameters, timeframes: ['1h', '4h'], next_after_id: null } })
    }
    if (route.request().method() === 'POST') {
      const command = route.request().postDataJSON()
      switches.push(command)
      pin = command.target_version_id
      return route.fulfill({ json: { operation: { operation_id: command.operation_id, status: 'pending', state: 'switching', revision: 13, reason: null } } })
    }
    const row = {
      activation_id: 'simulated-holding', symbol: 'BTC/USDC', state: 'paused', explicitly_paused: true,
      revision: 12, reason: null, runtime_wait_reason: null, observations_initialized: true,
      strategy_version_id: pin, strategy_slug: pin === 5 ? 'Original strategy' : 'Accumulation dip', strategy_version: 1,
      holding_integrity: 'unlinked', holding: null, entry: null, operations: [], older_operations_available: false,
    }
    return route.fulfill({ json: url.pathname.endsWith('/activations') ? { activations: [row], next_after: null } : row })
  })
  await page.goto('/control-center?mode=strategy-builder&target=strategy-builder')
  const editor = page.getByRole('region', { name: 'Accumulation strategies', exact: true })
  await expect(editor).toBeVisible()
  await editor.getByRole('button', { name: 'Save as new accumulation strategy', exact: true }).click()
  await expect(editor.getByText(/Existing holdings keep their current strategy/)).toBeVisible()
  expect(pin).toBe(5)
  await editor.screenshot({ path: `/private/tmp/moonwalker-accumulation-builder-${testInfo.project.name}.png` })
  expect(await editor.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  await page.goto('/control-center?mode=utilities')
  await expect(page.getByText('Inventory and history', { exact: true })).toHaveCount(0)
  await expect(page.locator('.accumulation-panel')).toHaveCount(0)
  await page.goto('/?symbol=BTC%2FUSDC')
  const utilities = page.getByRole('region', { name: 'BTC/USDC trade information', exact: true })
  await expect(utilities.getByLabel('Accumulation strategy version', { exact: true })).toHaveCount(0)
  await expect(utilities.getByRole('button', { name: 'Switch strategy', exact: true })).toHaveCount(0)
  await page.goto('/control-center?mode=setup&target=dca')
  await page.getByText('Change strategy for an existing registration', { exact: true }).click()
  const panel = page.getByRole('region', { name: 'Existing accumulation strategy', exact: true })
  await panel.getByLabel('Strategy for this registration', { exact: true }).click()
  await page.getByText('Accumulation dip · v1 · 1h', { exact: true }).click()
  await panel.getByRole('button', { name: 'Review strategy change', exact: true }).click()
  expect(switches).toHaveLength(0)
  await panel.getByRole('button', { name: 'Confirm strategy change', exact: true }).click()
  await expect.poll(() => switches.length).toBe(1)
  expect(switches[0]).toMatchObject({ action: 'switch_strategy', target_version_id: 17, expected_revision: 12 })
  expect(pin).toBe(17)
})

test('selects accumulation and an exact initial pin in Configuration before entry', async ({ page }, testInfo) => {
  const configured: Record<string, unknown> = {
    timezone: 'Europe/Vienna', signal: 'csv_signal', signal_settings: JSON.stringify({ csv_source: 'signals.csv' }),
    exchange: 'binance', timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', market: 'spot',
    max_bots: 2, bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d',
    dca: true, dry_run: true, mstc: 4, sos: 2, trading_paused: true, trade_mode: 'dynamic_dca',
    accumulation_available: true, accumulation_strategy_version_id: null,
  }
  const saves: Record<string, { value: unknown; type: string }>[] = []
  await page.route('**/config/all', route => route.fulfill({ json: configured }))
  await page.route('**/config/multiple', async route => {
    const payload = route.request().postDataJSON()
    saves.push(payload)
    for (const [key, value] of Object.entries(payload)) configured[key] = (value as { value: unknown }).value
    return route.fulfill({ json: { message: 'Config updated' } })
  })
  await page.route('**/accumulation/strategies**', route => route.fulfill({ json: {
    versions: [{ id: 17, name: 'Patient dip', version: 1, parameters: { timeframe: '4h' } }], next_after_id: null,
  } }))
  await page.goto('/control-center?mode=setup&target=dca')
  await page.getByText('Accumulation', { exact: true }).click()
  const selector = page.locator('#config-accumulation-strategy')
  await selector.click()
  await page.getByText('Patient dip · v1 · 4h', { exact: true }).click()
  await expect(page.getByText('Dry run trades against the exchange demo account when supported, using demo credentials and funds.', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Save changes', exact: true }).first().click()
  await expect.poll(() => saves.length).toBe(1)
  expect(saves[0].trade_mode).toEqual({ value: 'accumulation', type: 'str' })
  expect(saves[0].accumulation_strategy_version_id).toEqual({ value: 17, type: 'int' })
  expect(saves[0].accumulation_available).toBeUndefined()
  await page.goto('/control-center?mode=setup&target=dca')
  await expect(page.locator('.n-select').filter({ has: selector }).getByText('Patient dip · v1 · 4h', { exact: true })).toBeVisible()
  await page.getByText('Accumulation', { exact: true }).scrollIntoViewIfNeeded()
  await page.locator('.n-card').filter({ hasText: 'Trade modes' }).last().screenshot({ path: `/private/tmp/moonwalker-accumulation-config-${testInfo.project.name}.png` })
})

for (const action of ['declare_ownership', 'restore_inventory', 'acknowledge_settlement', 'empty_stop'] as const) {
  test(`reviews ${action} without creating an unintended order`, async ({ page }, testInfo) => {
    await page.route('**/config/all', route => route.fulfill({ json: {
      timezone: 'Europe/Vienna', signal: 'csv_signal', signal_settings: JSON.stringify({ csv_source: 'signals.csv' }), exchange: 'binance',
      timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
      bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d', dca: false, dry_run: true, mstc: 4,
    } }))
    const owned = { net_quantity: '0.100000000000000001', remaining_cost: '12', contributed_quote: '12', disposal_proceeds: '0', basis_provenance: 'exchange_fills', execution_history_complete: true, fees: { totals: {}, pending_reports: 0 } }
    const prior = { operation_id: 'settled-close', action: 'close', status: 'quarantined', result_state: 'closing', result_revision: 19, reason: 'restore_validation_required' }
    const detail: AccumulationDetail = {
      activation_id: 'reviewed-repair', symbol: 'BTC/USDC', state: action === 'acknowledge_settlement' ? 'closing' : 'paused', explicitly_paused: true,
      account_matches: action !== 'declare_ownership', revision: 20, reason: null, runtime_wait_reason: null, observations_initialized: true,
      strategy_version_id: 5, strategy_slug: 'Patient dip', strategy_version: 1,
      holding_integrity: ['restore_inventory', 'empty_stop'].includes(action) ? 'unlinked' : 'owned',
      inventory_restore_required: action === 'restore_inventory', holding: ['restore_inventory', 'empty_stop'].includes(action) ? null : owned,
      settled_commands: action === 'acknowledge_settlement' ? [prior] : [], entry: null, operations: [], older_operations_available: false,
    }
    const requests: Record<string, unknown>[] = []
    await page.route('**/accumulation/**', route => {
      const path = new URL(route.request().url()).pathname
      if (route.request().method() === 'POST') {
        const command = route.request().postDataJSON()
        requests.push(command)
        expect(command.action).toBe(action === 'empty_stop' ? 'close' : action)
        detail.revision = 21
        detail.account_matches = true
        if (action === 'restore_inventory') { detail.holding = owned; detail.holding_integrity = 'owned'; detail.inventory_restore_required = false }
        if (action === 'declare_ownership') { detail.holding!.execution_history_complete = false; detail.holding!.basis_provenance = 'operator_declared_ownership' }
        if (action === 'empty_stop') detail.state = 'stopped'
        if (action === 'acknowledge_settlement') { detail.settled_commands = []; detail.close_predecessor = { ...prior, status: 'reconciled', result_revision: 21 } }
        return route.fulfill({ json: { operation: { operation_id: command.operation_id, activation_id: detail.activation_id, status: 'applied', state: detail.state, revision: 21, reason: null } } })
      }
      return route.fulfill({ json: path.endsWith('/strategies') ? { versions: [], next_after_id: null } : path.endsWith('/activations') ? { activations: [detail], next_after: null } : detail })
    })
    await page.goto('/?symbol=BTC%2FUSDC')
    const panel = page.getByRole('region', { name: 'BTC/USDC trade information', exact: true })
  await expect(panel.locator('.assigned-strategy')).toBeVisible()
    if (action === 'declare_ownership') {
      await panel.getByText('Explicit ownership declaration', { exact: true }).click()
      await panel.getByLabel('Type BTC/USDC exactly').fill('BTC/USDC')
      await panel.getByLabel('Ownership declaration reason').fill('I verified ownership in this configured account')
    }
    const labels = { declare_ownership: 'Declare ownership under changed credentials', restore_inventory: 'Restore recorded inventory link', acknowledge_settlement: 'Acknowledge recorded sale settlement', empty_stop: 'Close holding' }
    await panel.getByRole('button', { name: labels[action], exact: true }).click()
    expect(requests).toHaveLength(0)
    await panel.getByRole('button', { name: `Confirm ${labels[action].toLowerCase()}`, exact: true }).click()
    await expect.poll(() => requests.length).toBe(1)
    expect(requests[0]).not.toHaveProperty('quantity')
    if (action === 'declare_ownership') expect(requests[0]).toMatchObject({ confirmation: 'BTC/USDC', note: 'I verified ownership in this configured account' })
    if (action === 'restore_inventory') await expect(panel.getByRole('button', { name: 'Resume accumulation', exact: true })).toBeEnabled()
    if (action === 'acknowledge_settlement') await expect(panel.getByRole('button', { name: 'Retry remaining sale', exact: true })).toBeEnabled()
    if (action === 'empty_stop') await expect(panel.getByRole('button', { name: 'Reactivate', exact: true })).toBeEnabled()
    expect(await panel.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
    await panel.screenshot({ path: `/private/tmp/moonwalker-accumulation-${action}-${testInfo.project.name}.png` })
  })
}
