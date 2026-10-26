import { beforeEach, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { archivedDust } from '../src/helpers/archivedDust'
import { useTradesStore } from '../src/stores/trades'

beforeEach(() => setActivePinia(createPinia()))

it('preserves tiny exact dust and unknown cost through the normal Unsellable feed', () => {
    const accumulation_inventory_json = JSON.stringify({ schema_version: 1,
        inventory: { quantity: '0.0000000000000000001', remaining_cost: null } })
    expect(archivedDust(accumulation_inventory_json)).toEqual({ quantity: '0.0000000000000000001', remaining_cost: null })
    const store = useTradesStore()
    store.setUnsellableTrades([{ id: 1, amount: 1e-19, cost: 0, accumulation_inventory_json }])
    expect(store.unsellableTrades[0]?.amount).toBe('0.0000000000000000001')
    expect(store.unsellableTrades[0]?.cost).toBe('Unknown')
    expect(archivedDust('{')).toBeNull()
    expect(archivedDust(JSON.stringify({ schema_version: 1, inventory: { quantity: -1 } }))).toBeNull()
})
