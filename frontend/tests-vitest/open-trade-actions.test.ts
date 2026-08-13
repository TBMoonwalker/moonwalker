import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MOONWALKER_OPERATION_HEADER } from '../src/api/client'
import { useOpenTradeActions } from '../src/composables/useOpenTradeActions'
import type { OpenTradeRow } from '../src/helpers/openTrades'
import type { OrderMutationStatus } from '../src/helpers/orderMutations'

const fetchJsonMock = vi.hoisted(() => vi.fn())

vi.mock('../src/api/client', () => ({
    fetchJson: fetchJsonMock,
    MOONWALKER_OPERATION_HEADER: 'X-Moonwalker-Operation-Id',
}))

function trade(): OpenTradeRow {
    return {
        id: 1,
        symbol: 'BTC/USDC',
        deal_id: 'deal-1',
        amount: 1,
        cost: 100,
        profit: 0,
        profit_percent: 0,
        current_price: 100,
        tp_price: 101,
        avg_price: 100,
        so_count: 0,
        open_date: '2026-08-02T00:00:00Z',
        baseorder: {
            id: 1,
            timestamp: '2026-08-02T00:00:00Z',
            ordersize: 100,
            amount: 1,
            symbol: 'BTC/USDC',
            price: 100,
        },
        safetyorder: [],
        precision: 8,
    }
}

function mutation(status: OrderMutationStatus) {
    return {
        result: '',
        mutation: {
            operation_id: 'server-operation',
            symbol: 'BTC/USDC',
            action: 'manual_buy',
            status,
            reason_code: status,
            user_message: `Buy outcome: ${status}`,
            exchange_order_id: null,
            client_order_id: null,
            persisted_execution_id: null,
        },
    }
}

describe('open trade order actions', () => {
    const dialogs: Array<Record<string, unknown>> = []
    const message = {
        error: vi.fn(),
        success: vi.fn(),
    }
    const dialog = {
        info: vi.fn((options: Record<string, unknown>) => {
            dialogs.push(options)
            return { loading: false }
        }),
        warning: vi.fn(),
    }

    beforeEach(() => {
        dialogs.length = 0
        fetchJsonMock.mockReset()
        message.error.mockReset()
        message.success.mockReset()
        dialog.info.mockClear()
        dialog.warning.mockClear()
    })

    it('reuses an indeterminate buy operation and releases it after success', async () => {
        fetchJsonMock
            .mockResolvedValueOnce(mutation('indeterminate'))
            .mockResolvedValueOnce(mutation('applied'))
            .mockResolvedValueOnce(mutation('applied'))
        const actions = useOpenTradeActions({
            availableFunds: ref(100),
            dialog: dialog as never,
            message: message as never,
        })

        actions.handleDealBuy(trade())
        await (dialogs[0].onPositiveClick as () => Promise<unknown>)()
        actions.handleDealBuy(trade())
        await (dialogs[1].onPositiveClick as () => Promise<unknown>)()
        actions.handleDealBuy(trade())
        await (dialogs[2].onPositiveClick as () => Promise<unknown>)()

        const operationIds = fetchJsonMock.mock.calls.map(
            ([, init]) => init.headers[MOONWALKER_OPERATION_HEADER],
        )
        expect(operationIds[1]).toBe(operationIds[0])
        expect(operationIds[2]).not.toBe(operationIds[0])
        expect(message.error).toHaveBeenCalledWith(
            expect.stringContaining('Buy outcome: indeterminate'),
            { duration: 0, closable: true },
        )
        expect(message.success).toHaveBeenCalledTimes(2)
    })
})
