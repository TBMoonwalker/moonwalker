export const TRADE_MODE_DYNAMIC_DCA = 'dynamic_dca'
export const TRADE_MODE_SIDESTEP = 'sidestep'

export const CLASSIC_DCA_TRADE_LIFECYCLE_MODE = 'classic_dca'
export const SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE = 'sidestep_reentry'

export type TradeMode =
    | typeof TRADE_MODE_DYNAMIC_DCA
    | typeof TRADE_MODE_SIDESTEP

export type TradeLifecycleMode =
    | typeof CLASSIC_DCA_TRADE_LIFECYCLE_MODE
    | typeof SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE

function parseBooleanFlag(value: unknown): boolean {
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
    return parseBooleanFlag(legacySidestepEnabled)
        ? SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE
        : CLASSIC_DCA_TRADE_LIFECYCLE_MODE
}

export function normalizeTradeMode(
    tradeMode: unknown,
    tradeLifecycleMode: unknown = null,
    dynamicDca: unknown = false,
    legacySidestepEnabled: unknown = false,
): TradeMode {
    const normalized = String(tradeMode ?? '').trim().toLowerCase()
    if (normalized === TRADE_MODE_DYNAMIC_DCA) {
        return TRADE_MODE_DYNAMIC_DCA
    }
    if (normalized === TRADE_MODE_SIDESTEP) {
        return TRADE_MODE_SIDESTEP
    }
    if (
        normalizeTradeLifecycleMode(
            tradeLifecycleMode,
            legacySidestepEnabled,
        ) === SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE
    ) {
        return TRADE_MODE_SIDESTEP
    }
    return TRADE_MODE_DYNAMIC_DCA
}

export function deriveLegacyTradeLifecycleMode(
    tradeMode: unknown,
): TradeLifecycleMode {
    return normalizeTradeMode(tradeMode) === TRADE_MODE_SIDESTEP
        ? SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE
        : CLASSIC_DCA_TRADE_LIFECYCLE_MODE
}

export function deriveLegacyDynamicDcaEnabled(tradeMode: unknown): boolean {
    return normalizeTradeMode(tradeMode) === TRADE_MODE_DYNAMIC_DCA
}

export function deriveLegacySidestepEnabled(
    tradeLifecycleModeOrTradeMode: unknown,
    legacySidestepEnabled: unknown = false,
): boolean {
    const normalized = String(tradeLifecycleModeOrTradeMode ?? '')
        .trim()
        .toLowerCase()
    if (
        normalized === TRADE_MODE_DYNAMIC_DCA ||
        normalized === TRADE_MODE_SIDESTEP
    ) {
        return normalized === TRADE_MODE_SIDESTEP
    }
    return (
        normalizeTradeLifecycleMode(
            tradeLifecycleModeOrTradeMode,
            legacySidestepEnabled,
        ) === SIDESTEP_REENTRY_TRADE_LIFECYCLE_MODE
    )
}

export function isDynamicTradeMode(
    tradeMode: unknown,
    tradeLifecycleMode: unknown = null,
    dynamicDca: unknown = false,
    legacySidestepEnabled: unknown = false,
): boolean {
    return (
        normalizeTradeMode(
            tradeMode,
            tradeLifecycleMode,
            dynamicDca,
            legacySidestepEnabled,
        ) === TRADE_MODE_DYNAMIC_DCA
    )
}

export function isSidestepTradeMode(
    tradeMode: unknown,
    tradeLifecycleMode: unknown = null,
    dynamicDca: unknown = false,
    legacySidestepEnabled: unknown = false,
): boolean {
    return (
        normalizeTradeMode(
            tradeMode,
            tradeLifecycleMode,
            dynamicDca,
            legacySidestepEnabled,
        ) === TRADE_MODE_SIDESTEP
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
