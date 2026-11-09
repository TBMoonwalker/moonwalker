export type PlacementRecoveryIntentState = 'quarantined' | 'restored_quarantined'

export interface PlacementRecoveryIntent {
  operation_id: string
  symbol: string
  action: string
  side: string
  order_type: string
  state: PlacementRecoveryIntentState
  exchange_name: string
  reason_code: string | null
  error_message: string | null
  exchange_order_id: string | null
  has_lookup_identity: boolean
  limit_price: number | null
  amount: number | null
  requested_quote: number | null
  route: string
  created_at: string | null
  completed_at: string | null
}

export interface PlacementRecoveryList {
  intents: PlacementRecoveryIntent[]
}

export type PlacementRecoveryActionStatus = 'completed' | 'rejected' | 'unchanged' | 'dismissed'

export interface PlacementRecoveryActionResult {
  operation_id: string
  status: PlacementRecoveryActionStatus
  state: string
  message: string
}
