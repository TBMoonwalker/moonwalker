import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AccumulationOutlook from '../src/components/AccumulationOutlook.vue'
import { accumulationOutlook } from '../src/helpers/accumulationPresentation'
import type { AccumulationDetail } from '../src/types/accumulation'

function row(overrides: Partial<AccumulationDetail> = {}): AccumulationDetail {
  return {
    activation_id: 'entry', symbol: 'BTC/USDC', state: 'enabled', explicitly_paused: false,
    revision: 1, reason: null, runtime_wait_reason: null, observations_initialized: true,
    strategy_version_id: 7, strategy_slug: 'accumulation_variant_dip_atr', strategy_version: 1,
    holding_integrity: 'unlinked', holding: null, entry: null, operations: [], older_operations_available: false,
    ...overrides,
  }
}

describe('accumulation operator outlook', () => {
  it('makes validation a next action without promising an immediate purchase', () => {
    const outlook = accumulationOutlook(row({ state: 'validating', observations_initialized: false, explicitly_paused: true, reason: 'validation_required' }), true)
    expect(outlook.title).toBe('Entry check incomplete')
    expect(outlook.action).toBe('retry_entry')
    expect(outlook.next).toContain('If it passes')
    expect(outlook.description).toContain('automatic entry check has not completed')
  })

  it.each([
    [{ account_matches: false }, 'Account ownership needs review'],
    [{ inventory_restore_required: true }, 'Inventory needs repair'],
    [{ quarantined_orders: [{ placement_operation_id: 'order', side: 'buy', has_lookup_identity: true }] }, 'Recorded work needs review'],
  ] as const)('puts repair ahead of an entry or resume suggestion', (overrides, title) => {
    const outlook = accumulationOutlook(row({ state: 'paused', explicitly_paused: true, ...overrides }), true)
    expect(outlook.title).toBe(title)
    expect(outlook.action).toBeUndefined()
  })

  it('does not show an enabled outlook over a stale snapshot or pending request', () => {
    expect(accumulationOutlook(row(), false).title).toBe('Status needs refresh')
    expect(accumulationOutlook(row({ operations: [{ operation_id: 'pause', action: 'pause', status: 'pending', result_state: 'enabled', result_revision: 1, reason: null }] }), true).title).toBe('Request is being processed')
  })

  it('keeps closing distinct from waiting for a buy minimum', () => {
    const outlook = accumulationOutlook(row({ state: 'closing', runtime_wait_reason: 'WAIT_MINIMUM' }), true)
    expect(outlook.title).toBe('Closing · new buys blocked')
    expect(outlook.next).toContain('previous orders have settled')
    expect(outlook.action).toBeUndefined()
  })

  it('shows runtime wait reasons ahead of old lifecycle reasons', () => {
    expect(accumulationOutlook(row({ reason: 'entry_validated', runtime_wait_reason: 'WAIT_DEPTH' }), true).title).toBe('Waiting for a deeper dip')
  })

  it('uses a cautious fallback for new or unrecognized runtime reasons', () => {
    const outlook = accumulationOutlook(row({ runtime_wait_reason: 'WAIT_FUTURE_CHECK' }), true)
    expect(outlook.title).toBe('Trading check pending')
    expect(outlook.description).toContain('not confirmed')
    expect(outlook.action).toBeUndefined()
  })

  it('limits expandable help to the current operational step', () => {
    const entry = mount(AccumulationOutlook, { props: { detail: row({ state: 'validating', observations_initialized: false }), fresh: true } })
    expect(entry.find('summary').text()).toBe('Entry check details')
    expect(entry.text()).not.toContain('Deeper dips')
    expect(entry.text()).not.toContain('Sales require')
    expect(entry.text()).not.toContain('ASAP registers')
    const watch = mount(AccumulationOutlook, { props: { detail: row({ runtime_wait_reason: 'WAIT_DEPTH' }), fresh: true } })
    expect(watch.find('summary').text()).toBe('Buying rules')
    expect(watch.text()).not.toContain('The first check runs automatically')
    expect(watch.find('details').attributes('open')).toBeUndefined()
  })

  it('keeps an expanded explanation mounted across status polling', async () => {
    const wrapper = mount(AccumulationOutlook, { props: { detail: row({ state: 'validating', observations_initialized: false }), fresh: true } })
    const explanation = wrapper.find('details').element
    explanation.setAttribute('open', '')
    await wrapper.setProps({ fresh: false })
    await wrapper.setProps({ fresh: true })
    expect(wrapper.find('details').element).toBe(explanation)
    expect(wrapper.find('details').attributes('open')).toBe('')
  })

  it.each([
    { state: 'paused', explicitly_paused: true },
    { state: 'closing', runtime_wait_reason: 'WAIT_MINIMUM' },
    { state: 'stopped' },
    { state: 'enabled', account_matches: false },
    { state: 'enabled', runtime_wait_reason: 'WAIT_GLOBAL_PAUSE' },
  ])('hides entry and buying explanations during a different step: %o', overrides => {
    const wrapper = mount(AccumulationOutlook, { props: { detail: row(overrides), fresh: true } })
    expect(wrapper.find('details').exists()).toBe(false)
  })
})
