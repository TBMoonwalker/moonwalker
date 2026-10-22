import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useWebSocket } from '@vueuse/core'
import { accumulationErrorStatus, fetchAccumulationDetail, fetchAccumulationPage, fetchAccumulationStrategies, sendAccumulationCommand } from '../api/accumulation'
import { fetchAccumulationPerformance } from '../api/accumulation'
import type { AccumulationPerformance } from '../types/accumulation'
import { extractApiErrorMessage } from '../helpers/apiErrors'
import { accumulationActions, accumulationClosePredecessor } from '../helpers/accumulation'
import { createOrderOperationId } from '../helpers/orderMutations'
import { MOONWALKER_API_ORIGIN } from '../config'
import { readText, writeText, removeJSON } from '../helpers/safeStorage'
import type { AccumulationAction, AccumulationCommand, AccumulationDetail, AccumulationStatus, AccumulationStrategy, AccumulationPortfolio } from '../types/accumulation'

// Retain an uncertain request across route changes; never replay it automatically.
const pendingKey = `moonwalker.accumulation.pending:${MOONWALKER_API_ORIGIN}`
const session = () => window.sessionStorage
const unresolvedRequest = ref<AccumulationCommand | null>(null)

function restoreRequest(): AccumulationCommand | null {
  if (unresolvedRequest.value) return unresolvedRequest.value
  try {
    const value = JSON.parse(readText(pendingKey, session) ?? 'null')
    if (value && typeof value.symbol === 'string' && typeof value.operation_id === 'string' &&
        typeof value.action === 'string' && Number.isSafeInteger(value.expected_revision)) {
      unresolvedRequest.value = value as AccumulationCommand
    }
  } catch { /* Storage is optional; requests are never replayed automatically. */ }
  return unresolvedRequest.value
}

function rememberRequest(command: AccumulationCommand | null, resolvedId?: string) {
  if (resolvedId && unresolvedRequest.value?.operation_id !== resolvedId) return
  unresolvedRequest.value = command
  if (command) writeText(pendingKey, JSON.stringify(command), session)
  else removeJSON(pendingKey, session)
}

