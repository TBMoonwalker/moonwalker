import { defineStore } from 'pinia'

export type OpenTradeRow = {
  id: number
  symbol: string
  deal_id?: string | null
  execution_history_complete?: boolean
  amount: number | string
  cost: number | string
  profit: number | string
  profit_percent: number
  current_price: number | string
  tp_price: number | string
  avg_price: number | string
  so_count: number
  open_date: string
  baseorder: OrderData
  safetyorder: Array<OrderData>
  precision: number
  unsellable_amount?: number
  unsellable_reason?: string | null
  unsellable_min_notional?: number | null
  unsellable_estimated_notional?: number | null
  unsellable_since?: string | null
  key: number
}

export type ClosedTradeRow = {
  id: number
  symbol: string
  deal_id?: string | null
  campaign_id?: string | null
  execution_history_complete: boolean
  amount: number | string
  cost: number | string
  tp_price: number | string
  avg_price: number | string
  profit: number | string
  profit_percent: number | string
  so_count: number
  open_date: string
  duration: string
  close_date: string
  close_reason?: string | null
  precision: number
  key: number
}

export type WaitingCampaignRow = {
  campaign_id: string
  symbol: string
  state: string
  sidestep_count: number
  last_exit_reason?: string | null
  cooldown_until?: string | null
  last_transition_at: string
  tp_percent: number
  gate_status: string
  gate_detail: string
  last_long_signal_at?: string | null
  key: string
}

export type UnsellableTradeRow = {
  id: number
  symbol: string
  deal_id?: string | null
  execution_history_complete?: boolean
  amount: number | string
  cost: number | string
  profit: number | string
  profit_percent: number | string
  so_count: number
  current_price: number | string
  avg_price: number | string
  open_date: string
  unsellable_reason?: string | null
  unsellable_min_notional?: number | null
  unsellable_estimated_notional?: number | null
  unsellable_since?: string | null
  key: number
}

export type OrderData = {
  id: number
  timestamp: string
  ordersize: number
  amount: number
  symbol: string
  price: number
  so_percentage?: number
}

export type TradeExecutionRow = {
  id: number
  deal_id: string
  symbol: string
  side: 'buy' | 'sell'
  role: string
  timestamp: string
  price: number
  amount: number
  ordersize: number
  fee: number
  order_id?: string | null
  order_type?: string | null
  order_count?: number | null
  so_percentage?: number | null
}

function isFloat(val: any): boolean {
  return typeof val === 'number' && Number.isFinite(val) && !Number.isInteger(val)
}

function formatDecimal(
  value: number,
  fallbackPrecision = 2,
  maxPrecision = 6
): string {
  if (!Number.isFinite(value)) {
    return String(value)
  }
  const actualPrecision = isFloat(value)
    ? value.toString().split('.')[1]?.length ?? fallbackPrecision
    : fallbackPrecision
  const precision = Math.min(maxPrecision, Math.max(fallbackPrecision, actualPrecision))
  return value.toFixed(precision)
}

function formatDuration(raw: string): string {
  try {
    const duration = JSON.parse(raw)
    if (duration['days'] !== 0) {
      return duration['days'] + ' days'
    }
    if (duration['hours'] !== 0) {
      return duration['hours'] + ' hours'
    }
    if (duration['minutes'] !== 0) {
      return duration['minutes'] + ' minutes'
    }
    if (duration['seconds'] !== 0) {
      return duration['seconds'] + ' seconds'
    }
    return 'na'
  } catch {
    return 'na'
  }
}

