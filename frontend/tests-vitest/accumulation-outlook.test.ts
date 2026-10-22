import { describe, expect, it } from 'vitest'
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
    expect(outlook.title).toBe('Entry needs validation')
    expect(outlook.action).toBe('retry_entry')
    expect(outlook.next).toContain('If it passes')
    expect(outlook.description).toContain('Buying has not started')
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
})
