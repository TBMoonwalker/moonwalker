import { describe, expect, it } from 'vitest'
import { resolveBudgetAllocation } from '../src/helpers/portfolioExposure'

const baseInput = {
    effectiveBudget: 1000,
    fundsLocked: 400,
    openTradeReserve: 100,
    pendingQuote: 50,
    tradableQuote: 300,
    exchangeFree: 700,
    reason: 'ok',
}

describe('resolveBudgetAllocation', () => {
    it('scales every segment to the effective capital budget', () => {
        const allocation = resolveBudgetAllocation(baseInput)

        expect(allocation).toMatchObject({
            limit: 1000,
            locked: 400,
            reserved: 150,
            tradable: 300,
            otherExchangeFree: 400,
            lockedPercent: 40,
            reservedPercent: 15,
            tradablePercent: 30,
            usedPercent: 55,
        })
    })

    it('caps tradable funds at exchange free and the unused budget', () => {
        expect(resolveBudgetAllocation({ ...baseInput, exchangeFree: 80 })?.tradable).toBe(80)
        expect(resolveBudgetAllocation({ ...baseInput, tradableQuote: 900 })?.tradable).toBe(450)
    })

    it('keeps an exceeded budget visually bounded and reports the overage', () => {
        const allocation = resolveBudgetAllocation({
            ...baseInput,
            fundsLocked: 900,
            openTradeReserve: 200,
            reason: 'capital_budget_exceeded',
        })

        expect(allocation?.exceeded).toBe(true)
        expect(allocation?.tradable).toBe(0)
        expect(allocation?.lockedPercent).toBe(90)
        expect(allocation?.reservedPercent).toBe(10)
    })

    it('does not invent an allocation when the budget is unconfigured or unavailable', () => {
        expect(resolveBudgetAllocation({ ...baseInput, reason: 'capital_budget_unconfigured' })).toBeNull()
        expect(resolveBudgetAllocation({ ...baseInput, fundsLocked: null })).toBeNull()
    })
})
