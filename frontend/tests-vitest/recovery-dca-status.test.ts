import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RecoveryDcaStatus from '../src/components/RecoveryDcaStatus.vue'

vi.mock('../src/control-center/configSnapshotStore', () => ({
     useSharedConfigSnapshot: () => ({ snapshot: { value: { mstc: 5, dca: true } } }),
}))

const now = 1_800_000_000_000
function trade(reason = 'waiting_for_atr_spacing', extra = {}) {
    return {
         symbol: 'WIF/USDC', current_price: 0.2435, so_count: 0,
         dca_sizing_mode: 'recovery_target', dca_reference_price: 0.255,
         dca_reference_atr_percent: 3.574182, dca_next_trigger_price: 0.2276575077,
         dca_policy_json: JSON.stringify({ spacing_atr_multiplier: 3, minimum_spacing_percent: 2 }),
         dca_last_decision_json: JSON.stringify({
             reason, evaluated_at_ms: now, current_price: 0.2435,
             reference_price: 0.255, trigger_price: 0.2276575077, ...extra,
          }),
      }
}
describe('recovery DCA status', () => {
    const wrappers: ReturnType<typeof mount>[] = []
    const render = (data = trade()) => {
         const wrapper = mount(RecoveryDcaStatus, { props: { trade: data } })
         wrappers.push(wrapper)
         return wrapper
      }
    beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(now) })
    afterEach(() => { wrappers.forEach(w => w.unmount()); wrappers.length = 0; vi.useRealTimers() })

    it('shows the live distance to the multiplied threshold, with precise small prices', async () => {
         const wrapper = render()
         expect(wrapper.text()).toContain('Another 6.51% drop')
         expect(wrapper.text()).toContain('0.22765751')
         expect(wrapper.text()).toContain('10.72%')
         expect(wrapper.text()).toContain('3 × 3.57%')
         expect(wrapper.text()).toContain('SO 1 / 5')
         await wrapper.setProps({ trade: { ...trade(), current_price: 0.24 } })
         expect(wrapper.text()).toContain('Another 5.14% drop')
      })
    it('does not reuse a spacing wait after the live price crosses the trigger', () => {
         const wrapper = render({ ...trade(), current_price: 0.22 })
         expect(wrapper.text()).toContain('Updating status')
         expect(wrapper.text()).toContain('Price condition met')
         expect(wrapper.text()).not.toContain('Waiting for a lower price')
      })
    it('expires diagnostics even without another websocket update', async () => {
         const wrapper = render()
         await vi.advanceTimersByTimeAsync(95_000)
         expect(wrapper.text()).toContain('Updating status')
      })
    it('stays fresh when the server clock is skewed ahead of the client', () => {
         // A far-future evaluated_at_ms must not read as stale: freshness is
         // anchored to local observation time, so a skewed client still shows live.
         const data = {
             ...trade('waiting_for_atr_spacing'),
             dca_last_decision_json: JSON.stringify({
                  reason: 'waiting_for_atr_spacing',
                  evaluated_at_ms: 9_999_999_999_000,
                  current_price: 0.2435,
                  reference_price: 0.255,
                  trigger_price: 0.2276575077,
             }),
          }
         expect(render(data).text()).toContain('Another 6.51% drop')
         expect(render(data).text()).not.toContain('Updating status')
      })
    it.each(['{broken', '[]', '{}'])('handles missing or malformed diagnostics: %s', raw => {
         expect(render({ ...trade(), dca_last_decision_json: raw }).text()).toContain('Updating status')
      })
    it('never presents shadow calculations as a live buy gate', () => {
         const wrapper = render({ ...trade(), dca_sizing_mode: 'recovery_shadow' })
         expect(wrapper.text()).toContain('Comparison only')
         expect(wrapper.find('dl').exists()).toBe(false)
      })
    it('prioritizes pause and the order limit over persisted waiting reasons', () => {
         expect(render({ ...trade(), automation_paused: true } as ReturnType<typeof trade>).text()).toContain('Automation paused')
         expect(render({ ...trade(), so_count: 5 }).text()).toContain('Safety-order limit reached')
      })
    it('describes missing budgets and fresh strategy waits', () => {
         expect(render(trade('missing_deal_budget')).text()).toContain('blocked by budget')
         expect(render({ ...trade('recovery_signal_unchanged'), current_price: 0.22 }).text()).toContain('Waiting for strategy confirmation')
      })
    it('shows sizing only for the evaluated price, hiding it after price moves', async () => {
         const data = { ...trade('target_recovery', { current_price: 0.22, final_quote: 12, projected_tp_price: 0.25 }), current_price: 0.22 }
         const wrapper = render(data)
         expect(wrapper.text()).toContain('Estimated buy 12.00 USDC')
         await wrapper.setProps({ trade: { ...data, current_price: 0.219 } })
         expect(wrapper.text()).not.toContain('Estimated buy')
         expect(wrapper.text()).toContain('Updating status')
      })
    it('explains a reachable TP without implying a buy', () => {
         const wrapper = render({ ...trade('tp_already_reachable', {
             current_price: 0.22, current_recovery_percent: 8, target_recovery_percent: 12,
          }), current_price: 0.22 })
         expect(wrapper.text()).toContain('No extra buy needed')
         expect(wrapper.text()).toContain('TP needs 8.00% rebound; target allows 12.00%')
      })
    it('rejects a decision from the preceding buy reference', () => {
         expect(render({ ...trade(), dca_reference_price: 0.24 }).text()).toContain('Updating status')
      })
})