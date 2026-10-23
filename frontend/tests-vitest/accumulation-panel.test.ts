import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AccumulationOrderTimeline from '../src/components/AccumulationOrderTimeline.vue'
import AccumulationPanel from '../src/components/AccumulationPanel.vue'
import AccumulationTradeStatus from '../src/components/AccumulationTradeStatus.vue'
import AccumulationStrategyAssignment from '../src/components/config/AccumulationStrategyAssignment.vue'
import { NSelect } from 'naive-ui/es/select'
import { useAccumulationPanel } from '../src/composables/useAccumulationPanel'
import { accumulationActions } from '../src/helpers/accumulation'
import type { AccumulationDetail, AccumulationCommand } from '../src/types/accumulation'

const api = vi.hoisted(() => ({ fetchAccumulationPage: vi.fn(), fetchAccumulationDetail: vi.fn(), fetchAccumulationStrategies: vi.fn(), sendAccumulationCommand: vi.fn(), accumulationErrorStatus: vi.fn() }))
vi.mock('../src/api/accumulation', () => api)
const routing = vi.hoisted(() => ({ route: null as any }))
vi.mock('vue-router', async importOriginal => ({ ...await importOriginal<typeof import('vue-router')>(), useRoute: () => routing.route }))

const live = vi.hoisted(() => ({ options: null as any, socket: {} as any }))
vi.mock('@vueuse/core', async importOriginal => {
  const original = await importOriginal<typeof import('@vueuse/core')>()
  const { ref, shallowRef } = await import('vue')
  return { ...original, useWebSocket: (_url: unknown, options: unknown) => {
    live.options = options
    live.socket = {}
    return { status: ref('OPEN'), ws: shallowRef(live.socket), open: vi.fn(), close: vi.fn() }
  } }
})

function snapshot(overrides: Partial<AccumulationDetail> = {}): AccumulationDetail {
  return {
    activation_id: 'activation-1', symbol: 'BTC/USDC', state: 'enabled', explicitly_paused: false,
    revision: 12, reason: null, runtime_wait_reason: null, observations_initialized: true,
    strategy_version_id: 5, strategy_slug: 'accumulation_dip_v1', strategy_version: 2,
    holding_integrity: 'owned',
    holding: { net_quantity: '0.100000000000000001', remaining_cost: null, contributed_quote: '12.000000000000000001', disposal_proceeds: '0', basis_provenance: 'unknown', execution_history_complete: false, fees: null },
    entry: null, operations: [], older_operations_available: false, ...overrides,
  }
}

function operation(command: AccumulationCommand, status = 'pending') {
  return { operation: { operation_id: command.operation_id, activation_id: 'activation-1', status, state: 'closing', revision: 13, reason: null } }
}

function harness() {
  let panel!: ReturnType<typeof useAccumulationPanel>
  const wrapper = mount(defineComponent({ setup() { panel = useAccumulationPanel(); return () => null } }))
  return { wrapper, get panel() { return panel } }
}

async function click(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll('button').find(item => item.text() === text)
  expect(button, `Missing ${text}`).toBeDefined()
  await button!.trigger('click')
  await flushPromises()
}