export const useTradesStore = defineStore('trades', {
  state: () => ({
    openTrades: [] as OpenTradeRow[],
    closedTrades: [] as ClosedTradeRow[],
    unsellableTrades: [] as UnsellableTradeRow[],
    waitingCampaigns: [] as WaitingCampaignRow[]
  }),
  actions: {
    setOpenTrades(raw: any[]) {
      this.openTrades = raw.map((val: any) => {
        const amountPrecision = isFloat(val.amount)
          ? val.amount.toString().split('.')[1].length
          : 0
        const costPrecision = isFloat(val.cost)
          ? val.cost.toString().split('.')[1].length
          : 0
        const tpPrecision = isFloat(val.tp_price)
          ? val.tp_price.toString().split('.')[1].length
          : 0
        const avgPrecision = isFloat(val.avg_price)
          ? val.avg_price.toString().split('.')[1].length
          : 0
        const currentPrecision = isFloat(val.current_price)
          ? val.current_price.toString().split('.')[1].length
          : 0

        return {
          ...val,
          cost: val.cost.toFixed(costPrecision),
          profit: val.profit.toFixed(2),
          amount: val.amount.toFixed(amountPrecision),
          current_price: val.current_price.toFixed(currentPrecision),
          tp_price: val.tp_price.toFixed(tpPrecision),
          avg_price: val.avg_price.toFixed(avgPrecision),
          so_count: Array.isArray(val.safetyorders) ? val.safetyorders.length : val.so_count,
          key: val.id,
          open_date: String(val.open_date ?? ''),
          deal_id: val.deal_id ?? null,
          execution_history_complete: Boolean(val.execution_history_complete ?? true),
          safetyorder: val.safetyorders,
          precision: currentPrecision,
          unsellable_amount: Number(val.unsellable_amount ?? 0),
          unsellable_reason: val.unsellable_reason ?? null,
          unsellable_min_notional:
            val.unsellable_min_notional === null || val.unsellable_min_notional === undefined
              ? null
              : Number(val.unsellable_min_notional),
          unsellable_estimated_notional:
            val.unsellable_estimated_notional === null || val.unsellable_estimated_notional === undefined
              ? null
              : Number(val.unsellable_estimated_notional),
          unsellable_since: val.unsellable_since ?? null
        }
      })
    },
    setClosedTrades(raw: any[]) {
      this.closedTrades = raw.map((val: any) => {
        const amountPrecision = isFloat(val.amount)
          ? val.amount.toString().split('.')[1].length
          : 0
        const tpPrecision = isFloat(val.tp_price)
          ? val.tp_price.toString().split('.')[1].length
          : 2
        const avgPrecision = isFloat(val.avg_price)
          ? val.avg_price.toString().split('.')[1].length
          : 2
        return {
          ...val,
          cost: formatDecimal(val.cost, 2),
          tp_price: formatDecimal(Number(val.tp_price ?? 0), 2, 8),
          avg_price: formatDecimal(Number(val.avg_price ?? 0), 2, 8),
          profit: formatDecimal(val.profit, 2),
          profit_percent: formatDecimal(val.profit_percent, 2),
          amount: val.amount.toFixed(amountPrecision),
          key: val.id,
          open_date: String(val.open_date ?? ''),
          close_date: String(val.close_date ?? ''),
          duration: formatDuration(val.duration),
          deal_id: val.deal_id ?? null,
          campaign_id: val.campaign_id ?? null,
          execution_history_complete: Boolean(val.execution_history_complete ?? false),
          close_reason: val.close_reason ?? null,
          precision: Math.max(tpPrecision, avgPrecision)
        }
      })
    },
    setUnsellableTrades(raw: any[]) {
      this.unsellableTrades = raw.map((val: any) => {
        const amountPrecision = isFloat(val.amount)
          ? val.amount.toString().split('.')[1].length
          : 0
        return {
          ...val,
          cost: formatDecimal(Number(val.cost), 2),
          profit: formatDecimal(Number(val.profit), 2),
          profit_percent: formatDecimal(Number(val.profit_percent), 2),
          amount: Number(val.amount).toFixed(amountPrecision),
          current_price: formatDecimal(Number(val.current_price), 2, 8),
          avg_price: formatDecimal(Number(val.avg_price), 2, 8),
          key: val.id,
          open_date: String(val.open_date ?? ''),
          deal_id: val.deal_id ?? null,
          execution_history_complete: Boolean(val.execution_history_complete ?? false),
          unsellable_reason: val.unsellable_reason ?? null,
          unsellable_min_notional:
            val.unsellable_min_notional === null || val.unsellable_min_notional === undefined
              ? null
              : Number(val.unsellable_min_notional),
          unsellable_estimated_notional:
            val.unsellable_estimated_notional === null || val.unsellable_estimated_notional === undefined
              ? null
              : Number(val.unsellable_estimated_notional),
          unsellable_since: val.unsellable_since ?? null
        }
      })
    },
    setWaitingCampaigns(raw: any[]) {
      this.waitingCampaigns = raw.map((val: any) => ({
        campaign_id: String(val.campaign_id ?? ''),
        symbol: String(val.symbol ?? ''),
        state: String(val.state ?? ''),
        sidestep_count: Number(val.sidestep_count ?? 0),
        last_exit_reason: val.last_exit_reason ?? null,
        cooldown_until: val.cooldown_until ?? null,
        last_transition_at: String(val.last_transition_at ?? ''),
        tp_percent: Number(val.tp_percent ?? 0),
        gate_status: String(val.gate_status ?? ''),
        gate_detail: String(val.gate_detail ?? ''),
        last_long_signal_at: val.last_long_signal_at ?? null,
        key: String(val.campaign_id ?? ''),
      }))
    }
  }
})
