import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import AccumulationStrategyWorkspace from '../src/components/control-center/AccumulationStrategyWorkspace.vue'

const api = vi.hoisted(() => ({ fetchAccumulationStrategies: vi.fn(), saveAccumulationStrategy: vi.fn(), accumulationErrorStatus: vi.fn() }))
vi.mock('../src/api/accumulation', () => api)
const defaults = { timeframe: '1h', peak_length: 168, atr_length: 14, entry_atr: '1.5', spacing_atr: '1', recovery_atr: '1', min_fraction: '0.02', slope: '0.03', max_fraction: '0.20' }

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchAccumulationStrategies.mockResolvedValue({ versions: [], next_after_id: null, defaults, timeframes: ['1h', '4h'] })
  api.accumulationErrorStatus.mockImplementation(error => error?.status)
  api.saveAccumulationStrategy.mockResolvedValue({ id: 17, name: 'Accumulation dip', version: 1 })
})

it('hides the editor behind the source release gate', async () => {
  api.fetchAccumulationStrategies.mockRejectedValueOnce({ status: 503 })
  const wrapper = mount(AccumulationStrategyWorkspace)
  await flushPromises()
  expect(wrapper.find('section').exists()).toBe(false)
  expect(api.saveAccumulationStrategy).not.toHaveBeenCalled()
})

it('saves a complete immutable parameter snapshot and states that holdings keep their pin', async () => {
  const wrapper = mount(AccumulationStrategyWorkspace)
  await flushPromises()
  const button = wrapper.findAll('button').find(row => row.text() === 'Save as new accumulation strategy')!
  await button.trigger('click')
  await flushPromises()
  expect(api.saveAccumulationStrategy.mock.calls[0][0]).toMatchObject({ name: 'Accumulation dip', parameters: defaults })
  expect(wrapper.text()).toContain('Existing holdings keep their current strategy')
})

it('retries an ambiguous save with the same ID and exact parameters', async () => {
  api.saveAccumulationStrategy.mockRejectedValueOnce(new Error('Connection lost'))
  const wrapper = mount(AccumulationStrategyWorkspace)
  await flushPromises()
  await wrapper.findAll('button').find(row => row.text() === 'Save as new accumulation strategy')!.trigger('click')
  await flushPromises()
  const request = api.saveAccumulationStrategy.mock.calls[0][0]
  await wrapper.findAll('button').find(row => row.text() === 'Retry same strategy save')!.trigger('click')
  await flushPromises()
  expect(api.saveAccumulationStrategy.mock.calls[1][0]).toEqual(request)
})
