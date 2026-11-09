import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PlacementRecoveryCard from '../src/components/PlacementRecoveryCard.vue'

const api = vi.hoisted(() => ({
  fetchPlacementRecoveryIntents: vi.fn(),
  repairPlacementIntent: vi.fn(),
  dismissPlacementIntent: vi.fn(),
  placementRecoveryError: (error: unknown) => {
    if (error && typeof error === 'object' && 'status' in error && 'message' in error) {
      return String((error as { message: unknown }).message)
    }
    return error instanceof Error ? error.message : String(error)
  },
}))
vi.mock('../src/api/placementRecovery', () => api)

function intent(overrides: Record<string, unknown> = {}) {
  return {
    operation_id: 'limit_sell-abc123',
    symbol: 'BTC/USDC',
    action: 'limit_sell',
    side: 'sell',
    order_type: 'limit',
    state: 'quarantined',
    exchange_name: 'binance',
    reason_code: 'reconciliation_account_scope_unverified',
    error_message: 'Order account/environment does not match verified server configuration.',
    exchange_order_id: '7788',
    has_lookup_identity: true,
    limit_price: 0.2,
    amount: 0.6,
    requested_quote: 120,
    route: 'classic_dca',
    created_at: '2026-11-07T12:00:00Z',
    completed_at: null,
    ...overrides,
  }
}

function render() {
  const wrapper = mount(PlacementRecoveryCard)
  return wrapper
}

async function settle() {
  await flushPromises()
}

function axiosError(status: number, message: string) {
  const error = new Error(message)
  return { ...error, status, message }
}

