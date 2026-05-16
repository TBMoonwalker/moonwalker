export const TRADE_MODE_DYNAMIC_DCA = 'dynamic_dca'
export const TRADE_MODE_SIDESTEP = 'sidestep'

export type TradeMode =
    | typeof TRADE_MODE_DYNAMIC_DCA
    | typeof TRADE_MODE_SIDESTEP

export function normalizeTradeMode(tradeMode: unknown): TradeMode {
    const normalized = String(tradeMode ?? '').trim().toLowerCase()
    if (normalized === TRADE_MODE_DYNAMIC_DCA) {
        return TRADE_MODE_DYNAMIC_DCA
    }
    if (normalized === TRADE_MODE_SIDESTEP) {
        return TRADE_MODE_SIDESTEP
    }
    return TRADE_MODE_DYNAMIC_DCA
}

export function isDynamicTradeMode(tradeMode: unknown): boolean {
    return normalizeTradeMode(tradeMode) === TRADE_MODE_DYNAMIC_DCA
}

export function isSidestepTradeMode(tradeMode: unknown): boolean {
    return normalizeTradeMode(tradeMode) === TRADE_MODE_SIDESTEP
}
