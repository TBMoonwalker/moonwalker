import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AccumulationOrderStatus from '../src/components/AccumulationOrderStatus.vue'
import AccumulationOutlook from '../src/components/AccumulationOutlook.vue'
import { accumulationOutlook, accumulationPendingStatus } from '../src/helpers/accumulationPresentation'
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
  it('uses each pending summary’s real wait without inventing detail evidence', () => {
    expect(accumulationPendingStatus(row({ runtime_wait_reason: 'WAIT_BUDGET' }), true)).toBe('Waiting for available budget')
    expect(accumulationPendingStatus(row({ runtime_wait_reason: 'WAIT_GLOBAL_PAUSE' }), true)).toBe('Moonwalker is paused')
    expect(accumulationPendingStatus(row({ runtime_wait_reason: 'WAIT_DATA' }), true)).toBe('Waiting for exchange data')
    expect(accumulationPendingStatus(row(), false)).toBe('Status needs refresh')
    expect(accumulationPendingStatus(row(), true)).toBe('Waiting for exchange update')
    expect(accumulationPendingStatus(row({ state: 'paused', explicitly_paused: true, runtime_wait_reason: 'WAIT_DEPTH' }), true)).toBe('Accumulation paused')
  })
  it('makes validation a next action without promising an immediate purchase', () => {
    const outlook = accumulationOutlook(row({ state: 'validating', observations_initialized: false, explicitly_paused: true, reason: 'validation_required' }), true)
    expect(outlook.title).toBe('Entry check incomplete')
    expect(outlook.action).toBe('retry_entry')
    expect(outlook.next).toContain('Retry the failed exchange check')
    expect(outlook.description).toContain('automatic entry check has not completed')
  })

  it.each([
    [{ account_matches: false }, 'Account ownership needs review'],
    [{ inventory_restore_required: true }, 'Inventory needs repair'],
    [{ quarantined_orders: [{ placement_operation_id: 'order', side: 'buy', has_lookup_identity: true }] }, 'Recorded work needs review'],
  ] satisfies Array<[Partial<AccumulationDetail>, string]>)('puts repair ahead of an entry or resume suggestion', (overrides, title) => {
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

  it('explains a consumed buy signal as a candle wait in the table and trade details', () => {
    const detail = row({ runtime_wait_reason: 'WAIT_CONSUMED' })
    const table = mount(AccumulationOrderStatus, { props: { status: detail, fresh: true } })
    expect(table.text()).toContain('Waiting for the next candle')
    expect(table.text()).not.toContain('Trading check pending')
    const card = mount(AccumulationOutlook, { props: { detail, fresh: true } })
    expect(card.text()).toContain('This candle’s buy has filled.')
    expect(card.text()).toContain('after the next candle closes')
    expect(card.text()).not.toContain('A buy is not confirmed')
    expect(card.find('.wait-levels').exists()).toBe(false)
    expect(accumulationOutlook(detail, true).action).toBeUndefined()
    expect(accumulationPendingStatus(detail, false)).toBe('Status needs refresh')
  })

  it('uses a cautious fallback for new or unrecognized runtime reasons', () => {
    const outlook = accumulationOutlook(row({ runtime_wait_reason: 'WAIT_FUTURE_CHECK' }), true)
    expect(outlook.title).toBe('Trading check pending')
    expect(outlook.description).toContain('not confirmed')
    expect(outlook.action).toBeUndefined()
  })

  it('shows only the unmet entry threshold and its percentage', () => {
    const wrapper = mount(AccumulationOutlook, { props: { detail: row({ runtime_wait_reason: 'WAIT_DEPTH', wait_condition: {
      reason: 'WAIT_DEPTH', timeframe: '1h', observed_close_ms: 1000, observed_price: '100', next_close_ms: 3601000,
      levels: [{ kind: 'depth', direction: 'at_or_below', target_price: '98', change_percent: '-2' }],
    } }), fresh: true } })
    expect(wrapper.text()).toContain('Waiting for entry')
    expect(wrapper.text()).toContain('2.00% fall')
    expect(wrapper.text()).toContain('98 USDC')
    expect(wrapper.text()).not.toContain('Buying rules')
    expect(wrapper.text()).not.toContain('ASAP')
    expect(wrapper.find('details').exists()).toBe(false)
  })

  it('separates recovery readiness from the next buy target in the card and table', () => {
    const detail = row({ runtime_wait_reason: 'WAIT_REARM', wait_condition: {
      reason: 'WAIT_REARM', timeframe: '1h', observed_close_ms: 1000, observed_price: '81580', next_close_ms: 3601000,
      levels: [
        { kind: 'further_decline', direction: 'at_or_below', target_price: '81089.84863', change_percent: '-0.60' },
        { kind: 'recovery_then_correction', direction: 'at_or_above', target_price: '81872.21137', change_percent: '0.36' },
      ],
    } })
    const wrapper = mount(AccumulationOutlook, { props: { detail, fresh: true } })
    const buys = wrapper.find('[aria-label="Current buy conditions"]')
    expect(buys.text()).toContain('0.60% fall')
    expect(buys.text()).not.toContain('rise')
    const recovery = wrapper.find('.recovery-condition')
    expect(recovery.text()).toContain('Recovery needed before another dip buy')
    expect(recovery.text()).toContain('0.36% rise')
    expect(recovery.text()).toContain('No buy on this rise. A fresh correction must follow.')
    expect(wrapper.find('.wait-or').exists()).toBe(false)
    const table = mount(AccumulationOrderStatus, { props: { status: detail, fresh: true } })
    expect(table.text()).toContain('Recovery reset: Rise ≈ 0.36%')
    expect(table.text()).toContain('no buy; correction required')
  })

  it('explains the live baseline wait and next close without inventing price targets', () => {
    const detail = row({ runtime_wait_reason: 'WAIT_BASELINE', wait_condition: {
      reason: 'WAIT_BASELINE', timeframe: '1h', observed_close_ms: 1792753200000,
      observed_price: '81596.7', next_close_ms: 1792756800000, levels: [],
    } })
    const table = mount(AccumulationOrderStatus, { props: { status: detail, fresh: true } })
    expect(table.text()).toContain('Waiting for the next 1h close')
    expect(table.text()).toContain('Next close: 2026-10-23 12:00 UTC')
    expect(table.text()).not.toContain('Trading check pending')
    const card = mount(AccumulationOutlook, { props: { detail, fresh: true } })
    expect(card.text()).toContain('Waiting for the next 1h close')
    expect(card.text()).toContain('Waiting for the next completed candle to evaluate a new buy signal;')
    expect(card.text()).toContain('Next close: 2026-10-23 12:00 UTC')
    expect(card.find('.wait-levels').exists()).toBe(false)
    const stale = mount(AccumulationOrderStatus, { props: { status: detail, fresh: false } })
    expect(stale.text()).not.toContain('Next close:')
    expect(stale.text()).toContain('Status needs refresh')
  })

  it('explains the actual four-hour baseline without promising a price trigger', () => {
    const detail = row({ runtime_wait_reason: 'WAIT_BASELINE', wait_condition: {
      reason: 'WAIT_BASELINE', timeframe: '4h', observed_close_ms: 1792900800000,
      observed_price: '80772.18', next_close_ms: 1792915200000, levels: [],
    } })
    const table = mount(AccumulationOrderStatus, { props: { status: detail, fresh: true } })
    expect(table.text()).toContain('Waiting for the next 4h close')
    expect(table.text()).toContain('Next close: 2026-10-25 08:00 UTC')
    const card = mount(AccumulationOutlook, { props: { detail, fresh: true } })
    expect(card.text()).toContain('No price target yet')
    expect(card.text()).toContain('a buy is not guaranteed')
    expect(card.find('.wait-levels').exists()).toBe(false)
  })

  it('keeps an unmet strategy condition distinct from waiting for an open candle', () => {
    const detail = row({ runtime_wait_reason: 'WAIT_CONDITIONS', wait_condition: {
      reason: 'WAIT_CONDITIONS', timeframe: '4h', observed_close_ms: 1792900800000,
      observed_price: '80772.18', next_close_ms: 1792915200000, levels: [],
    } })
    const card = mount(AccumulationOutlook, { props: { detail, fresh: true } })
    expect(card.find('h3').text()).toBe('Waiting for strategy conditions')
    expect(card.text()).toContain('buy conditions have not matched')
    expect(card.text()).not.toContain('No price target yet')
    expect(card.text()).toContain('Next close:')
  })

  it('shows condition values and alternatives only for fresh evidence', () => {
    const detail = row({ runtime_wait_reason: 'WAIT_CONDITIONS', wait_condition: {
      reason: 'WAIT_CONDITIONS', timeframe: '4h', observed_close_ms: 1000,
      observed_price: '100', next_close_ms: 14401000, levels: [],
      strategy_conditions: { label: 'Buy conditions', kind: 'all', matched: false, children: [
        { label: 'Market regime', kind: 'any', matched: true, children: [
          { label: 'Downtrend', kind: 'comparison', matched: true, comparison: 'less_than', value1: { label: 'Slope', value: -0.4 }, value2: { label: 'Threshold', value: -0.1 } },
          { label: 'Sideways', kind: 'comparison', matched: false, comparison: 'less_than', value1: { label: 'ADX', value: 34 }, value2: { label: 'Threshold', value: 20 } },
        ] },
        { label: 'Discount', kind: 'comparison', matched: false, comparison: 'greater_or_equal', value1: { label: 'EMA discount / ATR', value: 0.9777 }, value2: { label: 'Threshold', value: 1 } },
      ] },
    } })
    const card = mount(AccumulationOutlook, { props: { detail, fresh: true } })
    expect(card.text()).toContain('At least one required')
    expect(card.text()).toContain('EMA discount / ATR: 0.9777 ≥ Threshold: 1')
    expect(card.text()).toContain('Not met')
    expect(card.text()).toContain('does not guarantee a buy')
    const stale = mount(AccumulationOutlook, { props: { detail, fresh: false } })
    expect(stale.text()).not.toContain('EMA discount / ATR')
  })

  it('does not show cached price levels when the snapshot is stale', () => {
    const wrapper = mount(AccumulationOutlook, { props: { detail: row({ runtime_wait_reason: 'WAIT_DEPTH', wait_condition: {
      reason: 'WAIT_DEPTH', timeframe: '1h', observed_close_ms: 1000, observed_price: '100', next_close_ms: 3601000,
      levels: [{ kind: 'depth', direction: 'at_or_below', target_price: '98', change_percent: '-2' }],
    } }), fresh: false } })
    expect(wrapper.text()).toContain('Status needs refresh')
    expect(wrapper.text()).not.toContain('2.00%')
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

it('shows a labelled baseline preview in the trade card and order status without declaring a buy', () => {
  const detail = row({ runtime_wait_reason: 'WAIT_BASELINE', wait_condition: {
    reason: 'WAIT_BASELINE', timeframe: '4h', observed_close_ms: 1792915200000,
    observed_price: '80593.6', next_close_ms: 1792929600000, levels: [],
    indicative: { level: { kind: 'dip', direction: 'at_or_below', target_price: '78981.728', change_percent: '-2' }, conditions_match: false },
  } })
  const card = mount(AccumulationOutlook, { props: { detail, fresh: true } })
  expect(card.find('h3').text()).toBe('Waiting for the next 4h close')
  const preview = card.get('[aria-label="Indicative buy condition"]')
  expect(preview.text()).toContain('2.00% fall')
  expect(preview.text()).toContain('78,981.728 USDC')
  expect(card.text()).toContain('Strategy filters: not met')
  expect(card.text()).toContain('Rechecked at the next close; not a buy signal.')
  expect(card.text()).toContain('Next close: 2026-10-25 12:00 UTC')
  expect(card.text()).not.toContain('No price target yet')
  const table = mount(AccumulationOrderStatus, { props: { status: detail, fresh: true } })
  expect(table.text()).toContain('Indicative: Fall ≈ 2.00%')
  expect(table.text()).toContain('Next close:')
  for (const fresh of [false, true]) {
    const hidden = mount(AccumulationOutlook, { props: { detail: fresh ? { ...detail, explicitly_paused: true } : detail, fresh } })
    expect(hidden.find('[aria-label="Indicative buy condition"]').exists()).toBe(false)
  }
})

it.each(['NaN', '-1', '0'])('hides malformed indicative prices (%s) while preserving the candle wait', target => {
  const detail = row({ runtime_wait_reason: 'WAIT_BASELINE', wait_condition: {
    reason: 'WAIT_BASELINE', timeframe: '4h', observed_close_ms: 1000,
    observed_price: '100', next_close_ms: 14401000, levels: [],
    indicative: { level: { kind: 'dip', direction: 'below', target_price: target, change_percent: '-1' }, conditions_match: true },
  } })
  const card = mount(AccumulationOutlook, { props: { detail, fresh: true } })
  expect(card.find('[aria-label="Indicative buy condition"]').exists()).toBe(false)
  expect(card.text()).toContain('Waiting for the next 4h close')
  const table = mount(AccumulationOrderStatus, { props: { status: detail, fresh: true } })
  expect(table.text()).not.toContain('Indicative:')
})
