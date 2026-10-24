import type { AccumulationOrderCheckpoint } from '../types/accumulation'
import type { TradeExecutionRow } from '../stores/trades'

export interface DeclaredPurchase {
  key: string
  deal_id: string
  symbol: string
  timestamp: string
  price: string
  amount: string
  ordersize: string | null
  fees: Record<string, string>
  fees_known: boolean
  provenance: 'csv_declaration'
}

export interface AccumulationOrderItem {
  key: string
  title: string
  timestamp?: string | number
  content?: string
  price?: number
  checkpoint?: AccumulationOrderCheckpoint
  base: boolean
}

function operationId(execution: TradeExecutionRow): string | undefined {
  try {
    const metadata = JSON.parse(execution.metadata_json ?? '{}')
    return typeof metadata?.accumulation?.operation_id === 'string' ? metadata.accumulation.operation_id : undefined
  } catch { return undefined }
}

/** Show only the active deal; retain previous cycles in their execution ledger. */
export function accumulationOrders(
  checkpoints: AccumulationOrderCheckpoint[], executions: TradeExecutionRow[], dealId?: string | null,
  fallback: Array<{ key: string; title: string; content: string; timestamp: string | number }> = [],
  declarations: DeclaredPurchase[] = [], declarationUnavailable = false,
): AccumulationOrderItem[] {
  checkpoints = checkpoints.filter(order => Boolean(dealId) && order.deal_id === dealId)
  executions = executions.filter(execution => Boolean(dealId) && execution.deal_id === dealId)
  const matched = new Set<number>()
  const seen = new Set<string>()
  declarations = declarations.filter(row => Boolean(dealId) && row.deal_id === dealId && row.provenance === 'csv_declaration')
  let buys = declarations.length
  let sales = 0
  const items: AccumulationOrderItem[] = [...declarations].sort((a, b) => Number(a.timestamp) - Number(b.timestamp)).map((row, index) => ({
    key: row.key, base: index === 0, title: index === 0 ? 'Base order · CSV' : `Accumulation order ${index} · CSV`,
    timestamp: row.timestamp, price: Number(row.price),
    content: `Order size: ${row.ordersize ?? 'Unknown'} | Amount: ${row.amount} | Price: ${row.price}`,
  }))
  for (const execution of [...executions].sort((a, b) => Number(a.timestamp) - Number(b.timestamp))) {
    const operation = operationId(execution)
    const checkpoint = operation ? checkpoints.find(order => order.placement_operation_id === operation && order.deal_id === execution.deal_id) : undefined
    const key = checkpoint ? `checkpoint-${checkpoint.checkpoint_id}` : operation ? `${execution.deal_id}-${execution.side}-${operation}` : `execution-${execution.id}`
    if (seen.has(key)) continue
    seen.add(key)
    if (checkpoint) matched.add(checkpoint.checkpoint_id)
    const updates = operation ? executions.filter(candidate => candidate.deal_id === execution.deal_id && candidate.side === execution.side && operationId(candidate) === operation) : [execution]
    const base = execution.side === 'buy' && ++buys === 1 && !declarationUnavailable
    items.push({ key, base, title: execution.side === 'buy' ? base ? 'Base order' : `Accumulation order ${declarationUnavailable ? buys : buys - 1}` : `Manual sale ${++sales}`, timestamp: execution.timestamp, checkpoint, price: updates.at(-1)?.price,
      content: checkpoint ? undefined : `Order size: ${updates.length === 1 ? execution.ordersize : 'Unknown'} | Amount: ${updates.length === 1 ? execution.amount : 'Unknown'} | Price: ${updates.at(-1)?.price ?? 'Unknown'}`,
    })
  }
  if (!declarationUnavailable && !items.length && fallback.length && !checkpoints.some(order => dealId && order.deal_id === dealId)) items.push(...fallback.map((item, index) => ({ ...item, title: index === 0 ? 'Base order' : `Accumulation order ${index}`, base: index === 0 })))
  for (const checkpoint of [...checkpoints].reverse()) {
    if (matched.has(checkpoint.checkpoint_id)) continue
    const base = checkpoint.side === 'buy' && !declarationUnavailable && !items.some(item => item.base)
    items.push({ key: `checkpoint-${checkpoint.checkpoint_id}`, base, checkpoint, title: base ? 'Base order' : `Accumulation ${checkpoint.side === 'buy' ? 'order' : 'manual sale'}` })
  }
  if (!items.some(item => item.base)) items.unshift({ key: 'registration', title: 'Entry registration', base: true })
  return items
}
