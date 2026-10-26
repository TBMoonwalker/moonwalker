import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AccumulationOrderStatus from '../src/components/AccumulationOrderStatus.vue'
import type { AccumulationStatus } from '../src/types/accumulation'

const status: AccumulationStatus = {
  activation_id: 'a', symbol: 'BTC/USDC', state: 'enabled', explicitly_paused: false,
  revision: 1, reason: null, runtime_wait_reason: 'WAIT_DEPTH', observations_initialized: true,
  strategy_version_id: 7, strategy_slug: 'dip', strategy_version: 1, holding_integrity: 'owned', holding: null,
  wait_condition: { reason: 'WAIT_DEPTH', timeframe: '1h', observed_close_ms: 1, next_close_ms: 2, observed_price: '100',
    levels: [{ kind: 'depth', direction: 'at_or_below', target_price: '98', change_percent: '-2' }] },
}

describe('accumulation order status', () => {
  it('updates the normal order-status cell from pushed registration data', async () => {
    const wrapper = mount(AccumulationOrderStatus, { props: { status, fresh: true } })
    expect(wrapper.text()).toContain('Fall ≈ 2.00% · ≤ 98 USDC')
    await wrapper.setProps({ status: { ...status, wait_condition: { ...status.wait_condition!, levels: [{ kind: 'depth', direction: 'at_or_below', target_price: '97', change_percent: '-3' }] } } })
    expect(wrapper.text()).toContain('Fall ≈ 3.00% · ≤ 97 USDC')
    await wrapper.setProps({ fresh: false })
    expect(wrapper.text()).toContain('Status needs refresh')
    expect(wrapper.text()).not.toContain('97 USDC')
  })

  it('hides stale price targets when paused or when their reason no longer matches', async () => {
    const wrapper = mount(AccumulationOrderStatus, { props: { status: { ...status, explicitly_paused: true }, fresh: true } })
    expect(wrapper.text()).not.toContain('98 USDC')
    await wrapper.setProps({ status: { ...status, runtime_wait_reason: 'WAIT_BUDGET' } })
    expect(wrapper.text()).toContain('Waiting for available budget')
    expect(wrapper.text()).not.toContain('98 USDC')
  })
})
