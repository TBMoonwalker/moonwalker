import { expect, test, type WebSocketRoute } from '@playwright/test'
import type { AccumulationDetail } from '../src/types/accumulation'

test('shows accumulation only beneath its open trade chart and receives pushed waits', async ({ page }, testInfo) => {
  const stamp = Date.now() - 3600000
  const order = { id: 1, timestamp: String(stamp), ordersize: 10, amount: 0.1, symbol: 'BTC/USDC', price: 100 }
  const trade = { id: 1, key: 1, symbol: 'BTC/USDC', lifecycle_mode: 'accumulation', deal_id: 'fixture-holding',
    amount: 0.1, cost: 10, current_price: 100, avg_price: 100, profit: 0, profit_percent: 0, tp_price: 0, precision: 2,
    so_count: 0, open_date: new Date(stamp).toISOString(), baseorder: order, safetyorder: [] }
  const detail: AccumulationDetail = { activation_id: 'fixture', symbol: 'BTC/USDC', state: 'enabled', explicitly_paused: false,
    account_matches: true, revision: 4, reason: null, runtime_wait_reason: 'WAIT_DEPTH', observations_initialized: true,
    strategy_version_id: 7, strategy_slug: 'dip', strategy_version: 1, holding_integrity: 'owned',
    holding: { net_quantity: '0.1', remaining_cost: '10', contributed_quote: '10', disposal_proceeds: '0', basis_provenance: 'exchange_fills', execution_history_complete: true, fees: { totals: {}, pending_reports: 0 } },
    entry: null, operations: [], older_operations_available: false,
    wait_condition: { reason: 'WAIT_DEPTH', timeframe: '1h', observed_close_ms: stamp, observed_price: '100', next_close_ms: stamp + 3600000,
      levels: [{ kind: 'depth', direction: 'at_or_below', target_price: '98', change_percent: '-2' }] } }
  const sockets: WebSocketRoute[] = []
  await page.routeWebSocket('**/accumulation/stream**', socket => { sockets.push(socket) })
  await page.routeWebSocket('**/trades/open', socket => socket.send(JSON.stringify([trade])))
  for (const path of ['closed', 'unsellable', 'waiting']) await page.routeWebSocket(`**/trades/${path}`, socket => socket.send('[]'))
  await page.routeWebSocket('**/statistic/profit', socket => socket.send('{}'))
  await page.route('**/config/all', route => route.fulfill({ json: {
    trade_mode: 'accumulation', accumulation_available: true, market: 'spot', accumulation_strategy_version_id: 7,
    timezone: 'Europe/Vienna', signal: 'asap', symbol_list: 'BTC/USDC', exchange: 'binance',
    timeframe: '1h', key: 'test-only', secret: 'test-only', currency: 'USDC', max_bots: 2,
    bo: 10, tp: 1, capital_max_fund: 100, history_lookback_time: '180d', dca: true, dry_run: true, mstc: 4,
  } }))
  let commands = 0
  await page.route('**/accumulation/**', route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'POST') commands++
    return route.fulfill({ json: path.endsWith('/strategies') ? { versions: [{ id: 7, name: 'Patient dip', version: 1, parameters: { timeframe: '1h' } }, { id: 8, name: 'Deeper dip', version: 2, parameters: { timeframe: '4h' } }], next_after_id: null }
      : path.endsWith('/activations') ? { activations: [detail], next_after: null } : detail })
  })
  await page.route('**/trades/executions/**', route => route.fulfill({ json: { result: [{ ...order, deal_id: 'fixture-holding', side: 'buy', role: 'accumulation_buy' }] } }))
  await page.route('**/data/ohlcv/**', route => route.fulfill({ json: [] }))
  await page.route('**/trades/*/length', route => route.fulfill({ json: { result: 1 } }))
  await page.goto('/')
  await expect(page.getByText('Manage accumulation', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Historical strategy comparison', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Pending accumulation entries' })).toHaveCount(0)
  await page.getByRole('row', { name: 'Toggle trade details for BTC/USDC' }).click()
  const card = page.getByRole('region', { name: 'BTC/USDC accumulation', exact: true })
  await expect(card.getByRole('heading', { name: 'Waiting for next buy' })).toBeVisible()
  await expect(card.getByText('≈ 2.00% fall', { exact: true })).toBeVisible()
  await expect(card.getByText('Patient dip · v1 · 1h', { exact: true })).toBeVisible()
  await expect(card.getByRole('button', { name: 'Pause accumulation', exact: true })).toBeEnabled()
  await expect(card.getByRole('button', { name: 'Sell and close', exact: true })).toBeEnabled()
  expect(await card.evaluate(element => {
    const chart = element.parentElement!.querySelector('.expanded-replay-chart')!
    return !!(chart.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING)
  })).toBe(true)
  expect(await card.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(false)
  await expect.poll(() => sockets.length).toBeGreaterThan(1)
  detail.revision++
  detail.wait_condition!.levels[0]!.target_price = '97'
  detail.wait_condition!.levels[0]!.change_percent = '-3'
  sockets.at(-1)!.send(JSON.stringify({ type: 'snapshot', page: { activations: [detail], next_after: null }, detail }))
  await expect(card.getByText('≈ 3.00% fall', { exact: true })).toBeVisible()
  await card.getByText('Change strategy', { exact: true }).click()
  await expect(card.getByLabel('Accumulation strategy', { exact: true })).toBeVisible()
  expect(commands).toBe(0)
  await card.screenshot({ path: `/private/tmp/accumulation-inline-${testInfo.project.name}.png` })
})
