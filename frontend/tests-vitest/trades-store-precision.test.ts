import { beforeEach, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTradesStore } from '../src/stores/trades'

beforeEach(() => setActivePinia(createPinia()))

it('keeps the decimal digits of non-integer values and falls back for integers', () => {
    const store = useTradesStore()
    store.setOpenTrades([
        {
            id: 1,
            symbol: 'BTC/USDT',
            amount: 1.234,
            cost: 100,
            profit: 5,
            profit_percent: 5,
            current_price: 100.5,
            tp_price: 100,
            avg_price: 99.99,
            so_count: 0,
            open_date: '2026-01-01',
        },
    ])
    const row = store.openTrades[0]
    expect(row?.amount).toBe('1.234')
    expect(row?.cost).toBe('100')
    expect(row?.current_price).toBe('100.5')
    expect(row?.tp_price).toBe('100')
    expect(row?.avg_price).toBe('99.99')
    expect(row?.precision).toBe(1)
})

it('treats string values as the fallback precision, as before', () => {
    const store = useTradesStore()
    store.setOpenTrades([
        {
            id: 2,
            symbol: 'ETH/USDT',
            amount: '1.23',
            cost: '10.5',
            profit: 1,
            profit_percent: 1,
            current_price: '9.999',
            tp_price: 10,
            avg_price: 9,
            so_count: 0,
            open_date: '2026-01-01',
        },
    ])
    const row = store.openTrades[0]
    expect(row?.amount).toBe('1')
    expect(row?.cost).toBe('11')
    expect(row?.current_price).toBe('10')
    expect(row?.precision).toBe(0)
})

it('clamps closed-trade price precision between the fallback and the observed digits', () => {
    const store = useTradesStore()
    store.setClosedTrades([
        {
            id: 3,
            symbol: 'SOL/USDT',
            amount: 1.5,
            cost: 10,
            tp_price: 100.123,
            avg_price: 100.5,
            profit: 1,
            profit_percent: 1,
            so_count: 0,
            open_date: '2026-01-01',
            duration: '{}',
            close_date: '2026-01-02',
        },
    ])
    const row = store.closedTrades[0]
    expect(row?.amount).toBe('1.5')
    expect(row?.tp_price).toBe('100.123')
    expect(row?.avg_price).toBe('100.50')
    expect(row?.precision).toBe(3)
})
