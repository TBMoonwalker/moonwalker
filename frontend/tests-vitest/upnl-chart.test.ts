import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import UpnlChart from '../src/components/UpnlChart.vue'
import { useWebSocketDataStore } from '../src/stores/websocket'
import { fetchJson } from '../src/api/client'

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

it('keeps a live point received while resumed history is loading', async () => {
  localStorage.clear()
  let hidden = false
  const visibility = vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
  let resolveHistory!: (value: unknown) => void
  vi.mocked(fetchJson).mockResolvedValueOnce([]).mockImplementationOnce(() => new Promise(resolve => { resolveHistory = resolve }))
  // The return must revalidate: the absence spans the store's 5-minute TTL.
  let now = Date.now()
  const nowSpy = vi.spyOn(Date, 'now').mockImplementation(() => now)
  try {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(UpnlChart, { props: { range: 'all' }, global: { plugins: [pinia] } })
    await flushPromises()
    hidden = true
    document.dispatchEvent(new Event('visibilitychange'))
    hidden = false
    now += 5 * 60 * 1000 + 1
    document.dispatchEvent(new Event('visibilitychange'))
    const statistics = useWebSocketDataStore('statistics')
    statistics.setRaw(JSON.stringify({ profit_overall: 8, funds_locked: 1000, profit_overall_timestamp: '2026-10-23 12:15:00', performance_complete: true }))
    await flushPromises()
    resolveHistory([{ timestamp: '2026-10-23 12:00:00', profit_overall: 7, funds_locked: 1000 }])
    await flushPromises()
    const chart = wrapper.findComponent({ name: 'ChartStub' })
    expect(chart.props('option').series[0].data).toEqual([7, 8])
    wrapper.unmount()
  } finally {
    visibility.mockRestore()
    nowSpy.mockRestore()
  }
})

it('does not refetch the timeline on reactivation while the 5-minute cache is fresh', async () => {
  localStorage.clear()
  vi.mocked(fetchJson).mockReset()
  vi.mocked(fetchJson).mockResolvedValue([
    { timestamp: '2026-11-03 08:04:00', profit_overall: 1, funds_locked: 100 },
  ])
  // Freeze the clock so the return stays inside both the 5-minute TTL and
  // the cached point's 15-minute bucket.
  let now = new Date('2026-11-03T08:05:00Z').getTime()
  const nowSpy = vi.spyOn(Date, 'now').mockImplementation(() => now)
  try {
    const pinia = createPinia()
    setActivePinia(pinia)
    const active = ref(true)
    const Blank = defineComponent({ name: 'Blank', template: '<div class="blank" />' })
    const wrapper = mount(
      defineComponent({
        setup() {
          return () =>
            h(
              KeepAlive,
              null,
              { default: () => (active.value ? h(UpnlChart, { range: 'all' }) : h(Blank)) },
            )
        },
      }),
      { global: { plugins: [pinia] } },
    )
    await flushPromises()
    expect(vi.mocked(fetchJson)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(fetchJson).mock.calls[0][0]).toBe('/statistic/profit-overall/timeline')
    const chart = wrapper.findComponent({ name: 'ChartStub' })
    expect(chart.exists()).toBe(true)

    // Simulate leaving the Overview route and coming back (KeepAlive de/activation).
    active.value = false
    await nextTick()
    active.value = true
    await nextTick()
    await flushPromises()

    // No refetch while the cache is fresh inside the cached bucket — and
    // the deactivation's invalidation must not keep the (fresh, verified)
    // chart hidden.
    expect(vi.mocked(fetchJson)).toHaveBeenCalledTimes(1)
    expect(wrapper.findComponent({ name: 'ChartStub' }).exists()).toBe(true)
    wrapper.unmount()
  } finally {
    nowSpy.mockRestore()
  }
})

// Value: protects=a return across a 15-minute bucket boundary within the
// 5-minute TTL revalidates the timeline, because the cache predates the new
// bucket's history (TTL expiry alone never triggers a fetch);
// fails_when=a regression keeps the unconditional no-force call and the new
// bucket stays missing until the TTL expires and the next trigger fires;
// why_new=the fresh-cache test only covers a return inside the cached
// bucket; seam=none; no_claim=real network timing (the API uses a
// controlled promise; the clock is frozen).
it('revalidates the timeline on reactivation when a 15-minute bucket boundary was crossed', async () => {
  localStorage.clear()
  vi.mocked(fetchJson).mockReset()
  vi.mocked(fetchJson).mockResolvedValue([
    { timestamp: '2026-11-03 08:14:00', profit_overall: 1, funds_locked: 100 },
  ])
  let now = new Date('2026-11-03T08:14:30Z').getTime()
  const nowSpy = vi.spyOn(Date, 'now').mockImplementation(() => now)
  try {
    const pinia = createPinia()
    setActivePinia(pinia)
    const active = ref(true)
    const Blank = defineComponent({ name: 'Blank', template: '<div class="blank" />' })
    const wrapper = mount(
      defineComponent({
        setup() {
          return () =>
            h(
              KeepAlive,
              null,
              { default: () => (active.value ? h(UpnlChart, { range: 'all' }) : h(Blank)) },
            )
        },
      }),
      { global: { plugins: [pinia] } },
    )
    await flushPromises()
    expect(vi.mocked(fetchJson)).toHaveBeenCalledTimes(1)

    // Leave, cross the 08:15 bucket boundary, return — still inside the
    // 5-minute cache TTL.
    active.value = false
    await nextTick()
    now = new Date('2026-11-03T08:16:00Z').getTime()
    active.value = true
    await nextTick()
    await flushPromises()

    // The crossed bucket forces exactly one revalidation fetch.
    expect(vi.mocked(fetchJson)).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  } finally {
    nowSpy.mockRestore()
  }
})