describe('placement recovery card', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('stays hidden when no placement intent blocks startup', async () => {
    api.fetchPlacementRecoveryIntents.mockResolvedValue({ intents: [] })
    const wrapper = render()
    await settle()
    expect(wrapper.find('section').exists()).toBe(false)
    expect(api.fetchPlacementRecoveryIntents).toHaveBeenCalledTimes(1)
  })

  it('surfaces a load failure instead of hiding the gate state', async () => {
    api.fetchPlacementRecoveryIntents.mockRejectedValue(axiosError(500, 'boom'))
    const wrapper = render()
    await settle()
    expect(wrapper.find('section').exists()).toBe(true)
    expect(wrapper.find('[role="alert"]').text()).toContain('Could not load quarantined placements')
    expect(wrapper.text()).toContain('boom')
  })

  it('describes every quarantined intent with its exchange details', async () => {
    api.fetchPlacementRecoveryIntents.mockResolvedValue({
      intents: [
        intent(),
        intent({
          operation_id: 'restored-1',
          symbol: 'SOL/USDC',
          action: 'buy',
          side: 'buy',
          state: 'restored_quarantined',
          reason_code: 'portable_restore_quarantine',
          error_message: null,
          exchange_order_id: null,
          has_lookup_identity: false,
          limit_price: null,
          amount: null,
          requested_quote: null,
        }),
      ],
    })
    const wrapper = render()
    await settle()

    expect(wrapper.text()).toContain('2 placement intents are blocking startup')
    expect(wrapper.text()).toContain('Limit sell 0.6 BTC @ 0.2 USDC')
    expect(wrapper.text()).toContain('Order account/environment does not match verified server configuration.')
    expect(wrapper.text()).toContain('Quarantined')
    expect(wrapper.text()).toContain('Restored quarantined')
    expect(wrapper.text()).toContain('no exchange order identity')
    // Falls back to the reason code when no operator-facing message exists.
    expect(wrapper.text()).toContain('portable_restore_quarantine')
    expect(wrapper.findAll('button').some((button) => button.text() === 'Repair')).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Dismiss…')).toBe(true)
  })

  it('applies a completed repair result and hides the actions for that intent', async () => {
    api.fetchPlacementRecoveryIntents.mockResolvedValue({ intents: [intent(), intent({ operation_id: 'limit_sell-2nd' })] })
    api.repairPlacementIntent.mockResolvedValue({
      operation_id: 'limit_sell-abc123',
      status: 'completed',
      state: 'completed',
      message: 'Exchange fill evidence was applied and the trade finalized.',
    })
    const wrapper = render()
    await settle()
    expect(wrapper.text()).toContain('2 placement intents are blocking startup')

    const repairButtons = wrapper.findAll('button').filter((button) => button.text() === 'Repair')
    await repairButtons[0].trigger('click')
    await settle()

    expect(api.repairPlacementIntent).toHaveBeenCalledWith('limit_sell-abc123')
    expect(wrapper.text()).toContain('Resolved')
    expect(wrapper.text()).toContain('Exchange fill evidence was applied and the trade finalized.')
    expect(wrapper.text()).toContain('1 placement intent is blocking startup')
    // The untouched intent keeps its actions.
    expect(wrapper.findAll('button').filter((button) => button.text() === 'Repair')).toHaveLength(1)
  })

  it('keeps the actions after an inconclusive repair', async () => {
    api.fetchPlacementRecoveryIntents.mockResolvedValue({ intents: [intent()] })
    api.repairPlacementIntent.mockResolvedValue({
      operation_id: 'limit_sell-abc123',
      status: 'unchanged',
      state: 'quarantined',
      message: 'The exchange lookup is inconclusive (no status). Retry when the exchange is reachable.',
    })
    const wrapper = render()
    await settle()

    const repair = wrapper.findAll('button').find((button) => button.text() === 'Repair')!
    await repair.trigger('click')
    await settle()

    expect(wrapper.text()).toContain('Still quarantined')
    expect(wrapper.text()).toContain('The exchange lookup is inconclusive')
    expect(wrapper.text()).toContain('1 placement intent is blocking startup')
    expect(wrapper.findAll('button').some((button) => button.text() === 'Repair')).toBe(true)
  })

  it('shows the backend error when repair is rejected', async () => {
    api.fetchPlacementRecoveryIntents.mockResolvedValue({ intents: [intent()] })
    api.repairPlacementIntent.mockRejectedValue(axiosError(409, 'Placement limit_sell-abc123 is in state completed, not quarantined.'))
    const wrapper = render()
    await settle()

    const repair = wrapper.findAll('button').find((button) => button.text() === 'Repair')!
    await repair.trigger('click')
    await settle()

    expect(wrapper.find('[role="alert"]').text()).toContain('is in state completed, not quarantined')
    expect(wrapper.findAll('button').some((button) => button.text() === 'Repair')).toBe(true)
  })

  it('records a dismissal only with a non-empty note', async () => {
    api.fetchPlacementRecoveryIntents.mockResolvedValue({ intents: [intent()] })
    api.dismissPlacementIntent.mockResolvedValue({
      operation_id: 'limit_sell-abc123',
      status: 'dismissed',
      state: 'rejected',
      message: 'The operator dismissal was recorded; the intent is terminal and no longer blocks startup.',
    })
    const wrapper = render()
    await settle()

    const dismissToggle = wrapper.findAll('button').find((button) => button.text() === 'Dismiss…')!
    await dismissToggle.trigger('click')
    await settle()

    const input = wrapper.find('input.dismiss-input')
    expect(input.exists()).toBe(true)
    let confirm = wrapper.findAll('button').find((button) => button.text() === 'Dismiss intent')!
    expect(confirm.attributes('disabled')).toBeDefined()
    expect(api.dismissPlacementIntent).not.toHaveBeenCalled()

    await input.setValue('Verified manually on the exchange; no open order.')
    await settle()
    confirm = wrapper.findAll('button').find((button) => button.text() === 'Dismiss intent')!
    expect(confirm.attributes('disabled')).toBeUndefined()
    await confirm.trigger('click')
    await settle()

    expect(api.dismissPlacementIntent).toHaveBeenCalledWith(
      'limit_sell-abc123',
      'Verified manually on the exchange; no open order.',
    )
    expect(wrapper.text()).toContain('Dismissed')
    expect(wrapper.text()).toContain('The operator dismissal was recorded')
    expect(wrapper.text()).toContain('0 placement intents are blocking startup')
    expect(wrapper.find('input.dismiss-input').exists()).toBe(false)
  })

  it('follows an inconclusive repair with a dismissal on the same intent', async () => {
    api.fetchPlacementRecoveryIntents.mockResolvedValue({ intents: [intent()] })
    api.repairPlacementIntent.mockResolvedValue({
      operation_id: 'limit_sell-abc123',
      status: 'unchanged',
      state: 'quarantined',
      message: 'The exchange lookup is inconclusive.',
    })
    api.dismissPlacementIntent.mockResolvedValue({
      operation_id: 'limit_sell-abc123',
      status: 'dismissed',
      state: 'rejected',
      message: 'The operator dismissal was recorded.',
    })
    const wrapper = render()
    await settle()

    const repair = wrapper.findAll('button').find((button) => button.text() === 'Repair')!
    await repair.trigger('click')
    await settle()
    expect(wrapper.text()).toContain('Still quarantined')

    const dismissToggle = wrapper.findAll('button').find((button) => button.text() === 'Dismiss…')!
    await dismissToggle.trigger('click')
    await settle()
    await wrapper.find('input.dismiss-input').setValue('Manually verified; safe to close.')
    await settle()
    const confirm = wrapper.findAll('button').find((button) => button.text() === 'Dismiss intent')!
    await confirm.trigger('click')
    await settle()

    expect(api.dismissPlacementIntent).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Dismissed')
    expect(wrapper.text()).toContain('0 placement intents are blocking startup')
  })

  it('keeps the dismissal form open when the backend rejects the dismissal', async () => {
    api.fetchPlacementRecoveryIntents.mockResolvedValue({ intents: [intent()] })
    api.dismissPlacementIntent.mockRejectedValue(axiosError(409, 'Placement limit_sell-abc123 is in state completed, not quarantined.'))
    const wrapper = render()
    await settle()

    const dismissToggle = wrapper.findAll('button').find((button) => button.text() === 'Dismiss…')!
    await dismissToggle.trigger('click')
    await settle()
    const input = wrapper.find('input.dismiss-input')
    await input.setValue('I checked the exchange.')
    await settle()

    const confirm = wrapper.findAll('button').find((button) => button.text() === 'Dismiss intent')!
    await confirm.trigger('click')
    await settle()

    expect(wrapper.find('[role="alert"]').text()).toContain('is in state completed, not quarantined')
    // The note survives the failed attempt so the operator can correct it.
    expect((wrapper.find('input.dismiss-input').element as HTMLInputElement).value).toBe('I checked the exchange.')
  })

  it('cancels the dismissal form without calling the backend', async () => {
    api.fetchPlacementRecoveryIntents.mockResolvedValue({ intents: [intent()] })
    const wrapper = render()
    await settle()

    const dismissToggle = wrapper.findAll('button').find((button) => button.text() === 'Dismiss…')!
    await dismissToggle.trigger('click')
    await settle()
    expect(wrapper.find('input.dismiss-input').exists()).toBe(true)

    const cancel = wrapper.findAll('button').find((button) => button.text() === 'Cancel')!
    await cancel.trigger('click')
    await settle()
    expect(wrapper.find('input.dismiss-input').exists()).toBe(false)
    expect(api.dismissPlacementIntent).not.toHaveBeenCalled()
  })
})
