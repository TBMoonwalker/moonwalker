export interface BudgetAllocationInput {
    effectiveBudget: number | null
    fundsLocked: number | null
    openTradeReserve: number | null
    pendingQuote: number | null
    tradableQuote: number | null
    exchangeFree: number
    reason: string | null
}

export interface BudgetAllocation {
    limit: number
    locked: number
    reserved: number
    tradable: number
    unallocated: number
    otherExchangeFree: number
    lockedPercent: number
    reservedPercent: number
    tradablePercent: number
    unallocatedPercent: number
    usedPercent: number
    exceeded: boolean
}

export function resolveBudgetAllocation(input: BudgetAllocationInput): BudgetAllocation | null {
    const { effectiveBudget, fundsLocked, openTradeReserve, pendingQuote } = input
    if (
        !['ok', 'capital_budget_exceeded'].includes(input.reason ?? '') ||
        effectiveBudget === null || !Number.isFinite(effectiveBudget) || effectiveBudget <= 0 ||
        fundsLocked === null || !Number.isFinite(fundsLocked) ||
        openTradeReserve === null || !Number.isFinite(openTradeReserve) ||
        pendingQuote === null || !Number.isFinite(pendingQuote)
    ) {
        return null
    }

    const limit = effectiveBudget
    const locked = Math.max(0, fundsLocked)
    const reserved = Math.max(0, openTradeReserve) + Math.max(0, pendingQuote)
    const remaining = Math.max(0, limit - locked - reserved)
    const exchangeFree = Math.max(0, input.exchangeFree)
    const tradable = Math.min(
        remaining,
        exchangeFree,
        Math.max(0, input.tradableQuote ?? 0),
    )
    const unallocated = Math.max(0, remaining - tradable)
    const visibleLocked = Math.min(locked, limit)
    const visibleReserved = Math.min(reserved, Math.max(0, limit - visibleLocked))

    return {
        limit,
        locked,
        reserved,
        tradable,
        unallocated,
        otherExchangeFree: Math.max(0, exchangeFree - tradable),
        lockedPercent: (visibleLocked / limit) * 100,
        reservedPercent: (visibleReserved / limit) * 100,
        tradablePercent: (tradable / limit) * 100,
        unallocatedPercent: (unallocated / limit) * 100,
        usedPercent: Math.round(((locked + reserved) / limit) * 100),
        exceeded: locked + reserved > limit,
    }
}
