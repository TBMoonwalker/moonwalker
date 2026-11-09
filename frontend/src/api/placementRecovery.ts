import axios from 'axios'
import { buildMoonwalkerApiUrl } from '../helpers/configEditorDefaults'
import { MOONWALKER_CLIENT_HEADER, MOONWALKER_CLIENT_HEADER_VALUE } from './client'
import type { PlacementRecoveryActionResult, PlacementRecoveryList } from '../types/placementRecovery'

// The operator recovery endpoints stay reachable while every trading and
// configuration route is blocked, so the dashboard card is the only live
// control in recovery mode and must not depend on websockets.

export async function fetchPlacementRecoveryIntents(): Promise<PlacementRecoveryList> {
  return (await axios.get<PlacementRecoveryList>(
    buildMoonwalkerApiUrl('/orders/placement-recovery'),
  )).data
}

export async function repairPlacementIntent(operationId: string): Promise<PlacementRecoveryActionResult> {
  return (await axios.post<PlacementRecoveryActionResult>(
    buildMoonwalkerApiUrl(`/orders/placement-recovery/${encodeURIComponent(operationId)}/repair`),
    {},
    { headers: { [MOONWALKER_CLIENT_HEADER]: MOONWALKER_CLIENT_HEADER_VALUE } },
  )).data
}

export async function dismissPlacementIntent(
  operationId: string,
  note: string,
): Promise<PlacementRecoveryActionResult> {
  return (await axios.post<PlacementRecoveryActionResult>(
    buildMoonwalkerApiUrl(`/orders/placement-recovery/${encodeURIComponent(operationId)}/dismiss`),
    { note },
    { headers: { [MOONWALKER_CLIENT_HEADER]: MOONWALKER_CLIENT_HEADER_VALUE } },
  )).data
}

export function placementRecoveryError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const payload = error.response?.data as { error?: string } | undefined
    if (payload?.error) {
      return payload.error
    }
    const status = error.response?.status
    return status ? `Request failed: ${status}` : `Request failed: ${error.message}`
  }
  return error instanceof Error ? error.message : String(error)
}
