export interface CapitalBudgetPreviewInput {
    baseOrderSize: number | null
    maxSafetyOrders: number | null
    reserveSafetyOrders: boolean
    bufferPercent: number | null
    dynamicDcaEnabled: boolean
    openTrades: unknown
}

/** Mirror the backend baseline reserve and incremental base-order check. */
export function calculateCapitalBudgetPreview(input: CapitalBudgetPreviewInput) {
    const { baseOrderSize, maxSafetyOrders } = input
    if (
        baseOrderSize === null || !Number.isFinite(baseOrderSize) || baseOrderSize <= 0 ||
        maxSafetyOrders === null || !Number.isInteger(maxSafetyOrders) || maxSafetyOrders < 0
    ) {
        return null
    }

    const roundQuote = (value: number) => Math.round(value * 1e8) / 1e8
    const rawBuffer = input.dynamicDcaEnabled ? input.bufferPercent ?? 0 : 0
    if (!Number.isFinite(rawBuffer) || rawBuffer < 0) return null
    // The existing API accepts ratios up to 1 and whole percentages above 1.
    const bufferRatio = rawBuffer > 1 ? rawBuffer / 100 : rawBuffer
    const newDealReserve = input.reserveSafetyOrders
        ? roundQuote(baseOrderSize * maxSafetyOrders)
        : 0
    const newDealBaseline = roundQuote(baseOrderSize + newDealReserve)
    const newDealRequirement = roundQuote(newDealBaseline * (1 + bufferRatio))

    let openDealCount: number | null = null
    let remainingSafetyOrders: number | null = null
    if (Array.isArray(input.openTrades)) {
        const activeTrades = input.openTrades.filter((trade) => !(
            Number(trade?.unsellable_amount ?? 0) > 0 && trade?.unsellable_reason
        ))
        if (activeTrades.every((trade) => trade && typeof trade === 'object' &&
            Number.isInteger(Number(trade.so_count ?? 0)) && Number(trade.so_count ?? 0) >= 0)) {
            openDealCount = activeTrades.length
            remainingSafetyOrders = activeTrades.reduce((total, trade) =>
                total + Math.max(0, maxSafetyOrders - Number(trade.so_count ?? 0)), 0)
        }
    }

    return {
        baseOrderSize,
        bufferPercent: bufferRatio * 100,
        openDealCount,
        remainingSafetyOrders,
        openDealReserve: !input.reserveSafetyOrders ? 0 : remainingSafetyOrders === null
            ? null : roundQuote(baseOrderSize * remainingSafetyOrders),
        newDealReserve,
        newDealBaseline,
        newDealBuffer: roundQuote(newDealRequirement - newDealBaseline),
        newDealRequirement,
    }
}
