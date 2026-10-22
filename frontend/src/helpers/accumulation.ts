import type { AccumulationAction, AccumulationDetail } from '../types/accumulation'

export const accumulationActionLabels: Record<AccumulationAction, string> = {
  pause: 'Pause accumulation', resume: 'Resume accumulation', close: 'Close holding',
  retry_close: 'Retry remaining sale', sell_partial: 'Sell part', reactivate: 'Reactivate',
  retry_entry: 'Validate entry', correct_import: 'Correct CSV', abandon_entry: 'Abandon entry',
  switch_strategy: 'Switch strategy',
  repair_order: 'Reconcile restored order',
  retire_command: 'Retire interrupted command',
  rebind_account: 'Revalidate rotated API key',
  adjust_inventory: 'Correct managed inventory',
  restore_inventory: 'Restore recorded inventory link',
  acknowledge_settlement: 'Acknowledge recorded sale settlement',
  declare_ownership: 'Declare ownership under changed credentials',
}

export function accumulationActions(row: AccumulationDetail): AccumulationAction[] {
  if (row.explicitly_paused && row.observations_initialized && row.account_matches !== false &&
      (row.holding_integrity === 'invalid' || row.inventory_restore_required === true) &&
      ['paused', 'blocked', 'closing'].includes(row.state)) return ['restore_inventory']
  if (row.settled_commands?.length && row.explicitly_paused) return ['acknowledge_settlement']
  if (row.account_matches === false) return row.holding_integrity !== 'invalid'
    ? [...(row.quarantined_orders?.some(order => order.has_lookup_identity) ? ['repair_order' as const] : []), 'rebind_account', 'declare_ownership'] : []
  if (row.quarantined_orders?.length) {
    return row.holding_integrity !== 'invalid' && row.explicitly_paused && row.quarantined_orders.some(order => order.has_lookup_identity) ? ['repair_order'] : []
  }
  if (row.quarantined_commands?.length) {
    return row.holding_integrity !== 'invalid' && row.explicitly_paused ? ['retire_command'] : []
  }
  const actions = regularActions(row)
  return actions
}

export function accumulationClosePredecessor(row: AccumulationDetail) {
  if (row.state !== 'closing') return undefined
  return [row.close_predecessor, ...row.operations].find(operation => operation &&
    ['close', 'retry_close'].includes(operation.action) && operation.result_revision === row.revision &&
    (['pending', 'reconciled'].includes(operation.status) ||
      (operation.status === 'cancelled' && operation.reason === 'restore_intent_retired')))
}

function regularActions(row: AccumulationDetail): AccumulationAction[] {
  if (row.holding_integrity === 'invalid') return []
  const pending = row.operations.find((operation) => operation.status === 'pending')
  if (!row.observations_initialized) {
    const entry = row.entry
    if (!entry || !['validating', 'paused', 'stopped'].includes(row.state) ||
      (!['pending', 'cancelled'].includes(entry.status) && !(entry.action === 'abandon_entry' && entry.status === 'applied'))) return []
    return [
      ...(!entry.declaration_invalid ? ['retry_entry' as const] : []),
      ...((entry.source === 'csv' || (row.state === 'stopped' && entry.declaration_invalid)) ? ['correct_import' as const] : []),
      ...(row.state !== 'stopped' ? ['abandon_entry' as const] : []),
    ]
  }
  if (row.state === 'closing') {
    return accumulationClosePredecessor(row) ? ['retry_close'] : []
  }
  if (pending) return []
  if (row.state === 'stopped' && !row.holding) return ['reactivate']
  if (!['enabled', 'paused', 'blocked'].includes(row.state)) return []
  const actions: AccumulationAction[] = row.state === 'paused' ? ['resume'] : ['pause']
  if (row.state !== 'blocked') actions.push('switch_strategy')
  if (!row.holding && row.holding_integrity === 'unlinked' && row.inventory_restore_required !== true) actions.push('close')
  if (row.holding) {
    if (row.state === 'paused' && row.explicitly_paused) actions.push('adjust_inventory')
    if (row.state !== 'blocked') actions.push('sell_partial')
    actions.push('close')
  }
  return actions
}

export function accumulationActionCopy(action: AccumulationAction, symbol: string): string {
  const copy: Record<AccumulationAction, string> = {
    pause: 'Block new buys and settle any outstanding purchase.',
    resume: 'Revalidate the current strategy and allow new accumulation buys.',
    close: 'Block new buys and sell the managed quantity. Any unsellable remainder stays recorded in Closing.',
    retry_close: 'Retry selling the remaining managed quantity after the previous sale is reconciled. No coins will be bought to meet a minimum.',
    sell_partial: 'Sell only the entered base-asset quantity. The remaining holding stays managed.',
    reactivate: 'Revalidate this stopped registration and allow new buys with its pinned strategy.',
    retry_entry: 'Validate the current declaration against fresh wallet evidence and enable accumulation if it passes.',
    correct_import: 'Replace the staged declaration. It stays paused until you explicitly validate it.',
    abandon_entry: 'Leave these wallet coins unmanaged and keep a stopped registration. No coins will be sold. You can explicitly validate this declaration again later, or correct a CSV declaration before validation.',
    switch_strategy: 'Settle outstanding buys, validate the selected strategy version and start its observations from the current market. Previous purchase limits stay in force, and a paused holding stays paused.',
    repair_order: 'Look up the selected quarantined order in the configured exchange account. Apply only complete terminal evidence to the ledger. This cannot submit or cancel an order, enable buys, or sell a remainder. Missing evidence keeps the order quarantined.',
    retire_command: 'Retire only the selected interrupted command, which has no order attached. Coins, cost basis, strategy binding and purchase guards stay unchanged. Buying stays paused. A close remains in Closing and any sale needs a new explicit request. No exchange order is placed or cancelled.',
    rebind_account: 'Pause this holding and verify its historical order anchors and free inventory using the configured credentials. Rebind only if that evidence matches. This does not transfer coins, change inventory or enable buying. CSV-only holdings, missing order anchors and unresolved original-account work require separate repair.',
    restore_inventory: 'Restore recorded inventory link',
  acknowledge_settlement: 'Acknowledge a sale whose terminal fill and complete fees are already recorded. This updates only the interrupted command. It does not look up, place or cancel an order. Remaining coins stay in Closing after a full-close request and require an explicit retry. Buying remains paused.',
    declare_ownership: 'Explicitly declare that the recorded coins belong to you in the newly configured account. Fresh free wallet balance must cover the recorded quantity. This is an operator declaration, not proof of the original account. Buying remains paused, inventory and purchase guards are retained, and return history becomes unverified. No exchange order is submitted.',
    adjust_inventory: 'Record an inventory declaration after checking fresh free wallet balance. Add only the stated coins, or remove part using proportional remaining cost. No coins are traded, transferred or automatically adopted. Order history and purchase guards stay recorded; buying stays paused. Unknown acquisition cost stays unknown, and this correction is not an exchange fill.',
  }
  return `${symbol}: ${copy[action]}`
}

export function accumulationReason(reason: string | null): string {
  return reason ? reason.toLowerCase().replaceAll('_', ' ') : 'No additional wait reason'
}
