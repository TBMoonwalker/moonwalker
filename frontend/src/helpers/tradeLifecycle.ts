export const TRADE_MODE_DYNAMIC_DCA = 'dynamic_dca'

export type TradeMode = typeof TRADE_MODE_DYNAMIC_DCA

export function normalizeTradeMode(tradeMode: unknown): TradeMode {
    return TRADE_MODE_DYNAMIC_DCA
}

export function isDynamicTradeMode(tradeMode: unknown): boolean {
    return normalizeTradeMode(tradeMode) === TRADE_MODE_DYNAMIC_DCA
}
