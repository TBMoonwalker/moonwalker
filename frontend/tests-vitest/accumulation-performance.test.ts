import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import Statistics from '../src/components/Statistics.vue'
import { useWebSocketDataStore } from '../src/stores/websocket'

vi.mock('../src/control-center/configSnapshotStore', () => ({
  useSharedConfigSnapshot: () => ({ snapshot: ref({ currency: 'USDC' }) }),
}))

describe('accumulation performance coverage', () => {
  it('withholds net return and estimated portfolio value for partial performance coverage', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(Statistics, { global: { plugins: [pinia] } })
    const statistics = useWebSocketDataStore('statistics')
    const data = { upnl: 5, profit_overall: 7, funds_locked: 10, funds_available: 20 }
    statistics.setRaw(JSON.stringify(data))
    await flushPromises()
    expect(wrapper.text()).toContain('7.00')
    statistics.setRaw(JSON.stringify({ ...data, performance_complete: false }))
    await flushPromises()
    expect(wrapper.text()).toContain('Accumulation returns are not included')
    expect(wrapper.find('.profit-summary').text()).toContain('Unavailable')
    expect(wrapper.find('.profit-summary').text()).not.toContain('7.00')
    expect(wrapper.find('.exposure-totals').text()).toContain('Portfolio value Unavailable')
    expect(wrapper.text()).toContain('Exchange free 20.00')
  })
})
