/** Exact archived quantities must not pass through float/precision formatting. */
export function archivedDust(value: unknown): { quantity: string; remaining_cost: string | null } | null {
    if (typeof value !== 'string') return null
    try {
        const document = JSON.parse(value)
        const inventory = document?.inventory
        const decimal = /^(?:0|[1-9]\d*)(?:\.\d+)?$/
        if (document?.schema_version !== 1 || typeof inventory?.quantity !== 'string' ||
            !decimal.test(inventory.quantity) || !(inventory.remaining_cost === null ||
            typeof inventory.remaining_cost === 'string' && decimal.test(inventory.remaining_cost))) return null
        return { quantity: inventory.quantity, remaining_cost: inventory.remaining_cost }
    } catch {
        return null
    }
}
