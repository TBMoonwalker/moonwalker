import { ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchJson } from '../src/api/client'
import { useClosedTradeCount } from '../src/composables/useClosedTradeCount'

vi.mock('../src/api/client', () => ({ fetchJson: vi.fn() }))

afterEach(() => {
    vi.clearAllMocks()
})

describe('closed-trade title count', () => {
    it('uses the full server count and refreshes when the live page changes', async () => {
        const firstPage = ref<unknown>(Array.from({ length: 10 }, (_, id) => ({ id })))
        vi.mocked(fetchJson)
            .mockResolvedValueOnce({ result: 23 })
            .mockResolvedValueOnce({ result: 24 })

        const count = useClosedTradeCount(firstPage)
        await vi.waitFor(() => expect(count.value).toBe(23))
        expect(fetchJson).toHaveBeenCalledWith('/trades/closed/length')

        firstPage.value = Array.from({ length: 10 }, (_, id) => ({ id: id + 1 }))
        await vi.waitFor(() => expect(count.value).toBe(24))
    })

    it('does not present a page of ten as the total when the count is unavailable', async () => {
        const firstPage = ref<unknown>(Array.from({ length: 10 }, (_, id) => ({ id })))
        vi.mocked(fetchJson).mockRejectedValueOnce(new Error('offline'))

        const count = useClosedTradeCount(firstPage)
        await vi.waitFor(() => expect(fetchJson).toHaveBeenCalledOnce())
        expect(count.value).toBeNull()
    })
})
