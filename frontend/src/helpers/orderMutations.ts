export type OrderMutationStatus =
    | 'applied'
    | 'deduplicated'
    | 'rejected'
    | 'stale'
    | 'indeterminate'
    | 'quarantined'

export interface OrderMutationResult {
    operation_id: string
    symbol: string
    action: string
    status: OrderMutationStatus
    reason_code: string
    user_message: string
    exchange_order_id: string | null
    client_order_id: string | null
    persisted_execution_id: string | null
}

export interface OrderMutationResponse {
    result: string
    mutation?: OrderMutationResult
}

let fallbackOperationSequence = 0

export function createOrderOperationId(action: string): string {
    const normalizedAction = action.replace(/[^A-Za-z0-9._:-]/g, '_')
    const randomId =
        globalThis.crypto?.randomUUID?.().replaceAll('-', '') ??
        `${Date.now().toString(36)}-${(++fallbackOperationSequence).toString(36)}`
    return `${normalizedAction}-${randomId}`.slice(0, 64)
}

export function orderMutationApplied(
    response: OrderMutationResponse,
    legacyResult: string,
): boolean {
    if (response.mutation) {
        return (
            response.mutation.status === 'applied' ||
            response.mutation.status === 'deduplicated'
        )
    }
    return response.result === legacyResult
}

export function orderMutationFailureMessage(
    response: OrderMutationResponse,
    fallback: string,
): string {
    return response.mutation?.user_message || fallback
}