describe('accumulation controls', () => {
  it('reviews dust quantity and cost before archiving with the current close identity', async () => {
    const row = snapshot({ state: 'closing', runtime_wait_reason: 'WAIT_REMAINDER',
      holding: { ...snapshot().holding!, net_quantity: '0.0000048', remaining_cost: '0.390128303007857464591', execution_history_complete: true, fees: { totals: {}, pending_reports: 0 } },
      operations: [{ operation_id: 'close-1', action: 'close', status: 'pending', result_state: 'closing', result_revision: 12, reason: null }] })
    api.fetchAccumulationDetail.mockResolvedValue(row)
    const wrapper = mount(AccumulationPanel)
    await flushPromises()
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    await click(wrapper, 'Archive remaining dust')
    expect(wrapper.text()).toContain('0.0000048')
    expect(wrapper.text()).toContain('0.390128303007857464591')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    await click(wrapper, 'Confirm archive remaining dust')
    expect(api.sendAccumulationCommand.mock.calls[0][0]).toMatchObject({
      action: 'archive_dust', previous_operation_id: 'close-1', expected_revision: 12,
    })
  })


  it('reviews exact inventory corrections and retains the same declaration after a lost response', async () => {
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ state: 'paused', explicitly_paused: true }))
    const { panel } = harness()
    await flushPromises()
    panel.prepare('adjust_inventory')
    expect(panel.draft.value).toBeNull()
    panel.adjustmentQuantity.value = '0.000000000000000001'
    panel.adjustmentCost.value = '0.000000000000000009'
    panel.adjustmentNote.value = 'Correct imported net coins'
    panel.prepare('adjust_inventory')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    expect(panel.draft.value).toMatchObject({ direction: 'add', quantity: '0.000000000000000001', acquisition_cost: '0.000000000000000009', note: 'Correct imported net coins', expected_revision: 12 })
    api.sendAccumulationCommand.mockRejectedValueOnce(new Error('Lost response'))
    await panel.submit()
    const first = { ...api.sendAccumulationCommand.mock.calls[0][0] }
    panel.adjustmentQuantity.value = '99'
    await panel.submit()
    expect(api.sendAccumulationCommand.mock.calls[1][0]).toEqual(first)
    expect(panel.uncertain.value).toBeNull()
  })

  it('offers corrections only for explicitly paused, owned inventory', () => {
    expect(accumulationActions(snapshot())).not.toContain('adjust_inventory')
    expect(accumulationActions(snapshot({ state: 'closing', explicitly_paused: true }))).not.toContain('adjust_inventory')
    expect(accumulationActions(snapshot({ state: 'paused', explicitly_paused: true }))).toContain('adjust_inventory')
    expect(accumulationActions(snapshot({ state: 'paused', explicitly_paused: true, account_matches: false }))).not.toContain('adjust_inventory')
  })

  beforeEach(() => {
    routing.route = reactive({ query: {} as Record<string, string> })
    vi.clearAllMocks()
    api.fetchAccumulationPage.mockResolvedValue({ activations: [snapshot()], next_after: null })
    api.fetchAccumulationDetail.mockResolvedValue(snapshot())
    api.fetchAccumulationStrategies.mockResolvedValue({ versions: [{ id: 17, name: 'Patient dip', version: 1, slug: 'patient', parameters: { timeframe: '4h' } }], next_after_id: null })
    api.accumulationErrorStatus.mockImplementation(error => error?.status)
    api.sendAccumulationCommand.mockImplementation(command => Promise.resolve(operation(command)))
  })

  it('keeps the panel hidden when the release gate is disabled', async () => {
    api.fetchAccumulationPage.mockRejectedValue({ status: 503 })
    const wrapper = mount(AccumulationPanel)
    await flushPromises()
    expect(wrapper.find('section').exists()).toBe(false)
    expect(api.fetchAccumulationDetail).not.toHaveBeenCalled()
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
  })

  it('keeps holding summaries out of history and reviews a close before journaling', async () => {
    const wrapper = mount(AccumulationPanel)
    await flushPromises()
    expect(wrapper.text()).not.toContain('Current holding')
    expect(wrapper.text()).not.toContain('Managed quantity')
    expect(wrapper.text()).toContain('Fee or execution history is incomplete')
    await click(wrapper, 'Sell and close')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Any unsellable remainder stays recorded')
    await click(wrapper, 'Confirm close holding')
    expect(api.sendAccumulationCommand).toHaveBeenCalledTimes(1)
    expect(api.sendAccumulationCommand.mock.calls[0][0]).toMatchObject({ action: 'close', expected_revision: 12, symbol: 'BTC/USDC' })
    expect(wrapper.text()).toContain('Work is pending')
    expect(wrapper.text()).not.toContain('Sold ')
  })

  it('retains the exact request across a lost response and component remount', async () => {
    const first = harness()
    await flushPromises()
    api.sendAccumulationCommand.mockRejectedValueOnce(new Error('Connection lost'))
    first.panel.quantity.value = '0.000000000000000001'
    first.panel.prepare('sell_partial')
    await first.panel.submit()
    const original = api.sendAccumulationCommand.mock.calls[0][0]
    expect(first.panel.uncertain.value).toEqual(original)
    first.wrapper.unmount()
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ revision: 13, state: 'paused' }))
    const second = harness()
    await flushPromises()
    second.panel.prepare('close')
    expect(second.panel.draft.value).toBeNull()
    await second.panel.submit()
    expect(api.sendAccumulationCommand.mock.calls[1][0]).toEqual(original)
    expect(second.panel.uncertain.value).toBeNull()
    expect(window.sessionStorage.length).toBe(0)
  })

  it('refreshes a conflict without resubmitting or reusing its stale snapshot', async () => {
    const { panel } = harness()
    await flushPromises()
    panel.prepare('close')
    api.sendAccumulationCommand.mockRejectedValueOnce({ status: 409, message: 'Stale revision' })
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ state: 'paused', revision: 14 }))
    await panel.submit()
    expect(api.sendAccumulationCommand).toHaveBeenCalledTimes(1)
    expect(panel.uncertain.value).toBeNull()
    expect(panel.detail.value?.revision).toBe(14)
    expect(panel.draft.value).toBeNull()
  })

  it('ignores an old symbol response after selecting another holding', async () => {
    const { panel } = harness()
    await flushPromises()
    let resolveOld!: (value: AccumulationDetail) => void
    api.fetchAccumulationDetail.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const old = panel.refreshDetail()
    api.fetchAccumulationDetail.mockResolvedValueOnce(snapshot({ symbol: 'ETH/USDC' }))
    await panel.selectSymbol('ETH/USDC')
    resolveOld(snapshot())
    await old
    expect(panel.detail.value?.symbol).toBe('ETH/USDC')
  })

  it('blocks new commands after failed refresh and when a reviewed revision changes', async () => {
    const { panel } = harness()
    await flushPromises()
    panel.prepare('close')
    api.fetchAccumulationDetail.mockResolvedValueOnce(snapshot({ revision: 14 }))
    await panel.refreshDetail()
    await panel.submit()
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    panel.draft.value = null
    api.fetchAccumulationDetail.mockRejectedValueOnce(new Error('Offline'))
    await panel.refreshDetail()
    panel.prepare('pause')
    expect(panel.draft.value).toBeNull()
  })

  it('stages corrected CSV against the displayed predecessor without enabling it', async () => {
    const entry = { operation_id: 'entry-1', action: 'activate', status: 'pending', result_state: 'validating', result_revision: 12, reason: 'validation_required', source: 'csv' as const, declaration_invalid: false, declaration: { net_quantity: '1', acquisition_cost: '10', row_count: 1, historical_fees_known: false } }
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ state: 'validating', observations_initialized: false, holding: null, holding_integrity: 'unlinked', entry }))
    const { panel } = harness()
    await flushPromises()
    panel.csv.value = '2026-10-01;BTC/USDC;12;0.2'
    panel.prepare('correct_import')
    await panel.submit()
    expect(api.sendAccumulationCommand.mock.calls[0][0]).toMatchObject({ action: 'correct_import', previous_operation_id: 'entry-1', csv_content: panel.csv.value, expected_revision: 12 })
    expect(api.sendAccumulationCommand).toHaveBeenCalledTimes(1)
  })

  it('shows retained dust with only the explicit remaining-sale retry', async () => {
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ state: 'closing', runtime_wait_reason: 'WAIT_MINIMUM', operations: [{ operation_id: 'close-1', action: 'close', status: 'pending', result_state: 'closing', result_revision: 12, reason: null }] }))
    const wrapper = mount(AccumulationPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('including dust below the exchange minimum')
    await click(wrapper, 'Retry remaining sale')
    await click(wrapper, 'Confirm retry remaining sale')
    expect(api.sendAccumulationCommand.mock.calls[0][0]).toMatchObject({ action: 'retry_close', previous_operation_id: 'close-1' })
    expect(wrapper.findAll('button').some(button => button.text() === 'Resume accumulation')).toBe(false)
  })

  it('does not offer reactivation of abandoned or restored quarantined entries', () => {
    expect(accumulationActions(snapshot({ state: 'stopped', observations_initialized: false, holding: null }))).toEqual([])
    expect(accumulationActions(snapshot({ holding_integrity: 'invalid' }))).toEqual([])
    expect(accumulationActions(snapshot({ state: 'validating', observations_initialized: false, entry: { operation_id: 'restored', action: 'activate', status: 'quarantined', result_state: 'validating', result_revision: 1, reason: null, source: 'csv', declaration: null, declaration_invalid: false } }))).toEqual([])
  })

  it('reviews the exact compatible strategy version and rejects an unknown selection', async () => {
    const { panel } = harness()
    await flushPromises()
    panel.targetVersion.value = 999
    panel.prepare('switch_strategy')
    expect(panel.draft.value).toBeNull()
    panel.targetVersion.value = 17
    panel.prepare('switch_strategy')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    await panel.submit()
    expect(api.sendAccumulationCommand.mock.calls[0][0]).toMatchObject({ action: 'switch_strategy', target_version_id: 17, expected_revision: 12 })
  })

  it('keeps closed order history without portfolio summaries or invented returns', async () => {
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({
      state: 'stopped', holding: null, holding_integrity: 'unlinked',
      portfolio: { holding_count: 2, unverified_holding_count: 1, valuation_available: false, by_quote: [{ quote: 'USDC', holding_count: 2, known_remaining_cost: '0.300000000000000003', remaining_cost: null, unknown_cost_count: 1 }] },
      orders: [{ checkpoint_id: 5, deal_id: 'closed', side: 'sell', filled_quantity: '0.100000000000000001', quote_cost: '12.000000000000000001', fees: { BNB: '0.000000000000000001' }, fees_complete: true, terminal: true, updated_at: '2026-10-21T10:00:00Z', inventory_at_update: { net_quantity: '0', remaining_cost: null, contributed_quote: null, disposal_proceeds: '12.000000000000000001', fees: {}, pending_fee_reports: 0, basis_provenance: 'unknown' } }],
      operations: [{ operation_id: 'old-entry', action: 'activate', status: 'applied', result_state: 'enabled', result_revision: 1, reason: 'retry_entry' }],
      older_operations_available: true,
      older_orders_available: true,
    }))
    const { panel } = harness()
    await flushPromises()
    const history = mount(AccumulationOrderTimeline, { props: { detail: panel.detail.value } })
    expect(history.text()).toContain('Earlier holding / unlinked manual sale')
    expect(history.text()).toContain('0.100000000000000001')
    expect(history.text()).not.toContain('Recorded fees')
    expect(history.text()).not.toContain('activate')
    expect(history.text()).not.toContain('retry entry')
    expect(history.findAll('details')).toHaveLength(0)
    expect(history.text()).toContain('Order size: 12.000000000000000001 | Amount: 0.100000000000000001 | Price: Unknown')
    expect(history.text()).toContain('Unknown')
    expect(history.text()).toContain('Older executed orders remain recorded')
  })

  it('reviews one restored order and explicitly retries the identical lookup request', async () => {
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ state: 'paused', explicitly_paused: true,
      quarantined_orders: [{ placement_operation_id: 'restored-buy', side: 'buy', has_lookup_identity: true }],
    }))
    api.sendAccumulationCommand.mockImplementation(command => Promise.resolve(operation(command, 'quarantined')))
    const wrapper = mount(AccumulationPanel)
    await flushPromises()
    expect(wrapper.findAll('button').some(button => button.text() === 'Resume accumulation')).toBe(false)
    await click(wrapper, 'Reconcile restored order')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    await click(wrapper, 'Confirm reconcile restored order')
    const request = api.sendAccumulationCommand.mock.calls[0][0]
    expect(request).toMatchObject({ action: 'repair_order', placement_operation_id: 'restored-buy', expected_revision: 12 })
    expect(wrapper.text()).toContain('Terminal order evidence is not available')
    api.sendAccumulationCommand.mockImplementation(command => Promise.resolve(operation(command, 'applied')))
    await click(wrapper, 'Retry same request')
    expect(api.sendAccumulationCommand.mock.calls[1][0]).toEqual(request)
  })

  it('retires only the selected interrupted command after review and keeps buys paused', async () => {
    const interrupted = { operation_id: 'interrupted-switch', action: 'switch_strategy', status: 'quarantined', result_state: 'switching', result_revision: 10, reason: 'restore_validation_required' }
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ state: 'switching', explicitly_paused: true, quarantined_commands: [interrupted] }))
    const wrapper = mount(AccumulationPanel)
    await flushPromises()
    expect(wrapper.findAll('button').some(button => button.text() === 'Resume accumulation')).toBe(false)
    await click(wrapper, 'Retire interrupted command')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Buying stays paused')
    expect(wrapper.text()).toContain('Selected command: switch strategy')
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ state: 'paused', explicitly_paused: true, quarantined_commands: [] }))
    api.sendAccumulationCommand.mockImplementation(command => Promise.resolve(operation(command, 'applied')))
    await click(wrapper, 'Confirm retire interrupted command')
    expect(api.sendAccumulationCommand.mock.calls[0][0]).toMatchObject({ action: 'retire_command', expected_revision: 12, previous_operation_id: 'interrupted-switch' })
    expect(wrapper.text()).toContain('paused')
  })

  it('finds the retired close predecessor outside the recent request list', async () => {
    const previous = { operation_id: 'retired-close', action: 'close', status: 'cancelled', result_state: 'closing', result_revision: 12, reason: 'restore_intent_retired' }
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ state: 'closing', explicitly_paused: true, operations: [], close_predecessor: previous }))
    const { panel } = harness()
    await flushPromises()
    expect(panel.actions.value).toEqual(['retry_close'])
    panel.prepare('retry_close')
    expect(panel.draft.value).toMatchObject({ action: 'retry_close', previous_operation_id: 'retired-close' })
  })

  it('reviews credential rebinding and retains the original request until account proof completes', async () => {
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ account_matches: false }))
    api.sendAccumulationCommand.mockImplementation(command => Promise.resolve(operation(command, 'quarantined')))
    const wrapper = mount(AccumulationPanel)
    await flushPromises()
    await click(wrapper, 'Revalidate rotated API key')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('This does not transfer coins')
    await click(wrapper, 'Confirm revalidate rotated api key')
    const request = api.sendAccumulationCommand.mock.calls[0][0]
    expect(request).toMatchObject({ action: 'rebind_account', expected_revision: 12 })
    expect(request.account_scope).toBeUndefined()
    expect(wrapper.text()).toContain('Account ownership evidence is incomplete')
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ account_matches: true, state: 'paused', explicitly_paused: true }))
    api.sendAccumulationCommand.mockImplementation(command => Promise.resolve(operation(command, 'applied')))
    await click(wrapper, 'Retry same request')
    expect(api.sendAccumulationCommand.mock.calls[1][0]).toEqual(request)
    expect(wrapper.text()).toContain('paused')
  })
  it('requires a typed ownership declaration and retains the request while evidence is incomplete', async () => {
    api.fetchAccumulationDetail.mockResolvedValue(snapshot({ account_matches: false, state: 'paused', explicitly_paused: true }))
    const { panel } = harness()
    await flushPromises()
    panel.prepare('declare_ownership')
    expect(panel.draft.value).toBeNull()
    panel.ownershipConfirmation.value = 'BTC/USDC'
    panel.ownershipNote.value = 'I verified these coins in the configured account'
    panel.prepare('declare_ownership')
    expect(panel.draft.value).toMatchObject({ confirmation: 'BTC/USDC', note: panel.ownershipNote.value, expected_revision: 12 })
    api.sendAccumulationCommand.mockImplementation(command => Promise.resolve(operation(command, 'quarantined')))
    await panel.submit()
    const request = panel.uncertain.value
    expect(request?.action).toBe('declare_ownership')
    panel.ownershipNote.value = 'Changed input must not replace the request'
    api.sendAccumulationCommand.mockImplementation(command => Promise.resolve(operation(command, 'applied')))
    await panel.submit()
    expect(api.sendAccumulationCommand.mock.calls[1][0]).toEqual(request)
    expect(panel.uncertain.value).toBeNull()
  })

  it('offers exact inventory restoration before acknowledgement when ownership is missing', () => {
    expect(accumulationActions(snapshot({ state: 'closing', explicitly_paused: true, holding_integrity: 'unlinked', holding: null, inventory_restore_required: true }))).toEqual(['restore_inventory'])
    expect(accumulationActions(snapshot({ state: 'closing', explicitly_paused: true, settled_commands: [{ operation_id: 'settled-close', action: 'close', status: 'quarantined', result_state: 'closing', result_revision: 12, reason: null }] }))).toEqual(['acknowledge_settlement'])
  })

  it('applies a pushed snapshot and invalidates an older reviewed revision without an HTTP refresh', async () => {
    const { panel } = harness()
    await flushPromises()
    panel.prepare('close')
    const reads = api.fetchAccumulationDetail.mock.calls.length
    const next = snapshot({ revision: 13, state: 'paused', explicitly_paused: true })
    live.options.onMessage(live.socket, { data: JSON.stringify({ type: 'snapshot', page: { activations: [next], next_after: null }, detail: next }) })
    expect(panel.detail.value?.revision).toBe(13)
    expect(panel.draft.value?.expected_revision).toBe(12)
    await panel.submit()
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    expect(api.fetchAccumulationDetail).toHaveBeenCalledTimes(reads)
    live.options.onDisconnected(live.socket)
    expect(panel.fresh.value).toBe(false)
    live.options.onMessage(live.socket, { data: JSON.stringify({ type: 'snapshot', page: { activations: [next], next_after: null }, detail: next }) })
    expect(panel.fresh.value).toBe(true)
  })

  it('does not schedule HTTP status polling', async () => {
    const timer = vi.spyOn(globalThis, 'setInterval')
    const { wrapper } = harness()
    await flushPromises()
    expect(timer).not.toHaveBeenCalled()
    wrapper.unmount()
    timer.mockRestore()
  })

  it('accepts an authoritative restored snapshot and cancels a review when ownership changes', async () => {
    const { panel } = harness()
    await flushPromises()
    panel.prepare('close')
    const restored = snapshot({ revision: 2, state: 'paused', explicitly_paused: true, holding: null })
    live.options.onMessage(live.socket, { data: JSON.stringify({ type: 'snapshot', page: { activations: [restored], next_after: null }, detail: restored }) })
    expect(panel.detail.value?.revision).toBe(2)
    expect(panel.draft.value).toBeNull()
    expect(panel.notice.value).toContain('changed')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
  })

  it('will not confirm a command that is no longer offered by the latest state', async () => {
    const { panel } = harness()
    await flushPromises()
    panel.prepare('close')
    const changed = snapshot({ account_matches: false })
    live.options.onMessage(live.socket, { data: JSON.stringify({ type: 'snapshot', page: { activations: [changed], next_after: null }, detail: changed }) })
    await panel.submit()
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    expect(panel.draft.value).toBeNull()
  })

  it('binds all trade information and recovery controls to their trade symbol', async () => {
    api.fetchAccumulationDetail.mockImplementation((symbol: string) => Promise.resolve(snapshot({ symbol })))
    const wrapper = mount(AccumulationTradeStatus, { props: { symbol: 'ETH/USDC' }, global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(api.fetchAccumulationDetail).toHaveBeenCalledWith('ETH/USDC')
    expect(wrapper.html()).toContain('ETH/USDC')
    expect(wrapper.text()).not.toContain('Manage accumulation')
    expect(wrapper.text()).not.toContain('Inventory and history')
    expect(wrapper.text()).not.toContain('Holding information')
    expect(wrapper.text()).not.toContain('Current holding')
    expect(wrapper.text()).not.toContain('Change strategy')
    expect(wrapper.text()).not.toContain('Use strategy')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    await click(wrapper, 'Sell and close')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    expect(wrapper.html()).toContain('ETH/USDC')
    expect(wrapper.text()).toContain('Confirm close holding')
    const confirm = wrapper.findAll('button').find(button => button.text() === 'Confirm close holding')!
    expect(confirm.attributes('disabled')).toBeUndefined()
    await confirm.trigger('click')
    await flushPromises()
    expect(api.sendAccumulationCommand).toHaveBeenCalledTimes(1)
    expect(api.sendAccumulationCommand.mock.calls[0][0]).toMatchObject({ symbol: 'ETH/USDC', action: 'close', expected_revision: 12 })
    wrapper.unmount()
  })

  it('reveals a partial sale and submits only the exact reviewed quantity', async () => {
    const wrapper = mount(AccumulationTradeStatus, { props: { symbol: 'BTC/USDC' }, global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(wrapper.find('input[inputmode="decimal"]').exists()).toBe(false)
    await click(wrapper, 'Sell part')
    await wrapper.get('input[inputmode="decimal"]').setValue('0.000000000000000001')
    await click(wrapper, 'Review partial sale')
    expect(wrapper.text()).toContain('Quantity: 0.000000000000000001 BTC')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    await click(wrapper, 'Confirm sell part')
    expect(api.sendAccumulationCommand).toHaveBeenCalledTimes(1)
    expect(api.sendAccumulationCommand.mock.calls[0][0]).toMatchObject({ symbol: 'BTC/USDC', quantity: '0.000000000000000001', action: 'sell_partial' })
    wrapper.unmount()
  })

  it('changes a registration strategy only through the configuration control', async () => {
    const utilities = mount(AccumulationPanel)
    await flushPromises()
    expect(utilities.find('#accumulation-strategy').exists()).toBe(false)
    expect(utilities.findAll('button').some(button => button.text() === 'Switch strategy')).toBe(false)
    utilities.unmount()
    const wrapper = mount(AccumulationStrategyAssignment)
    await flushPromises()
    const selector = wrapper.findAllComponents(NSelect).find(select => select.props('options')?.some(option => option.value === 17))!
    expect(selector).toBeDefined()
    selector.vm.$emit('update:value', 17)
    await flushPromises()
    await click(wrapper, 'Review strategy change')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Selected strategy: Patient dip · v1 · 4h')
    await click(wrapper, 'Confirm strategy change')
    expect(api.sendAccumulationCommand.mock.calls[0][0]).toMatchObject({ action: 'switch_strategy', symbol: 'BTC/USDC', target_version_id: 17, expected_revision: 12 })
    wrapper.unmount()
  })

  it('retries an uncertain strategy change only in trade-mode configuration', async () => {
    const stubs = { RouterLink: { template: '<a><slot /></a>' } }
    const first = harness()
    await flushPromises()
    first.panel.targetVersion.value = 17
    first.panel.prepare('switch_strategy')
    api.sendAccumulationCommand.mockRejectedValueOnce(new Error('Lost response'))
    await first.panel.submit()
    const original = api.sendAccumulationCommand.mock.calls[0][0]
    first.wrapper.unmount()
    const utilities = mount(AccumulationPanel, { global: { stubs } })
    const trade = mount(AccumulationTradeStatus, { props: { symbol: 'BTC/USDC' }, global: { stubs } })
    await flushPromises()
    for (const wrapper of [utilities, trade]) {
      expect(wrapper.findAll('button').some(button => button.text() === 'Retry same request')).toBe(false)
      expect(wrapper.text()).toContain('Review strategy request in Configuration')
      wrapper.unmount()
    }
    const settings = mount(AccumulationStrategyAssignment, { global: { stubs } })
    await flushPromises()
    await click(settings, 'Retry same strategy request')
    expect(api.sendAccumulationCommand.mock.calls[1][0]).toEqual(original)
    settings.unmount()
  })

  it('explains why an inline confirmation is blocked after a pushed revision change', async () => {
    const wrapper = mount(AccumulationTradeStatus, { props: { symbol: 'BTC/USDC' }, global: { stubs: { RouterLink: true } } })
    await flushPromises()
    await click(wrapper, 'Sell and close')
    const changed = snapshot({ revision: 13 })
    live.options.onMessage(live.socket, { data: JSON.stringify({ type: 'snapshot', page: { activations: [changed], next_after: null }, detail: changed }) })
    await flushPromises()
    expect(wrapper.text()).toContain('The holding changed. Cancel and review the action again.')
    const confirm = wrapper.findAll('button').find(button => button.text() === 'Confirm close holding')!
    expect(confirm.attributes('disabled')).toBeDefined()
    await confirm.trigger('click')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps the route symbol even outside the first page and follows route changes', async () => {
    routing.route.query.symbol = 'ETH/USDC'
    api.fetchAccumulationDetail.mockImplementation((symbol: string) => Promise.resolve(snapshot({ symbol })))
    const wrapper = mount(AccumulationPanel)
    await flushPromises()
    expect(api.fetchAccumulationDetail).toHaveBeenCalledWith('ETH/USDC')
    expect(wrapper.html()).toContain('ETH/USDC')
    routing.route.query.symbol = 'SOL/USDC'
    await flushPromises()
    expect(api.fetchAccumulationDetail).toHaveBeenLastCalledWith('SOL/USDC')
    expect(wrapper.html()).toContain('SOL/USDC')
    wrapper.unmount()
  })

  it('reports a missing route symbol without substituting the first registration', async () => {
    routing.route.query.symbol = 'ETH/USDC'
    api.fetchAccumulationDetail.mockRejectedValue(new Error('Not found'))
    const wrapper = mount(AccumulationPanel)
    await flushPromises()
    expect(api.fetchAccumulationDetail.mock.calls.every(([symbol]) => symbol === 'ETH/USDC')).toBe(true)
    expect(wrapper.text()).toContain('ETH/USDC:')
    expect(wrapper.text()).not.toContain('Managed quantity')
    wrapper.unmount()
  })

  it('preserves a different symbol’s uncertain request while following a recovery route', async () => {
    const first = harness()
    await flushPromises()
    api.sendAccumulationCommand.mockRejectedValueOnce(new Error('Lost response'))
    first.panel.prepare('close')
    await first.panel.submit()
    const original = api.sendAccumulationCommand.mock.calls[0][0]
    first.wrapper.unmount()
    routing.route.query.symbol = 'ETH/USDC'
    api.fetchAccumulationDetail.mockImplementation((symbol: string) => Promise.resolve(snapshot({ symbol })))
    const wrapper = mount(AccumulationPanel, { global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('Resolve the pending request for BTC/USDC')
    expect(api.sendAccumulationCommand).toHaveBeenCalledTimes(1)
    routing.route.query.symbol = 'BTC/USDC'
    await flushPromises()
    await click(wrapper, 'Retry same request')
    expect(api.sendAccumulationCommand.mock.calls[1][0]).toEqual(original)
    wrapper.unmount()
  })

  it('reviews a row action once and never reopens it after a later status update', async () => {
    const wrapper = mount(AccumulationTradeStatus, { props: { symbol: 'BTC/USDC', intent: { action: 'pause', id: 1 } }, global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('Confirm pause accumulation')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    await click(wrapper, 'Cancel')
    const changed = snapshot({ revision: 13 })
    live.options.onMessage(live.socket, { data: JSON.stringify({ type: 'snapshot', page: { activations: [changed], next_after: null }, detail: changed }) })
    await flushPromises()
    expect(wrapper.text()).not.toContain('Confirm pause accumulation')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not duplicate row actions or strategy testing in expanded trade information', async () => {
    const wrapper = mount(AccumulationTradeStatus, { props: { symbol: 'BTC/USDC', hideOutlook: true, intent: { action: 'pause', id: 1 } }, global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('Confirm pause accumulation')
    await click(wrapper, 'Cancel')
    for (const label of ['Sell and close', 'Pause accumulation', 'Sell part']) {
      expect(wrapper.findAll('button').some(button => button.text() === label)).toBe(false)
    }
    expect(wrapper.text()).not.toContain('Historical strategy comparison')
    expect(api.sendAccumulationCommand).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('focuses the review heading and restores the initiating button on cancel', async () => {
    const wrapper = mount(AccumulationTradeStatus, { props: { symbol: 'BTC/USDC' }, attachTo: document.body, global: { stubs: { RouterLink: true } } })
    await flushPromises()
    const button = wrapper.findAll('button').find(button => button.text() === 'Sell and close')!
    await button.trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get('h4').element)
    await click(wrapper, 'Cancel')
    expect(document.activeElement).toBe(button.element)
    wrapper.unmount()
  })

})
