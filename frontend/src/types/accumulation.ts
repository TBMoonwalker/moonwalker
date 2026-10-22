export type AccumulationAction = 'pause' | 'resume' | 'close' | 'retry_close' | 'sell_partial' | 'reactivate' | 'retry_entry' | 'correct_import' | 'abandon_entry' | 'switch_strategy' | 'repair_order' | 'retire_command' | 'rebind_account' | 'adjust_inventory' | 'declare_ownership' | 'acknowledge_settlement' | 'restore_inventory'

export interface AccumulationOperation {
  operation_id: string
  action: string
  status: string
  result_state: string
  result_revision: number
  reason: string | null
  created_at?: string
  adjustment?: { direction: 'add' | 'remove'; quantity: string; note: string; before_quantity: string; after_quantity: string; before_cost: string | null; after_cost: string | null }
}

export interface AccumulationStatus {
  wait_condition?: AccumulationWaitCondition | null
  account_matches?: boolean | null
  activation_id: string
  symbol: string
  state: string
  explicitly_paused: boolean
  revision: number
  reason: string | null
  runtime_wait_reason: string | null
  observations_initialized: boolean
  strategy_version_id: number | null
  strategy_slug: string | null
  strategy_version: number | null
  inventory_restore_required?: boolean
  holding_integrity: 'unlinked' | 'owned' | 'invalid'
  holding: null | {
    net_quantity: string | null
    remaining_cost: string | null
    contributed_quote: string | null
    disposal_proceeds: string | null
    basis_provenance: string | null
    execution_history_complete: boolean
    fees: null | { totals: Record<string, string>; pending_reports: number }
  }
}

export interface AccumulationDetail extends AccumulationStatus {
  quarantined_orders?: Array<{ placement_operation_id: string; side: 'buy' | 'sell'; has_lookup_identity: boolean }>
  settled_commands?: AccumulationOperation[]
  quarantined_commands?: AccumulationOperation[]
  close_predecessor?: AccumulationOperation | null
  portfolio?: AccumulationPortfolio
  orders?: AccumulationOrderCheckpoint[]
  older_orders_available?: boolean
  entry: null | (AccumulationOperation & {
    source: 'asap' | 'csv' | null
    declaration_invalid: boolean
    declaration: null | {
      net_quantity: string
      acquisition_cost: string
      row_count: number
      historical_fees_known: boolean
    }
  })
  operations: AccumulationOperation[]
  older_operations_available: boolean
}

export interface AccumulationCommand {
  symbol: string
  action: AccumulationAction
  operation_id: string
  expected_revision: number
  previous_operation_id?: string
  quantity?: string
  csv_content?: string
  target_version_id?: number
  placement_operation_id?: string
  direction?: 'add' | 'remove'
  acquisition_cost?: string | null
  confirmation?: string
  note?: string
}

export interface AccumulationCommandResult {
  operation: {
    operation_id: string
    activation_id: string
    status: string
    state: string
    revision: number
    reason: string | null
  }
}

export interface AccumulationPage {
  stream_available?: boolean
  activations: AccumulationStatus[]
  next_after: string | null
  portfolio?: AccumulationPortfolio
}

export interface AccumulationPortfolio {
  holding_count: number
  unverified_holding_count: number
  valuation_available: false
  by_quote: Array<{ quote: string; holding_count: number; known_remaining_cost: string; remaining_cost: string | null; unknown_cost_count: number }>
}

export interface AccumulationWaitCondition {
  reason: string
  timeframe: string
  observed_close_ms: number
  observed_price: string
  price_basis?: 'ask'
  next_close_ms: number
  levels: Array<{
    kind: string
    direction: 'below' | 'at_or_below' | 'at_or_above'
    target_price: string
    change_percent: string
  }>
}

export interface AccumulationPerformance {
  complete: boolean
  observed_at_ms: number
  basis: string
  reason: string | null
  by_quote: Array<{ quote: string; complete: boolean; unknown_deal_count: number; live_holding_count: number; market_value: string | null; realized: string | null; unrealized: string | null; total_return: string | null }>
}

export interface AccumulationOrderCheckpoint {
  checkpoint_id: number
  deal_id: string | null
  side: 'buy' | 'sell'
  filled_quantity: string | null
  quote_cost: string | null
  fees: Record<string, string> | null
  fees_complete: boolean
  terminal: boolean
  updated_at: string
  inventory_at_update: null | {
    net_quantity: string | null
    remaining_cost: string | null
    contributed_quote: string | null
    disposal_proceeds: string | null
    fees: Record<string, string> | null
    pending_fee_reports: number
    basis_provenance: string
  }
}

export interface AccumulationParameters {
  timeframe: string
  peak_length: number
  atr_length: number
  entry_atr: string
  spacing_atr: string
  recovery_atr: string
  min_fraction: string
  slope: string
  max_fraction: string
}

export interface AccumulationStrategy {
  id: number
  slug: string
  name: string
  version: number
  parameters: AccumulationParameters
  required_history_candles: number
}

export interface AccumulationStrategyPage {
  versions: AccumulationStrategy[]
  next_after_id: number | null
  defaults: AccumulationParameters
  timeframes: string[]
}