export function useAccumulationPanel(symbol?: string) {
  restoreRequest()
  const visible = ref(false)
  const available = ref(false)
  const rows = ref<AccumulationStatus[]>([])
  const portfolio = ref<AccumulationPortfolio | null>(null)
  const performance = ref<AccumulationPerformance | null>(null)
  const performanceLoading = ref(false)
  const performanceError = ref('')

  async function loadPerformance() {
    if (performanceLoading.value) return
    performanceLoading.value = true
    performanceError.value = ''
    try {
      const result = await fetchAccumulationPerformance()
      if (!Array.isArray(result.by_quote)) throw new Error('Invalid valuation response')
      if (!disposed) performance.value = result
    } catch (cause) {
      if (!disposed) performanceError.value = extractApiErrorMessage(cause, 'Valuation is unavailable; no price or return has been guessed.')
    } finally {
      if (!disposed) performanceLoading.value = false
    }
  }
  const next = ref<string | null>(null)
  const selected = ref<string | null>(symbol ?? unresolvedRequest.value?.symbol ?? null)
  const detail = ref<AccumulationDetail | null>(null)
  const loading = ref(false)
  const fresh = ref(false)
  const busy = ref(false)
  const error = ref('')
  const notice = ref('')
  const draft = ref<AccumulationCommand | null>(null)
  const uncertain = ref<AccumulationCommand | null>(!symbol || unresolvedRequest.value?.symbol === symbol ? unresolvedRequest.value : null)
  watch([selected, unresolvedRequest], ([current, request]) => {
    uncertain.value = request?.symbol === current ? request : null
  })
  const quantity = ref('')
  const csv = ref('')
  const adjustmentDirection = ref<'add' | 'remove'>('add')
  const adjustmentQuantity = ref('')
  const adjustmentCost = ref('')
  const adjustmentNote = ref('')
  const ownershipConfirmation = ref('')
  const ownershipNote = ref('')
  const strategies = ref<AccumulationStrategy[]>([])
  const strategyCursor = ref<number | null>(null)
  const targetVersion = ref<number | null>(null)
  const repairTarget = ref<string | null>(null)
  const retirementTarget = ref<string | null>(null)
  const strategyError = ref('')
  const strategyLoading = ref(false)
  let sequence = 0
  let disposed = false
  let pageLoading = false
  const streamUrl = ref<string>()
  const streamAvailable = ref(true)
  const stream = useWebSocket(streamUrl, {
    immediate: false,
    autoConnect: false,
    autoReconnect: { retries: -1, delay: 1500 },
    onDisconnected(socket) {
      if (!disposed && socket === stream.ws.value) fresh.value = false
    },
    onError(socket) {
      if (!disposed && socket === stream.ws.value) fresh.value = false
    },
    onMessage(_socket, event) {
      if (disposed) return
      try {
        const snapshot = JSON.parse(String(event.data))
        if (snapshot.type === 'unavailable') { available.value = false; fresh.value = false; return }
        if (snapshot.type !== 'snapshot') return
        if (!Array.isArray(snapshot.page?.activations) ||
            (snapshot.detail !== null && (!snapshot.detail || typeof snapshot.detail.symbol !== 'string' ||
              !Number.isSafeInteger(snapshot.detail.revision) || !Array.isArray(snapshot.detail.operations)))) throw new Error('Invalid snapshot')
        if (selected.value && snapshot.detail?.symbol !== selected.value) return
        ++sequence
        loading.value = false
        const incoming = snapshot.page.activations as AccumulationStatus[]
        rows.value = [...incoming, ...rows.value.filter(row => !incoming.some(item => item.symbol === row.symbol))]
        if (rows.value.length <= incoming.length) next.value = snapshot.page.next_after
        const bindSelection = !selected.value && !!snapshot.detail?.symbol
        if (!selected.value) selected.value = snapshot.detail?.symbol ?? null
        applyDetail(snapshot.detail)
        portfolio.value = snapshot.detail?.portfolio ?? snapshot.page.portfolio ?? null
        if (bindSelection) connectStream()
      } catch {
        fresh.value = false
        error.value = 'Live accumulation status could not be read. Refresh status before choosing an action.'
      }
    },
  })

  function connectStream() {
    if (!streamAvailable.value || disposed || !available.value) return
    const url = new URL('/accumulation/stream', MOONWALKER_API_ORIGIN)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    if (selected.value) url.searchParams.set('symbol', selected.value)
    if (streamUrl.value === url.toString() && stream.status.value !== 'CLOSED') return
    streamUrl.value = url.toString()
    stream.open()
  }

  function applyDetail(result: AccumulationDetail | null) {
    if (draft.value && detail.value && result && (
      detail.value.activation_id !== result.activation_id ||
      detail.value.account_matches !== result.account_matches ||
      JSON.stringify(detail.value.holding) !== JSON.stringify(result.holding)
    )) {
      draft.value = null
      notice.value = 'Holding or account changed. Review the action again.'
    }
    detail.value = result
    if (!result) { fresh.value = false; return }
    if (!result.quarantined_commands?.some(operation => operation.operation_id === retirementTarget.value)) retirementTarget.value = result.quarantined_commands?.[0]?.operation_id ?? null
    if (!result.quarantined_orders?.some(order => order.placement_operation_id === repairTarget.value && order.has_lookup_identity)) repairTarget.value = result.quarantined_orders?.find(order => order.has_lookup_identity)?.placement_operation_id ?? null
    portfolio.value = result.portfolio ?? null
    available.value = true
    fresh.value = true
    error.value = ''
  }
  const actions = computed(() => detail.value ? accumulationActions(detail.value) : [])
  const disabled = computed(() => !available.value || !fresh.value || busy.value || !!uncertain.value || !!draft.value || !!unresolvedRequest.value)
  const confirmBlockedReason = computed(() => {
    if (!draft.value) return 'Choose an action to review.'
    if (busy.value) return 'Sending the recorded request.'
    if (unresolvedRequest.value && unresolvedRequest.value.operation_id !== draft.value.operation_id) return `Resolve the pending request for ${unresolvedRequest.value.symbol} first.`
    if (!available.value || !fresh.value) return 'Refresh status before confirming.'
    if (!detail.value || draft.value.symbol !== detail.value.symbol || draft.value.expected_revision !== detail.value.revision) return 'The holding changed. Cancel and review the action again.'
    if (!actions.value.includes(draft.value.action)) return 'This action is no longer available. Cancel and review the current status.'
    return ''
  })
  const pendingRequest = computed(() => unresolvedRequest.value)

  async function loadStrategies(more = false) {
    if (strategyLoading.value) return
    strategyLoading.value = true
    try {
      const page = await fetchAccumulationStrategies(more ? strategyCursor.value ?? 0 : 0)
      if (disposed) return
      strategies.value = more ? [...strategies.value, ...page.versions.filter(row => !strategies.value.some(old => old.id === row.id))] : page.versions
      strategyCursor.value = page.next_after_id
      strategyError.value = ''
    } catch {
      if (!disposed) strategyError.value = 'Compatible strategies could not be loaded. Refresh the strategy list before switching.'
    } finally { strategyLoading.value = false }
  }

  async function refreshDetail() {
    if (!selected.value || disposed) return
    const request = ++sequence
    loading.value = true
    fresh.value = false
    try {
      const result = await fetchAccumulationDetail(selected.value)
      if (request !== sequence || disposed) return
      applyDetail(result)
    } catch (cause) {
      if (request !== sequence || disposed) return
      if (accumulationErrorStatus(cause) === 503) available.value = false
      error.value = `${selected.value}: ${extractApiErrorMessage(cause, 'Could not load this holding. Actions are disabled until refresh succeeds.')}`
    } finally {
      if (request === sequence && !disposed) loading.value = false
    }
  }

  async function selectSymbol(symbol: string) {
    ++sequence
    stream.close()
    selected.value = symbol
    detail.value = null
    fresh.value = false
    draft.value = null
    quantity.value = ''
    csv.value = ''
    targetVersion.value = null
    await refreshDetail()
    connectStream()
  }

  async function loadPage(more = false) {
    if (pageLoading || disposed) return
    pageLoading = true
    try {
      const result = await fetchAccumulationPage(more ? next.value ?? undefined : undefined)
      if (disposed) return
      rows.value = more ? [...rows.value, ...result.activations.filter(row => !rows.value.some(old => old.symbol === row.symbol))] : result.activations
      next.value = result.next_after
      portfolio.value = result.portfolio ?? null
      visible.value = true
      available.value = true
      streamAvailable.value = result.stream_available !== false
      if (!streamAvailable.value) stream.close()
      error.value = ''
      if (!selected.value && rows.value[0]) await selectSymbol(rows.value[0].symbol)
      else if (selected.value) await refreshDetail()
      connectStream()
    } catch (cause) {
      if (disposed) return
      available.value = false
      fresh.value = false
      if (accumulationErrorStatus(cause) === 503 && !visible.value && !uncertain.value) return
      visible.value = true
      error.value = extractApiErrorMessage(cause, 'Accumulation status is unavailable.')
    } finally {
      pageLoading = false
    }
  }

  function prepare(action: AccumulationAction) {
    const row = detail.value
    if (disabled.value || !row || !actions.value.includes(action)) return
    if (unresolvedRequest.value) { error.value = `Resolve the pending request for ${unresolvedRequest.value.symbol} before starting another action.`; return }
    error.value = ''
    if (action === 'sell_partial' && (!/^(?:\d+\.?\d*|\.\d+)$/.test(quantity.value.trim()) || !/[1-9]/.test(quantity.value))) {
      error.value = 'Enter a positive base-asset quantity using decimal digits.'
      return
    }
    if (action === 'correct_import' && (!csv.value.trim() || csv.value.length > 1_000_000)) {
      error.value = 'Enter the corrected CSV declaration (up to 1 MB).'
      return
    }
    if (action === 'switch_strategy' && (!targetVersion.value || targetVersion.value === row.strategy_version_id ||
        !strategies.value.some(version => version.id === targetVersion.value))) {
      error.value = 'Select a different compatible strategy version.'
      return
    }
    if (action === 'repair_order' && !row.quarantined_orders?.some(order => order.has_lookup_identity && order.placement_operation_id === repairTarget.value)) {
      error.value = 'Select a quarantined order with a durable exchange identity.'
      return
    }
    if (action === 'acknowledge_settlement' && row.settled_commands?.length !== 1) {
      error.value = 'Refresh and resolve ambiguous interrupted settlements before acknowledgement.'
      return
    }
    if (action === 'retire_command' && !row.quarantined_commands?.some(operation => operation.operation_id === retirementTarget.value)) {
      error.value = 'Select the interrupted command to retire.'
      return
    }
    const command: AccumulationCommand = {
      symbol: row.symbol, action, operation_id: createOrderOperationId(`acc-${action}`), expected_revision: row.revision,
    }
    if (action === 'declare_ownership') {
      const note = ownershipNote.value.trim()
      if (ownershipConfirmation.value !== row.symbol || !note || note.length > 500 || /[\u0000-\u001f]/.test(note)) {
        error.value = 'Type the full symbol exactly and enter an ownership declaration reason (up to 500 characters).'
        return
      }
      command.confirmation = ownershipConfirmation.value
      command.note = note
    }
    if (action === 'adjust_inventory') {
      const amount = adjustmentQuantity.value.trim()
      const cost = adjustmentCost.value.trim()
      const note = adjustmentNote.value.trim()
      if (!/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(amount) || !/[1-9]/.test(amount) || amount.length > 128 ||
          (adjustmentDirection.value === 'add' && cost !== '' && (!/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(cost) || cost.length > 128)) ||
          !note || note.length > 500 || /[\u0000-\u001f]/.test(note)) {
        error.value = 'Enter a positive decimal correction quantity, a valid acquisition cost or leave it unknown, and a reason (up to 500 characters).'
        return
      }
      command.direction = adjustmentDirection.value
      command.quantity = amount
      command.acquisition_cost = adjustmentDirection.value === 'add' && cost !== '' ? cost : null
      command.note = note
    }
    if (action === 'sell_partial') command.quantity = quantity.value.trim()
    if (action === 'correct_import') command.csv_content = csv.value
    if (action === 'repair_order') command.placement_operation_id = repairTarget.value!
    if (action === 'acknowledge_settlement') command.previous_operation_id = row.settled_commands![0]!.operation_id
    if (action === 'retire_command') command.previous_operation_id = retirementTarget.value!
    if (action === 'switch_strategy') command.target_version_id = targetVersion.value!
    if (['retry_entry', 'correct_import'].includes(action) && targetVersion.value !== null) {
      if (!strategies.value.some(version => version.id === targetVersion.value)) { error.value = 'Select a compatible saved version.'; return }
      command.target_version_id = targetVersion.value
    }
    if (['retry_entry', 'correct_import', 'abandon_entry'].includes(action)) command.previous_operation_id = row.entry!.operation_id
    if (action === 'retry_close') {
      const previous = accumulationClosePredecessor(row)
      if (!previous) { error.value = 'Refresh the current close before retrying.'; return }
      command.previous_operation_id = previous.operation_id
    }
    draft.value = command
  }

  async function submit() {
    if (busy.value || (!uncertain.value && !draft.value)) return
    if (!uncertain.value && confirmBlockedReason.value) { error.value = confirmBlockedReason.value; return }
    if (unresolvedRequest.value && unresolvedRequest.value.operation_id !== (uncertain.value ?? draft.value)?.operation_id) { error.value = `Resolve the pending request for ${unresolvedRequest.value.symbol} first.`; return }
    const command = { ...(uncertain.value ?? draft.value!) }
    // Persist in memory before sending, so a route change cannot produce a new ID.
    rememberRequest(command)
    uncertain.value = command
    draft.value = null
    busy.value = true
    notice.value = ''
    error.value = ''
    try {
      const result = await sendAccumulationCommand(command)
      if (result.operation.operation_id !== command.operation_id) throw new Error('The response did not identify this request.')
      if (['repair_order', 'rebind_account', 'declare_ownership'].includes(command.action) && result.operation.status === 'quarantined') {
        notice.value = ['rebind_account', 'declare_ownership'].includes(command.action)
          ? 'Account ownership evidence is incomplete. The holding stays paused under its original binding. Retry this same request for fresh verification.'
          : 'Terminal order evidence is not available. The order stays quarantined and buying stays paused. Retry this same request for a fresh lookup.'
        return
      }
      rememberRequest(null, command.operation_id)
      performance.value = null
      uncertain.value = null
      notice.value = result.operation.status === 'pending'
        ? command.action === 'correct_import'
          ? 'Correction recorded. The entry stays paused until you choose Retry entry check.'
          : 'Request recorded. Work is pending; check the current status below.'
        : `Recorded outcome: ${result.operation.status}. Current status has been refreshed below.`
    } catch (cause) {
      const status = accumulationErrorStatus(cause)
      if (status === 400 || status === 409) {
        rememberRequest(null, command.operation_id)
        uncertain.value = null
        notice.value = extractApiErrorMessage(cause, 'Request rejected. Review the refreshed state before choosing another action.')
      } else {
        notice.value = 'The request outcome is unknown. Retry this same request to retrieve its recorded outcome; no new operation will be created.'
      }
    } finally {
      if (!disposed) await refreshDetail()
      busy.value = false
    }
  }

  onMounted(() => {
    void loadPage()
    void loadStrategies()

  })
  onBeforeUnmount(() => { disposed = true; ++sequence; stream.close() })
  return { confirmBlockedReason, pendingRequest, streamAvailable, streamStatus: stream.status, visible, available, rows, portfolio, performance, performanceLoading, performanceError, loadPerformance, next, selected, detail, loading, fresh, busy, error, notice, draft, uncertain, quantity, csv, adjustmentDirection, adjustmentQuantity, adjustmentCost, adjustmentNote, ownershipConfirmation, ownershipNote, actions, disabled, loadPage, selectSymbol, refreshDetail, prepare, submit, strategies, strategyCursor, targetVersion, repairTarget, retirementTarget, strategyError, strategyLoading, loadStrategies }
}
