export const CLASSIC_DCA_TRADE_LIFECYCLE_MODE = 'classic_dca'
export const SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE = 'sidestep_reentry'

export type TradeLifecycleMode =
    | typeof CLASSIC_DCA_TRADE_LIFECYCLE_MODE
    | typeof SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE

export function normalizeTradeLifecycleMode(
    tradeLifecycleMode: unknown,
    legacySidestepEnabled: unknown = false,
): TradeLifecycleMode {
    const normalized = String(tradeLifecycleMode ?? '').trim().toLowerCase()
    if (normalized === SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE) {
        return SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE
    }
    if (normalized === CLASSIC_DCA_TRADE_LIFECYCLE_MODE) {
        return CLASSIC_DCA_TRADE_LIFECYCLE_MODE
    }
    return parseLegacySidestepEnabled(legacySidestepEnabled)
        ? SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE
        : CLASSIC_DCA_TRADE_LIFECYCLE_MODE
}

export function deriveLegacySidestepEnabled(
    tradeLifecycleMode: unknown,
    legacySidestepEnabled: unknown = false,
): boolean {
    return (
        normalizeTradeLifecycleMode(
            tradeLifecycleMode,
            legacySidestepEnabled,
        ) === SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE
    )
}

export function isSidestepTradeLifecycleMode(
    tradeLifecycleMode: unknown,
    legacySidestepEnabled: unknown = false,
): boolean {
    return deriveLegacySidestepEnabled(
        tradeLifecycleMode,
        legacySidestepEnabled,
    )
}

export function isClassicTradeLifecycleMode(
    tradeLifecycleMode: unknown,
    legacySidestepEnabled: unknown = false,
): boolean {
    return !isSidestepTradeLifecycleMode(
        tradeLifecycleMode,
        legacySidestepEnabled,
    )
}

function parseLegacySidestepEnabled(value: unknown): boolean {
    if (typeof value === 'boolean') {
        return value
    }
    if (typeof value === 'string') {
        const normalized = value.trim().toLowerCase()
        if (['true', '1', 'yes', 'on'].includes(normalized)) {
            return true
        }
        if (['false', '0', 'no', 'off', ''].includes(normalized)) {
            return false
        }
    }
    return Boolean(value)
}
