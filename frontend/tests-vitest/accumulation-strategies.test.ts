import { effectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAccumulationStrategies } from '../src/composables/useAccumulationStrategies'
import type { AccumulationStrategy, AccumulationStrategyPage } from '../src/types/accumulation'

const api = vi.hoisted(() => ({ fetchAccumulationStrategies: vi.fn() }))
vi.mock('../src/api/accumulation', () => api)
const scopes: ReturnType<typeof effectScope>[] = []
function catalog() {
  const scope = effectScope()
  scopes.push(scope)
  return { scope, pager: scope.run(() => useAccumulationStrategies(() => 'Catalog unavailable'))! }
}
function page(ids: number[], cursor: number | null = null): AccumulationStrategyPage {
  return { versions: ids.map(id => ({ id }) as AccumulationStrategy), next_after_id: cursor,
    defaults: {} as AccumulationStrategyPage['defaults'], timeframes: [] }
}
function deferred() {
  let resolve!: (page: AccumulationStrategyPage) => void
  let reject!: (cause: unknown) => void
  const promise = new Promise<AccumulationStrategyPage>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
beforeEach(() => vi.resetAllMocks())
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()) })

describe('per-consumer accumulation strategy catalog', () => {
  it('deduplicates immutable versions within and across pages, and stops at exhaustion', async () => {
    api.fetchAccumulationStrategies.mockResolvedValueOnce(page([1, 1, 2], 2)).mockResolvedValueOnce(page([2, 3, 3]))
    const { pager } = catalog()
    await pager.load()
    await pager.load(true)
    await pager.load(true)
    expect(pager.versions.value.map(row => row.id)).toEqual([1, 2, 3])
    expect(api.fetchAccumulationStrategies.mock.calls).toEqual([[0], [2]])
  })

  it('retains the catalog and cursor after a failed page, and retries that page', async () => {
    api.fetchAccumulationStrategies.mockResolvedValueOnce(page([1], 1))
      .mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(page([2]))
    const { pager } = catalog()
    await pager.load()
    expect(await pager.load(true)).toBeNull()
    expect(pager.versions.value.map(row => row.id)).toEqual([1])
    expect(pager.cursor.value).toBe(1)
    expect(pager.error.value).toBe('Catalog unavailable')
    await pager.load(true)
    expect(api.fetchAccumulationStrategies.mock.calls).toEqual([[0], [1], [1]])
    expect(pager.error.value).toBe('')
    expect(pager.loading.value).toBe(false)
  })

  it('ignores concurrent requests and replaces pages on an explicit reload', async () => {
    const request = deferred()
    api.fetchAccumulationStrategies.mockReturnValueOnce(request.promise).mockResolvedValueOnce(page([9]))
    const { pager } = catalog()
    const pending = pager.load()
    expect(pager.loading.value).toBe(true)
    expect(await pager.load()).toBeNull()
    expect(await pager.load(true)).toBeNull()
    expect(api.fetchAccumulationStrategies).toHaveBeenCalledTimes(1)
    request.resolve(page([1], 1))
    await pending
    await pager.load()
    expect(pager.versions.value.map(row => row.id)).toEqual([9])
    expect(pager.cursor.value).toBeNull()
  })

  it.each(['success', 'failure'])('ignores a late %s after disposal', async outcome => {
    const request = deferred()
    api.fetchAccumulationStrategies.mockReturnValue(request.promise)
    const { pager, scope } = catalog()
    const pending = pager.load()
    scope.stop()
    if (outcome === 'success') request.resolve(page([1], 1))
    else request.reject(new Error('offline'))
    expect(await pending).toBeNull()
    expect(pager.versions.value).toEqual([])
    expect(pager.cursor.value).toBeNull()
    expect(pager.error.value).toBe('')
    expect(await pager.load()).toBeNull()
    expect(api.fetchAccumulationStrategies).toHaveBeenCalledTimes(1)
  })

  it('keeps catalogs and pending requests independent across views', async () => {
    const firstRequest = deferred()
    api.fetchAccumulationStrategies.mockReturnValueOnce(firstRequest.promise).mockResolvedValueOnce(page([7]))
    const first = catalog().pager
    const second = catalog().pager
    const pending = first.load()
    await second.load()
    expect(second.versions.value.map(row => row.id)).toEqual([7])
    expect(first.versions.value).toEqual([])
    firstRequest.resolve(page([1], 1))
    await pending
    expect(second.cursor.value).toBeNull()
    expect(first.cursor.value).toBe(1)
  })
})
