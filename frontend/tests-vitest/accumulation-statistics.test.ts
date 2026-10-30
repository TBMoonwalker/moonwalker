import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AccumulationStatistics from '../src/components/AccumulationStatistics.vue'

const fetchJson = vi.hoisted(() => vi.fn())
vi.mock('../src/api/client', () => ({ fetchJson }))

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(public url: string) { FakeWebSocket.instances.push(this) }
  sendSnapshot(performance: unknown, activityRevision = 1, accountGeneration = 0) {
    this.onmessage?.({ data: JSON.stringify({ type: 'snapshot', performance, activity_revision: activityRevision, account_generation: accountGeneration }) })
  }
  close() { this.onclose?.() }
}

const performance = (now = Date.now()) => ({
  observed_at_ms: now, valid_until_ms: now + 10000, includes_csv_declarations: true,
  holdings: [{ symbol: 'BTC/USDC', quantity: '0.019', remaining_cost: '123.456', average_cost: '9007199254740993.1299', market_value: '124.999', unrealized: '-0.009', complete: false, basis_provenance: 'csv_declared_fees_unknown' }],
  by_quote: [{ quote: 'USDC', contributed_quote: '100', remaining_cost: '100.125', market_value: '124.999', realized: null, unrealized: '-0.009', total_return: null, complete: false, unknown_deal_count: 1, live_holding_count: 1 }],
})

beforeEach(() => {
  FakeWebSocket.instances = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
  fetchJson.mockResolvedValue({ items: [], next_cursor: null })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  fetchJson.mockReset()
})

