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

export interface OrderOperationRegistry {
    acquire(key: string, action: string): string
    release(key: string): void
    get(key: string): string | null
}

let fallbackOperationSequence = 0

export function createOrderOperationId(action: string): string {
    const normalizedAction = action.replace(/[^A-Za-z0-9._:-]/g, '_')
    const randomId =
        globalThis.crypto?.randomUUID?.().replaceAll('-', '') ??
        `${Date.now().toString(36)}-${(++fallbackOperationSequence).toString(36)}`
    return `${normalizedAction}-${randomId}`.slice(0, 64)
}

export function createOrderOperationRegistry(): OrderOperationRegistry {
    const operations = new Map<string, string>()
    return {
        acquire(key: string, action: string): string {
            const normalizedKey = key.trim().toLowerCase()
            const existing = operations.get(normalizedKey)
            if (existing) {
                return existing
            }
            const operationId = createOrderOperationId(action)
            operations.set(normalizedKey, operationId)
            return operationId
        },
        release(key: string): void {
            operations.delete(key.trim().toLowerCase())
        },
        get(key: string): string | null {
            return operations.get(key.trim().toLowerCase()) ?? null
        },
    }
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
    const mutation = response.mutation
    const message = mutation?.user_message || fallback
    if (
        mutation?.status === 'indeterminate' ||
        mutation?.status === 'quarantined'
    ) {
        return `${message} Do not submit a new order. Operation ID: ${mutation.operation_id}`
    }
    return message
}

export function orderMutationRequiresReconciliation(
    response: OrderMutationResponse,
): boolean {
    return (
        response.mutation?.status === 'indeterminate' ||
        response.mutation?.status === 'quarantined'
    )
}
