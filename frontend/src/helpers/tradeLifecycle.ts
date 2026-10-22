export const TRADE_MODE_DYNAMIC_DCA = 'dynamic_dca'
export const TRADE_MODE_ACCUMULATION = 'accumulation'

export type TradeMode = typeof TRADE_MODE_DYNAMIC_DCA | typeof TRADE_MODE_ACCUMULATION | 'unsupported'

export function normalizeTradeMode(tradeMode: unknown): TradeMode {
    if (tradeMode === TRADE_MODE_ACCUMULATION) return TRADE_MODE_ACCUMULATION
    if (typeof tradeMode === 'string' && !['', 'dynamic_dca', 'classic_dca', 'sidestep'].includes(tradeMode)) return 'unsupported'
    return TRADE_MODE_DYNAMIC_DCA
}

export function isDynamicTradeMode(tradeMode: unknown): boolean {
    return normalizeTradeMode(tradeMode) === TRADE_MODE_DYNAMIC_DCA
}
