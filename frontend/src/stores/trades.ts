import { defineStore } from 'pinia'

export type OpenTradeRow = {
  id: number
  symbol: string
  deal_id?: string | null
  campaign_id?: string | null
  campaign_started_at?: string | null
  lifecycle_mode?: string | null
  exposure_state?: string | null
  sidestep_count?: number
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
  reserved_reentry_quote?: number
  waiting_reference_price?: number
  waiting_reference_amount?: number
  waiting_reference_quote?: number
  virtual_waiting_profit?: number
  virtual_waiting_profit_percent?: number
  last_transition_at?: string | null
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

export type WaitingCampaignRow = OpenTradeRow

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
    normalizeOpenTradeRow(val: any) {
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
        cost: Number(val.cost ?? 0).toFixed(costPrecision),
        profit: Number(val.profit ?? 0).toFixed(2),
        amount: Number(val.amount ?? 0).toFixed(amountPrecision),
        current_price: Number(val.current_price ?? 0).toFixed(currentPrecision),
        tp_price: Number(val.tp_price ?? 0).toFixed(tpPrecision),
        avg_price: Number(val.avg_price ?? 0).toFixed(avgPrecision),
        so_count: Array.isArray(val.safetyorders) ? val.safetyorders.length : Number(val.so_count ?? 0),
        key: Number(val.id ?? 0),
        open_date: String(val.open_date ?? ''),
        deal_id: val.deal_id ?? null,
        campaign_id: val.campaign_id ?? null,
        campaign_started_at: val.campaign_started_at ?? null,
        lifecycle_mode: val.lifecycle_mode ?? null,
        exposure_state: val.exposure_state ?? null,
        sidestep_count: Number(val.sidestep_count ?? 0),
        execution_history_complete: Boolean(val.execution_history_complete ?? true),
        safetyorder: Array.isArray(val.safetyorders) ? val.safetyorders : [],
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
        unsellable_since: val.unsellable_since ?? null,
        reserved_reentry_quote: Number(val.reserved_reentry_quote ?? 0),
        waiting_reference_price: Number(val.waiting_reference_price ?? 0),
        waiting_reference_amount: Number(val.waiting_reference_amount ?? 0),
        waiting_reference_quote: Number(val.waiting_reference_quote ?? 0),
        virtual_waiting_profit: Number(val.virtual_waiting_profit ?? 0),
        virtual_waiting_profit_percent: Number(val.virtual_waiting_profit_percent ?? 0),
        last_transition_at: val.last_transition_at ?? null
      }
    },
    setOpenTrades(raw: any[]) {
      this.openTrades = raw.map((val: any) => this.normalizeOpenTradeRow(val))
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
      this.waitingCampaigns = raw.map((val: any) => this.normalizeOpenTradeRow(val))
    }
  }
})