describe('accumulation statistics', () => {
  it('suspends its stream in a hidden tab and reconnects once when visible', async () => {
    let hidden = false
    vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
    const wrapper = mount(AccumulationStatistics)
    const oldSocket = FakeWebSocket.instances[0]
    oldSocket.sendSnapshot(performance())
    await flushPromises()

    hidden = true
    document.dispatchEvent(new Event('visibilitychange'))
    oldSocket.sendSnapshot({ ...performance(), holdings: [] })
    await flushPromises()
    expect(wrapper.text()).toContain('BTC/USDC')
    expect(FakeWebSocket.instances).toHaveLength(1)

    hidden = false
    document.dispatchEvent(new Event('visibilitychange'))
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(FakeWebSocket.instances).toHaveLength(2)
    wrapper.unmount()
  })

  it('does not reuse disconnected history when reconnecting to a different account', async () => {
    vi.useFakeTimers()
    let resolveOld!: (value: unknown) => void
    fetchJson.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    fetchJson.mockResolvedValue({ items: [{ kind: 'order', id: 2, symbol: 'NEW/USDC', side: 'buy', updated_at: '2026-01-01T00:00:00Z' }], next_cursor: null })
    const wrapper = mount(AccumulationStatistics)
    FakeWebSocket.instances[0].close()
    resolveOld({ items: [{ kind: 'order', id: 1, symbol: 'OLD/USDC', side: 'buy', updated_at: '2026-01-01T00:00:00Z' }], next_cursor: null })
    await flushPromises()
    expect(wrapper.text()).not.toContain('OLD/USDC')
    expect(fetchJson).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2000)
    FakeWebSocket.instances[1].sendSnapshot(performance())
    await flushPromises()
    expect(wrapper.text()).toContain('NEW/USDC')
    expect(wrapper.text()).not.toContain('OLD/USDC')
    wrapper.unmount()
  })
  it('clears old account history and ignores an in-flight response after account changes', async () => {
    let resolveOld!: (value: unknown) => void
    fetchJson.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    fetchJson.mockResolvedValue({ items: [{ kind: 'order', id: 2, symbol: 'ETH/USDC', side: 'buy', updated_at: '2026-01-01T00:00:00Z', quantity: '2', quote_cost: '10', price_per_coin: '5', terminal: true, fees_complete: true }], next_cursor: null })
    const wrapper = mount(AccumulationStatistics)
    const ws = FakeWebSocket.instances[0]
    ws.sendSnapshot(performance(), 1, 0)
    ws.sendSnapshot(performance(), 1, 1)
    resolveOld({ items: [{ kind: 'order', id: 1, symbol: 'OLD/USDC', side: 'buy', updated_at: '2026-01-01T00:00:00Z' }], next_cursor: null })
    await flushPromises()
    expect(wrapper.text()).not.toContain('OLD/USDC')
    expect(wrapper.text()).toContain('ETH/USDC')
    wrapper.unmount()
  })
  it('renders pushed snapshots without polling and truncates exact decimals', async () => {
    const wrapper = mount(AccumulationStatistics, { global: { stubs: ['router-link'] } })
    const ws = FakeWebSocket.instances[0]
    expect(ws.url).toContain('/accumulation/performance/stream')
    ws.sendSnapshot(performance())
    await flushPromises()
    expect(wrapper.text()).toContain('0.0190')
    expect(wrapper.text()).toContain('123.45')
    expect(wrapper.text()).toContain('9007199254740993.12')
    expect(wrapper.text()).toContain('-0.00')
    expect(wrapper.text()).toContain('CSV-declared basis')
    expect(wrapper.text()).toContain('Contributed funds: 100.00')
    expect(wrapper.text()).toContain('Remaining basis: 100.12')
    expect(wrapper.text()).toContain('1 managed holdings')
    expect(wrapper.text()).toContain('Unavailable')
    expect(fetchJson.mock.calls.every(([path]) => path.startsWith('/accumulation/activity'))).toBe(true)
    expect(wrapper.text()).not.toContain('Restart history')
    expect(wrapper.findAll('a')).toHaveLength(0)
    const table = wrapper.find('table').element
    ws.sendSnapshot({ ...performance(), holdings: [{ ...performance().holdings[0], quantity: '0.029' }] })
    await flushPromises()
    expect(wrapper.find('table').element).toBe(table)
    expect(wrapper.text()).toContain('0.0290')
    wrapper.unmount()
  })

  it('distinguishes a pending entry from an empty holding list', async () => {
    const wrapper = mount(AccumulationStatistics)
    FakeWebSocket.instances[0].sendSnapshot({ ...performance(), holdings: [], pending_entry_count: 1 })
    await flushPromises()
    expect(wrapper.text()).toContain('No managed accumulation holdings.')
    expect(wrapper.text()).toContain('1 accumulation entry is awaiting completion.')
    wrapper.unmount()
  })

  it('keeps existing holdings visible when another entry is pending', async () => {
    const wrapper = mount(AccumulationStatistics)
    FakeWebSocket.instances[0].sendSnapshot({ ...performance(), pending_entry_count: 1 })
    await flushPromises()
    expect(wrapper.find('.holdings-table tbody').text()).toContain('BTC/USDC')
    expect(wrapper.text()).toContain('1 accumulation entry is awaiting completion.')
    wrapper.unmount()
  })

  it('keeps the last snapshot until its bid expires and reconnects', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AccumulationStatistics, { global: { stubs: ['router-link'] } })
    const ws = FakeWebSocket.instances[0]
    ws.sendSnapshot({ ...performance(), valid_until_ms: Date.now() + 1000 })
    await flushPromises()
    ws.close()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Reconnecting')
    await vi.advanceTimersByTimeAsync(2000)
    expect(wrapper.text()).toContain('Valuation is stale')
    expect(wrapper.text()).not.toContain('124.99')
    expect(FakeWebSocket.instances).toHaveLength(2)
    FakeWebSocket.instances[1].sendSnapshot(performance())
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('124.99')
    wrapper.unmount()
  })

  it('keeps a fresh value visible between delayed WebSocket updates', async () => {
    vi.useFakeTimers()
    const wrapper = mount(AccumulationStatistics, { global: { stubs: ['router-link'] } })
    const ws = FakeWebSocket.instances[0]
    ws.sendSnapshot(performance())
    await flushPromises()
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.text()).toContain('124.99')
    expect(wrapper.text()).not.toContain('Valuation is stale')
    ws.sendSnapshot(performance())
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('124.99')
    wrapper.unmount()
  })

  it('refreshes invalidated activity automatically and keeps records labeled', async () => {
    fetchJson.mockImplementation((path: string) => {
      if (path.includes('?cursor=')) return Promise.reject(new Error('Request failed: 409 Conflict'))
      return Promise.resolve({ items: [
        { kind: 'order', id: 1, symbol: 'BTC/USDC', side: 'buy', updated_at: '2026-01-01T00:00:00Z', quantity: '1.239567', quote_cost: '100.567', price_per_coin: '81.1309', fees_complete: true, terminal: true },
        { kind: 'csv', id: 1, symbol: 'ETH/USDC', updated_at: '2026-01-02T00:00:00Z', quantity: '2', quote_cost: '50', price_per_coin: '25', fees_complete: false, declaration_complete: true },
      ], next_cursor: 'page-2' })
    })
    const wrapper = mount(AccumulationStatistics, { global: { stubs: ['router-link'] } })
    await flushPromises()
    expect(wrapper.text()).toContain('buy order summary')
    expect(wrapper.text()).toContain('CSV declaration')
    expect(wrapper.text()).toContain('1.239567')
    expect(wrapper.text()).toContain('2.0000')
    expect(wrapper.text()).toContain('81.13')
    expect(wrapper.text()).toContain('25.00')
    await wrapper.findAll('button').find(button => button.text() === 'Load older activity')!.trigger('click')
    await flushPromises()
    expect(fetchJson.mock.calls.filter(([path]) => path === '/accumulation/activity').length).toBe(2)
    expect(wrapper.text()).toContain('buy order summary')
    expect(wrapper.text()).not.toContain('Restart history')
    const ws = FakeWebSocket.instances[0]
    ws.sendSnapshot(performance(), 10)
    await flushPromises()
    const beforeChange = fetchJson.mock.calls.length
    ws.sendSnapshot(performance(), 11)
    await flushPromises()
    expect(fetchJson.mock.calls.length).toBeGreaterThan(beforeChange)
    wrapper.unmount()
  })
})
