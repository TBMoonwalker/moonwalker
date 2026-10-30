import { expect, test, type WebSocketRoute } from '@playwright/test'

test.use({ screenshot: 'on' })

test('overview waits for new snapshots and rejects an old sell confirmation', async ({ page }) => {
  await page.clock.install()
  await page.addInitScript(() => {
    let hidden = false
    let online = true
    const NativeWebSocket = window.WebSocket
    const sockets: WebSocket[] = []
    window.WebSocket = new Proxy(NativeWebSocket, {
      construct(target, args) {
        const socket = Reflect.construct(target, args) as WebSocket
        sockets.push(socket)
        return socket
      },
    })
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => online })
    Object.assign(window, { setTestHidden(value: boolean) {
      hidden = value
      document.dispatchEvent(new Event('visibilitychange'))
    }, setTestOnline(value: boolean) {
      online = value
      window.dispatchEvent(new Event(value ? 'online' : 'offline'))
    }, sendObsoleteTrade(value: string) {
      const oldSocket = sockets.find(socket => socket.url.includes('/trades/open'))
      oldSocket?.dispatchEvent(new MessageEvent('message', { data: value }))
    } })
  })
  const trades: WebSocketRoute[] = []
  const statistics: WebSocketRoute[] = []
  const row = { id: 1, symbol: 'BTC/USDC', deal_id: 'deal-1', amount: 1, cost: 100,
    profit: 0, profit_percent: 0, current_price: 100, tp_price: 101, avg_price: 100,
    so_count: 0, open_date: '2026-10-01T00:00:00Z', precision: 8,
    baseorder: { id: 1, timestamp: '2026-10-01T00:00:00Z', ordersize: 100, amount: 1, symbol: 'BTC/USDC', price: 100 }, safetyorder: [] }
  const profit = { funds_available: 100, profit_overall: 1, funds_locked: 100,
    profit_overall_timestamp: '2026-10-29 08:00:00', performance_complete: true }
  await page.routeWebSocket('**/trades/open*', socket => { trades.push(socket); if (trades.length === 1) socket.send(JSON.stringify([row])) })
  await page.routeWebSocket('**/statistic/profit*', socket => { statistics.push(socket); if (statistics.length === 1) socket.send(JSON.stringify(profit)) })
  await page.routeWebSocket('**/trades/closed', socket => socket.send('[]'))
  await page.routeWebSocket('**/trades/unsellable', socket => socket.send('[]'))
  await page.routeWebSocket('**/accumulation/stream**', () => {})
  await page.route('**/config/all', route => route.fulfill({ json: {
    trade_mode: 'accumulation', accumulation_available: true, accumulation_strategy_version_id: 7,
    market: 'spot', timezone: 'Europe/Vienna', signal: 'asap',
    symbol_list: 'BTC/USDC', exchange: 'binance', timeframe: '1h', key: 'test-only',
    secret: 'test-only', currency: 'USDC', max_bots: 2, bo: 10, tp: 1,
    capital_max_fund: 100, history_lookback_time: '180d', dca: true, dry_run: true, mstc: 4,
    config_revision: 1,
    ws_watchdog_enabled: false,
  } }))
  await page.route('**/config/freshness', route => route.fulfill({ json: { config_revision: 1 } }))
  await page.route('**/accumulation/**', route => route.fulfill({ status: 503, json: {} }))
  await page.route('**/statistic/profit-overall/timeline', route => route.fulfill({ json: [] }))
  await page.route('**/trades/closed/length', route => route.fulfill({ json: { result: 0 } }))
  let orders = 0
  await page.route('**/orders/**', route => { orders++; return route.fulfill({ json: { result: 'sell' } }) })
  await page.goto('/')
  const sell = page.getByRole('button', { name: 'Sell BTC/USDC' })
  await expect(sell).toBeEnabled()
  await sell.click()
  const confirm = page.getByRole('button', { name: 'Sell', exact: true }).last()
  await expect(confirm).toBeVisible()
  await page.evaluate(() => (window as unknown as { setTestHidden: (value: boolean) => void }).setTestHidden(true))
  await page.evaluate(() => (window as unknown as { setTestHidden: (value: boolean) => void }).setTestHidden(false))
  await expect.poll(() => trades.length).toBe(2)
  await expect.poll(() => statistics.length).toBe(2)
  await confirm.click()
  expect(orders).toBe(0)
  // Value: protects=malformed recovery snapshots cannot enable trade actions;
  // fails_when=invalid socket data certifies freshness; why_new=the prior flow
  // waited only for valid data; seam=none; no_claim=real exchange data.
  trades[1].send('not-json')
  statistics[1].send(JSON.stringify({ funds_available: 'invalid' }))
  await expect(sell).toHaveCount(0)
  trades[1].send(JSON.stringify([{ ...row, amount: 2 }]))
  statistics[1].send(JSON.stringify(profit))
  await expect(sell).toBeEnabled()
  await page.evaluate((payload) => (window as unknown as { sendObsoleteTrade: (value: string) => void }).sendObsoleteTrade(payload), JSON.stringify([row]))
  await confirm.click()
  expect(orders).toBe(0)
  await expect(page.getByText('Trade or available funds changed. Close this dialog and review the action again.')).toBeVisible()
  await page.getByRole('button', { name: 'Do not sell' }).click()
  // Value: protects=offline recovery waits for fresh trade and balance data;
  // fails_when=returning online reuses stale snapshots; why_new=visibility
  // recovery does not exercise online events; seam=none; no_claim=real outage.
  await page.evaluate(() => (window as unknown as { setTestOnline: (value: boolean) => void }).setTestOnline(false))
  await expect(sell).toBeDisabled()
  await page.evaluate(() => (window as unknown as { setTestOnline: (value: boolean) => void }).setTestOnline(true))
  await expect.poll(() => trades.length).toBe(3)
  await expect.poll(() => statistics.length).toBe(3)
  await expect(sell).toBeDisabled()
  trades[2].send(JSON.stringify([{ ...row, amount: 2 }]))
  statistics[2].send(JSON.stringify(profit))
  await expect(sell).toBeEnabled()
  await page.clock.fastForward(26000)
  await expect(sell).toBeDisabled()
})

