import type { AccumulationAction, AccumulationDetail } from '../types/accumulation'

interface AccumulationOutlook {
  title: string
  description: string
  next: string
  tone: 'warning' | 'info' | 'default'
  action?: AccumulationAction
}

const waits: Record<string, [string, string]> = {
  WAIT_REBASE: ['Initializing accumulation strategy', 'Loading completed candles for subsequent accumulation buys.'],
  WAIT_DATA: ['Waiting for market history', 'A complete, continuous candle history is needed before the strategy can evaluate a buy.'],
  WAIT_NEW_CANDLE: ['Waiting for a candle close', 'The current candle is still open. The strategy evaluates completed candles.'],
  WAIT_DEPTH: ['Waiting for a deeper dip', 'The latest dip has not reached the strategy’s entry threshold.'],
  WAIT_DECLINE: ['Waiting for a declining close', 'The strategy needs a completed candle that closes lower.'],
  WAIT_REARM: ['Waiting for a fresh opportunity', 'A further decline or a recovery followed by a fresh correction must meet the strategy’s spacing rules.'],
  WAIT_BUDGET: ['Waiting for available budget', 'Available trading funds do not currently cover an eligible buy.'],
  WAIT_MINIMUM: ['Below the exchange minimum', 'The eligible order is too small for the exchange.'],
  WAIT_ACCOUNT: ['Exchange account needs attention', 'The configured account could not pass the required checks. Buying is on hold.'],
  WAIT_GLOBAL_PAUSE: ['Moonwalker is paused', 'The global pause blocks new buys for this symbol.'],
  WAIT_STRATEGY: ['Strategy needs attention', 'The pinned strategy could not be loaded or validated. Buying is on hold.'],
  WAIT_ACCUMULATION_MODE: ['Accumulation mode is inactive', 'Select accumulation trading mode in Configuration before new buys can run.'],
  WAIT_ORDER: ['Waiting for an order', 'The existing order must settle before another buy can proceed.'],
  WAIT_RECONCILIATION: ['Checking an existing order', 'Exchange evidence is being reconciled before new trading can proceed.'],
  WAIT_COMMAND: ['Request is being processed', 'Wait for the recorded request to resolve before choosing another action.'],
}

/** Describe the observed state without promising an order or inventing market telemetry. */
export function accumulationOutlook(row: AccumulationDetail, fresh: boolean): AccumulationOutlook {
  if (!fresh) return { title: 'Status needs refresh', description: 'The last snapshot is shown. Actions stay disabled until a fresh status is available.', next: 'Refresh status to check the current state.', tone: 'warning' }
  if (row.account_matches === false) return { title: 'Account ownership needs review', description: 'The configured credentials differ from this holding’s recorded account. Buying is on hold.', next: 'Review the account evidence below.', tone: 'warning' }
  if (row.holding_integrity === 'invalid' || row.inventory_restore_required) return { title: 'Inventory needs repair', description: 'The recorded inventory link must be restored before trading.', next: 'Review the inventory evidence below.', tone: 'warning' }
  if (row.quarantined_orders?.length || row.quarantined_commands?.length || row.settled_commands?.length) return { title: 'Recorded work needs review', description: 'Resolve the interrupted request or order evidence before new trading can proceed.', next: 'Review the recovery controls below.', tone: 'warning' }
  if (row.state === 'closing') return { title: 'Closing · new buys blocked', description: 'The remaining coins stay recorded until sold, including dust below the exchange minimum.', next: 'Retry a remaining sale only when sellable and previous orders have settled.', tone: 'warning' }
  if (row.state === 'stopped') return { title: 'Accumulation stopped', description: 'This registration is not buying. Wallet coins are not automatically adopted.', next: 'Review the entry or reactivate explicitly to start again.', tone: 'default' }
  if (!row.observations_initialized && ['validating', 'paused'].includes(row.state)) return {
    title: row.entry?.declaration_invalid ? 'Entry declaration needs correction' : 'Entry check incomplete',
    description: 'The automatic entry check has not completed. Buying remains paused.',
    next: row.entry?.declaration_invalid ? 'Correct the CSV declaration, then retry the entry check.' : 'Retry the failed exchange check to continue entry.',
    tone: 'warning', action: row.entry?.declaration_invalid ? undefined : 'retry_entry',
  }
  if (row.state === 'paused' || row.explicitly_paused) return { title: 'Accumulation paused', description: 'New buys are paused. Existing coins remain managed.', next: 'Resume explicitly when you want the strategy to evaluate new buys.', tone: 'default', action: 'resume' }
  if (row.state === 'blocked') return { title: 'Buying is blocked', description: 'A holding check needs attention before buying can continue.', next: 'Review the reported reason and recovery controls below.', tone: 'warning' }
  if (row.operations.some(operation => operation.status === 'pending')) return { title: 'Request is being processed', description: 'The recorded request has not finished yet.', next: 'Wait for its outcome before choosing another action.', tone: 'info' }
  if (!row.holding && row.entry?.source === 'asap' && ['WAIT_DATA', 'WAIT_REBASE'].includes(row.runtime_wait_reason ?? '')) return { title: 'Initial buy needs exchange data', description: 'Waiting for the exchange quote and account balance.', next: '', tone: 'info' }
  const wait = row.runtime_wait_reason ? waits[row.runtime_wait_reason] : undefined
  if (wait) return { title: wait[0], description: wait[1], next: row.runtime_wait_reason === 'WAIT_GLOBAL_PAUSE' ? 'Use Resume Moonwalker in the top bar when ready.' : 'Buying resumes only when the strategy and trading checks pass.', tone: 'info' }
  if (row.runtime_wait_reason) return { title: 'Trading check pending', description: 'The runtime has reported a wait condition. A buy is not confirmed.', next: 'Review the runtime reason in Strategy and status details.', tone: 'info' }
  if (row.state === 'enabled' && !row.holding && row.entry?.source === 'asap') return { title: 'Starting initial buy', description: 'ASAP opens this holding with the configured base order.', next: '', tone: 'info' }
  if (row.state === 'enabled') return { title: 'Watching for a buy signal', description: 'The registration is enabled. Buys require a qualifying completed candle and available budget.', next: 'No action needed to wait. A buy is not guaranteed at the next candle close.', tone: 'info' }
  return { title: 'Waiting for an update', description: 'A lifecycle step or trading check is still pending.', next: 'Check the reported reason below or refresh status.', tone: 'default' }
}
