import { onScopeDispose, reactive, ref } from 'vue'
import {
  dismissPlacementIntent,
  fetchPlacementRecoveryIntents,
  placementRecoveryError,
  repairPlacementIntent,
} from '../api/placementRecovery'
import type {
  PlacementRecoveryActionResult,
  PlacementRecoveryIntent,
} from '../types/placementRecovery'

export interface PlacementRecoveryActionState {
  pending: boolean
  error: string
  last: PlacementRecoveryActionResult | null
}

/**
 * Owns the quarantined placement list and the operator action state for each
 * intent. Every intent keeps its own action history so an inconclusive repair
 * ("unchanged") can be retried or followed by an explicit dismissal.
 */
export function usePlacementRecovery() {
  const intents = ref<PlacementRecoveryIntent[]>([])
  const loading = ref(false)
  const loadError = ref('')
  const actions = reactive(new Map<string, PlacementRecoveryActionState>())
  const dismissing = ref<string | null>(null)
  const dismissNote = ref('')
  let disposed = false

  onScopeDispose(() => { disposed = true })

  async function load(): Promise<void> {
    if (loading.value || disposed) return
    loading.value = true
    loadError.value = ''
    try {
      const page = await fetchPlacementRecoveryIntents()
      if (!disposed) intents.value = page.intents
    } catch (cause) {
      if (!disposed) loadError.value = placementRecoveryError(cause)
    } finally {
      if (!disposed) loading.value = false
    }
  }

  function actionState(operationId: string): PlacementRecoveryActionState {
    const existing = actions.get(operationId)
    if (existing) {
      return existing
    }
    actions.set(operationId, { pending: false, error: '', last: null })
    // Read the value back so mutations go through the reactive proxy;
    // mutating the raw object would not invalidate dependent computed.
    const created = actions.get(operationId)
    if (!created) {
      throw new Error(`Placement recovery state for ${operationId} is unavailable`)
    }
    return created
  }

  async function repair(operationId: string): Promise<PlacementRecoveryActionResult | null> {
    const state = actionState(operationId)
    if (state.pending) return null
    state.pending = true
    state.error = ''
    try {
      const result = await repairPlacementIntent(operationId)
      if (!disposed) state.last = result
      return result
    } catch (cause) {
      if (!disposed) state.error = placementRecoveryError(cause)
      return null
    } finally {
      if (!disposed) state.pending = false
    }
  }

  function openDismiss(operationId: string): void {
    dismissing.value = operationId
    dismissNote.value = ''
  }

  function closeDismiss(): void {
    dismissing.value = null
    dismissNote.value = ''
  }

  async function dismiss(operationId: string): Promise<PlacementRecoveryActionResult | null> {
    const state = actionState(operationId)
    if (state.pending) return null
    state.pending = true
    state.error = ''
    try {
      const result = await dismissPlacementIntent(operationId, dismissNote.value)
      if (!disposed) state.last = result
      closeDismiss()
      return result
    } catch (cause) {
      if (!disposed) state.error = placementRecoveryError(cause)
      return null
    } finally {
      if (!disposed) state.pending = false
    }
  }

  return {
    intents,
    loading,
    loadError,
    actions,
    dismissing,
    dismissNote,
    load,
    repair,
    openDismiss,
    closeDismiss,
    dismiss,
  }
}
