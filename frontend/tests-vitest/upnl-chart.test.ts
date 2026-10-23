import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent } from 'vue'
import { expect, it, vi } from 'vitest'
import UpnlChart from '../src/components/UpnlChart.vue'
import { useWebSocketDataStore } from '../src/stores/websocket'

vi.mock('../src/api/client', () => ({ fetchJson: vi.fn(async () => []) }))
vi.mock('vue-echarts', () => ({ default: defineComponent({ name: 'ChartStub', props: ['option'], template: '<div class="test-chart" />' }) }))

it('shows a visible first performance point after coverage recovers, then a line as history grows', async () => {
  localStorage.clear()
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(UpnlChart, { props: { range: 'all' }, global: { plugins: [pinia] } })
  const statistics = useWebSocketDataStore('statistics')
  await flushPromises()
  const point = { profit_overall: 7, funds_locked: 1000, profit_overall_timestamp: '2026-10-23 12:00:00' }
  statistics.setRaw(JSON.stringify({ ...point, performance_complete: false }))
  await flushPromises()
  expect(wrapper.find('.test-chart').exists()).toBe(false)
  statistics.setRaw(JSON.stringify({ ...point, performance_complete: true }))
  await flushPromises()
  const chart = wrapper.findComponent({ name: 'ChartStub' })
  expect(chart.exists()).toBe(true)
  expect(chart.props('option').series).toEqual(expect.arrayContaining([
    expect.objectContaining({ name: 'Profit overall', data: [7], symbol: 'circle' }),
    expect.objectContaining({ name: 'Funds locked', data: [1000], symbol: 'circle' }),
  ]))
  statistics.setRaw(JSON.stringify({ ...point, profit_overall: 8, performance_complete: true, profit_overall_timestamp: '2026-10-23 12:15:00' }))
  await flushPromises()
  expect(chart.props('option').series[0]).toMatchObject({ data: [7, 8], symbol: 'none' })
  wrapper.unmount()
})
