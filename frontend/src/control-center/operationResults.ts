export interface OperationResult<TData = undefined> {
    status: 'success' | 'error' | 'blocked' | 'noop'
    message: string
    data?: TData
    statusCode?: number | null
    blockers?: unknown[]
    category?: string
}
