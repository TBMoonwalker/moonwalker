import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import ConfigDcaSection from '../src/components/config/ConfigDcaSection.vue'
import type { DcaModel } from '../src/config-editor/types'
import { deriveControlCenterReadiness } from '../src/control-center/readiness'
import { normalizeTradeMode, isDynamicTradeMode } from '../src/helpers/tradeLifecycle'

const api = vi.hoisted(() => ({ fetchAccumulationStrategies: vi.fn() }))
vi.mock('../src/api/accumulation', () => api)
const guard = { blocked: false, can_switch: true, current_trade_mode: 'dynamic_dca', message: null, open_trade_count: 0 }

function render(available: boolean, mode = 'dynamic_dca', signalName = 'asap') {
  return mount(ConfigDcaSection, {
    props: {
      dca: { enabled: true, trade_mode: mode, accumulation_available: available, accumulation_strategy_version_id: 17 } as DcaModel,
      signalName, rules: {}, sellOrderTypeOptions: [], showAdvancedGeneral: false, strategyOptions: [], tradeModeSwitchGuard: guard,
    }, global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchAccumulationStrategies.mockResolvedValue({ versions: [{ id: 17, name: 'Patient dip', version: 1, parameters: { timeframe: '4h' } }], next_after_id: null })
})

it('preserves accumulation rather than silently loading it as Dynamic DCA', () => {
  expect(normalizeTradeMode('accumulation')).toBe('accumulation')
  expect(isDynamicTradeMode('accumulation')).toBe(false)
  expect(normalizeTradeMode('unknown_future_mode')).toBe('unsupported')
  expect(isDynamicTradeMode('unknown_future_mode')).toBe(false)
})

it('disables accumulation selection when the backend release gate is off', async () => {
  const wrapper = render(false)
  await flushPromises()
  const radio = wrapper.findAll('input[type="radio"]').find(input => input.element.getAttribute('value') === 'accumulation')
  const labels = wrapper.findAll('.n-radio-button')
  expect(labels.find(label => label.text() === 'Accumulation')?.classes()).toContain('n-radio-button--disabled')
  expect(radio?.attributes('disabled') !== undefined || labels.some(label => label.text() === 'Accumulation' && label.classes().includes('n-radio-button--disabled'))).toBe(true)
  expect(api.fetchAccumulationStrategies).not.toHaveBeenCalled()
})

it('shows ASAP initial sizing and the saved strategy without automatic exits', async () => {
  const wrapper = render(true, 'accumulation')
  await flushPromises()
  expect(wrapper.text()).toContain('Initial accumulation strategy version')
  expect(wrapper.text()).toContain('Dry run trades against the exchange demo account')
  expect(wrapper.text()).toContain('Max managed symbols')
  expect(wrapper.text()).not.toContain('Take profit percentage')
  expect(wrapper.text()).not.toContain('Base order amount')
  expect(wrapper.text()).toContain('Initial buy amount')
  expect(wrapper.text()).not.toContain('Stop loss percentage')
  expect(api.fetchAccumulationStrategies).toHaveBeenCalledOnce()
})

it('requires the accumulation pin for readiness without demanding DCA sizing or exits', () => {
  const draft = { trade_mode: 'accumulation', accumulation_available: true, market: 'spot', dry_run: true, dca: true, signal: 'asap', bo: 10, symbol_list: 'BTC/USDC', exchange: 'binance', key: 'test', secret: 'test', timeframe: '1h', timezone: 'UTC', currency: 'USDC', max_bots: 2, capital_max_fund: 100, history_lookback_time: '180d' }
  const missing = deriveControlCenterReadiness(draft)
  expect(missing.blockers.map(row => row.key)).toEqual(['accumulation_strategy_version_id'])
  expect(deriveControlCenterReadiness({ ...draft, accumulation_strategy_version_id: 17 }).complete).toBe(true)
  expect(deriveControlCenterReadiness({ ...draft, accumulation_strategy_version_id: 17, accumulation_available: false }).complete).toBe(false)
})


it('does not ask CSV imports to buy an initial position', async () => {
  const wrapper = render(true, 'accumulation', 'csv_signal')
  await flushPromises()
  expect(wrapper.text()).not.toContain('Initial buy amount')
})
