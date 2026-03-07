import { defineStore } from 'pinia'

export type OpenTradeRow = {
  id: number
  symbol: string
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
  amount: number | string
  cost: number | string
  profit: number | string
  profit_percent: number | string
  so_count: number
  duration: string
  close_date: string
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
    closedTrades: [] as ClosedTradeRow[]
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

        const date = new Date(Math.trunc(parseFloat(val.open_date)))

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
          open_date: date.toLocaleString(),
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
        const timestamp: number = Date.parse(val.close_date)
        const date = new Date(timestamp)

        return {
          ...val,
          cost: formatDecimal(val.cost, 2),
          profit: formatDecimal(val.profit, 2),
          profit_percent: formatDecimal(val.profit_percent, 2),
          amount: val.amount.toFixed(amountPrecision),
          key: val.id,
          close_date: date.toLocaleString(),
          duration: formatDuration(val.duration)
        }
      })
    }
  }
})