test('an initially hidden dashboard opens its streams only when visible', async ({ page }) => {
  await page.addInitScript(() => {
    let hidden = true
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    Object.assign(window, { showTestPage() {
      hidden = false
      document.dispatchEvent(new Event('visibilitychange'))
    } })
  })
  let openTrades = 0
  let statistics = 0
  await page.routeWebSocket('**/trades/open*', socket => {
    openTrades++
    socket.send('[]')
  })
  await page.routeWebSocket('**/statistic/profit*', socket => {
    statistics++
    socket.send(JSON.stringify({ funds_available: 100 }))
  })
  await page.routeWebSocket('**/trades/closed', socket => socket.send('[]'))
  await page.routeWebSocket('**/trades/unsellable', socket => socket.send('[]'))
  await page.routeWebSocket('**/accumulation/stream**', () => {})
  await page.route('**/config/all', route => route.fulfill({ json: {
    trade_mode: 'dynamic_dca', market: 'spot', exchange: 'binance', currency: 'USDC',
    ws_watchdog_enabled: false,
  } }))
  await page.route('**/config/freshness', route => route.fulfill({ json: {} }))
  await page.route('**/statistic/profit-overall/timeline', route => route.fulfill({ json: [] }))
  await page.route('**/trades/closed/length', route => route.fulfill({ json: { result: 0 } }))
  await page.goto('/')
  expect(openTrades).toBe(0)
  expect(statistics).toBe(0)
  await page.evaluate(() => (window as unknown as { showTestPage: () => void }).showTestPage())
  await expect.poll(() => openTrades).toBe(1)
  await expect.poll(() => statistics).toBe(1)
})
