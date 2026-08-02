import { describe, expect, it } from 'vitest'

import {
    createOrderOperationId,
    orderMutationApplied,
    orderMutationFailureMessage,
    type OrderMutationResponse,
    type OrderMutationStatus,
} from '../src/helpers/orderMutations'

function response(status: OrderMutationStatus): OrderMutationResponse {
    return {
        result: '',
        mutation: {
            operation_id: 'operation-1',
            symbol: 'BTC/USDC',
            action: 'manual_sell',
            status,
            reason_code: status,
            user_message: `Outcome: ${status}`,
            exchange_order_id: null,
            client_order_id: null,
            persisted_execution_id: null,
        },
    }
}

describe('order mutation results', () => {
    it('creates a distinct bounded identity for each confirmed action', () => {
        const first = createOrderOperationId('manual_sell')
        const second = createOrderOperationId('manual_sell')

        expect(first).toMatch(/^manual_sell-[A-Za-z0-9._:-]+$/)
        expect(second).not.toBe(first)
        expect(first.length).toBeLessThanOrEqual(64)
    })

    it.each(['applied', 'deduplicated'] as const)(
        'treats %s as completed',
        (status) => {
            expect(orderMutationApplied(response(status), 'sell')).toBe(true)
        },
    )

    it.each([
        'rejected',
        'stale',
        'indeterminate',
        'quarantined',
    ] as const)('does not report %s as success', (status) => {
        expect(orderMutationApplied(response(status), 'sell')).toBe(false)
        expect(orderMutationFailureMessage(response(status), 'fallback')).toBe(
            `Outcome: ${status}`,
        )
    })

    it('supports the legacy response during rolling compatibility', () => {
        expect(orderMutationApplied({ result: 'sell' }, 'sell')).toBe(true)
        expect(
            orderMutationFailureMessage({ result: '' }, 'fallback'),
        ).toBe('fallback')
    })
})
