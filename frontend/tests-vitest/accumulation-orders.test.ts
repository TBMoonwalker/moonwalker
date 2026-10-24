import { describe, expect, it } from 'vitest'
import { accumulationOrders } from '../src/helpers/accumulationOrders'
import type { AccumulationOrderCheckpoint } from '../src/types/accumulation'
import type { TradeExecutionRow } from '../src/stores/trades'
const checkpoint = (overrides = {}): AccumulationOrderCheckpoint => ({ checkpoint_id: 7, placement_operation_id: 'buy-1', deal_id: 'current', side: 'buy', filled_quantity: '0.100000000000000001', quote_cost: '12.000000000000000001', fees: null, fees_complete: false, terminal: true, updated_at: '2026-10-22T10:00:00Z', inventory_at_update: null, ...overrides })
const execution = (id: number, operation = 'buy-1', deal = 'current'): TradeExecutionRow => ({ id, deal_id: deal, symbol: 'BTC/USDC', side: 'buy', role: 'accumulation_buy', timestamp: String(id * 1000), price: 120, amount: 0.1, ordersize: 12, fee: 0, metadata_json: JSON.stringify({ accumulation: { operation_id: operation } }) })
describe('accumulation order evidence', () => {
  it('collapses native fill and fee corrections into one cumulative order with exact evidence', () => {
    const orders = accumulationOrders([checkpoint()], [execution(1), execution(2)], 'current')
    expect(orders).toHaveLength(1)
    expect(orders[0]).toMatchObject({ key: 'checkpoint-7', title: 'Base order', timestamp: '1000', checkpoint: { filled_quantity: '0.100000000000000001', fees_complete: false } })
    const corrected = accumulationOrders([checkpoint({ fees: { BTC: '0.000000000000000001' }, fees_complete: true })], [execution(1), execution(2)], 'current')
    expect(corrected).toHaveLength(1)
    expect(corrected[0].key).toBe(orders[0].key)
    expect(corrected[0].checkpoint?.fees).toEqual({ BTC: '0.000000000000000001' })
  })
  it('keeps older fill corrections in their order when cumulative checkpoints leave the recent window', () => {
    const orders = accumulationOrders([], [execution(1), { ...execution(2), amount: 0, ordersize: 0 }, execution(3, 'buy-2')], 'current')
    expect(orders).toHaveLength(2)
    expect(orders.map(order => order.title)).toEqual(['Base order', 'Accumulation order 1'])
    expect(orders[0].content).toBe('Order size: Unknown | Amount: Unknown | Price: 120')
  })
  it('does not join another generation or guess a match from equal amounts', () => {
    const orders = accumulationOrders([checkpoint({ deal_id: 'earlier' })], [execution(1)], 'current')
    expect(orders).toHaveLength(1)
    expect(orders[0].checkpoint).toBeUndefined()
    expect(orders[0].title).toBe('Base order')
  })
  it('keeps separate accumulation orders and preserves a base home while awaiting entry', () => {
    const orders = accumulationOrders([checkpoint(), checkpoint({ checkpoint_id: 8, placement_operation_id: 'buy-2' })], [execution(1), execution(2, 'buy-2')], 'current')
    expect(orders.map(order => order.title)).toEqual(['Base order', 'Accumulation order 1'])
    expect(accumulationOrders([], [], null)).toEqual([{ key: 'registration', title: 'Entry registration', base: true }])
  })
})


it('shows no previous-cycle evidence while a fresh accumulation awaits its base order', () => {
  expect(accumulationOrders([checkpoint({ deal_id: 'sold' })], [execution(1, 'sold-buy', 'sold')], null))
    .toEqual([{ key: 'registration', title: 'Entry registration', base: true }])
})

it('numbers the new base order independently of all previous-cycle buys and sales', () => {
  const old = checkpoint({ checkpoint_id: 1, deal_id: 'sold', side: 'sell' })
  const orders = accumulationOrders([old, checkpoint()], [execution(0, 'old-buy', 'sold'), execution(1)], 'current')
  expect(orders).toHaveLength(1)
  expect(orders[0]).toMatchObject({ title: 'Base order', base: true, checkpoint: { deal_id: 'current' } })
})


it('shows declared CSV base then native accumulation purchases without mixing cycles', () => {
  const declared = { key: 'csv-1', deal_id: 'current', symbol: 'BTC/USDC', timestamp: '100', price: '81.000000000000000001', amount: '0.01227109', ordersize: '1000.139592', fees: { BTC: '0.00003075' }, fees_known: true, provenance: 'csv_declaration' as const }
  const orders = accumulationOrders([checkpoint()], [execution(1)], 'current', [], [declared, { ...declared, key: 'old', deal_id: 'sold' }])
  expect(orders.map(row => row.title)).toEqual(['Base order · CSV', 'Accumulation order 1'])
  expect(orders[0].content).toContain('Price: 81.000000000000000001')
  expect(orders[1].checkpoint?.placement_operation_id).toBe('buy-1')
  expect(accumulationOrders([], [], null, [], [declared])).toEqual([{ key: 'registration', title: 'Entry registration', base: true }])
})

it('keeps corrupt declaration history unavailable instead of calling a later native buy the base', () => {
  const orders = accumulationOrders([checkpoint()], [execution(1)], 'current', [], [], true)
  expect(orders.find(row => row.checkpoint)?.title).toBe('Accumulation order 1')
  expect(orders.some(row => row.title === 'Base order')).toBe(false)
})
