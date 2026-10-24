import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NSelect } from 'naive-ui/es/select'
import BacktestView from '../src/views/BacktestView.vue'

const api = vi.hoisted(() => ({ fetchJson: vi.fn(), strategies: vi.fn() }))
vi.mock('../src/api/client', async original => ({ ...await original<typeof import('../src/api/client')>(), fetchJson: api.fetchJson }))
vi.mock('../src/api/accumulation', () => ({ fetchAccumulationStrategies: api.strategies }))

beforeEach(() => {
  vi.clearAllMocks()
  api.strategies.mockResolvedValue({ versions: [{ id: 17, name: 'Patient dip', version: 1, parameters: { timeframe: '1h' } }], next_after_id: null })
  api.fetchJson.mockImplementation((path: string) => Promise.resolve(path === '/config/all' ? { currency: 'USDC', timeframe: '4h' } : path === '/strategies' ? { strategies: [{ slug: 'ema20_swing' }] } : { symbols: ['BTC/USDC'] }))
})
function mountView() {
  return mount(BacktestView, { global: { stubs: { BacktestResultChart: true } } })
}
async function selectAccumulation(wrapper: ReturnType<typeof mountView>) {
  const mode = wrapper.findAllComponents(NSelect).find(select => select.props('options')?.some(option => option.value === 'accumulation'))!
  mode.vm.$emit('update:value', 'accumulation')
  await flushPromises()
}

describe('accumulation in the shared Backtest workspace', () => {
  it('requires a saved compatible version and reports a failed catalog load', async () => {
    api.strategies.mockRejectedValue(new Error('Strategy catalog offline'))
    const wrapper = mountView()
    await flushPromises()
    await selectAccumulation(wrapper)
    await wrapper.get('form.backtest-controls').trigger('submit')
    expect(wrapper.text()).toContain('Strategy catalog offline')
    expect(api.fetchJson.mock.calls.some(([path]) => path === '/backtest/run')).toBe(false)
    expect(wrapper.text()).not.toContain('Completed OHLC candles')
    wrapper.unmount()
  })

  it('uses the normal endpoint and exchange timeframe, then displays unsold inventory without closed-trade profit', async () => {
    const wrapper = mountView()
    await flushPromises()
    await selectAccumulation(wrapper)
    api.fetchJson.mockResolvedValueOnce({ trades: [], chart: { candles: [], markers: [], indicators: [] }, stats: { trade_mode: 'accumulation', symbol: 'BTC/USDC', timeframe: '4h' }, accumulation: {
      gap_count: 0, accumulation_trades: [], caveats: [], results: [{ strategy: 'accumulation', units: '1.25', buy_count: 2, spent_quote_including_fees: '100', cash_quote: '900', ending_value_quote: '1020', maximum_drawdown_fraction: '0.05' }],
    } })
    await wrapper.get('form.backtest-controls').trigger('submit')
    await flushPromises()
    const [path, options] = api.fetchJson.mock.calls.find(([path]) => path === '/backtest/run')!
    expect(path).toBe('/backtest/run')
    expect(JSON.parse(options.body)).toMatchObject({ trade_mode: 'accumulation', strategy_version_id: 17, timeframe: '4h', symbol: 'BTC/USDC', funding: '1000' })
    expect(JSON.parse(options.body)).not.toHaveProperty('take_profit_pct')
    expect(wrapper.text()).toContain('Coins accumulated')
    expect(wrapper.text()).toContain('Ending value')
    expect(wrapper.text()).not.toContain('Win rate')
    expect(wrapper.text()).not.toContain('Take profit %')
    wrapper.unmount()
  })

  it('keeps Dynamic DCA on the existing run contract', async () => {
    const wrapper = mountView()
    await flushPromises()
    api.fetchJson.mockResolvedValueOnce({ trades: [], chart: { candles: [], markers: [], indicators: [] }, stats: {} })
    await wrapper.get('form.backtest-controls').trigger('submit')
    await flushPromises()
    const [, options] = api.fetchJson.mock.calls.find(([path]) => path === '/backtest/run')!
    expect(JSON.parse(options.body)).toMatchObject({ trade_mode: 'dynamic_dca', strategy_slug: 'ema20_swing', take_profit_pct: 2.5 })
    expect(api.strategies).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
