import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'

import { fetchJson } from '../src/api/client'
import { usePagedTradeFeed } from '../src/composables/usePagedTradeFeed'

vi.mock('../src/api/client', () => ({ fetchJson: vi.fn() }))

afterEach(() => {
  vi.resetAllMocks()
})

it('loads the first closed-trade page while the live feed is empty', async () => {
  vi.mocked(fetchJson).mockImplementation(async (path) => {
    if (path === '/trades/closed/length') return { result: 2 }
    if (path === '/trades/closed/0') return { result: [1, 2] }
    throw new Error(`Unexpected path: ${path}`)
  })

  const liveRows = ref<number[]>([])
  const feed = useFeedHarness(liveRows)
  await flushPromises()

  expect(feed.pagedRows.value).toEqual([1, 2])
  expect(fetchJson).toHaveBeenCalledWith('/trades/closed/0')

  liveRows.value = [3, 4]
  await flushPromises()
  expect(feed.pagedRows.value).toEqual([3, 4])
})

it('keeps newer live rows when the fallback request finishes later', async () => {
  let resolvePage!: (value: { result: number[] }) => void
  const pageRequest = new Promise<{ result: number[] }>((resolve) => {
    resolvePage = resolve
  })
  vi.mocked(fetchJson).mockImplementation(async (path) => {
    if (path === '/trades/closed/length') return { result: 2 }
    if (path === '/trades/closed/0') return pageRequest
    throw new Error(`Unexpected path: ${path}`)
  })

  const liveRows = ref<number[]>([])
  const feed = useFeedHarness(liveRows)
  await flushPromises()
  expect(fetchJson).toHaveBeenCalledWith('/trades/closed/0')

  liveRows.value = [3, 4]
  await flushPromises()
  resolvePage({ result: [1, 2] })
  await flushPromises()

  expect(feed.pagedRows.value).toEqual([3, 4])
})

it('discards a stale first-page result resolved after the page advanced', async () => {
  let resolveFirstPage!: (value: { result: number[] }) => void
  const firstPageRequest = new Promise<{ result: number[] }>((resolve) => {
    resolveFirstPage = resolve
   })
  vi.mocked(fetchJson).mockImplementation(async (path) => {
    if (path === '/trades/closed/length') return { result: 2 }
    if (path === '/trades/closed/0') return firstPageRequest
    return { result: [] }
   })

  const feed = useFeedHarness(ref<number[]>([]))
  await flushPromises()
  expect(fetchJson).toHaveBeenCalledWith('/trades/closed/0')
  expect(feed.pagedRows.value).toEqual([])

  feed.pagination.page = 2
  resolveFirstPage({ result: [7, 8] })
  await flushPromises()

  expect(feed.pagedRows.value).toEqual([])
})

function useFeedHarness(liveRows: ReturnType<typeof ref<number[]>>) {
  let feed!: ReturnType<typeof usePagedTradeFeed<number>>
  mount(
    defineComponent({
      setup() {
        feed = usePagedTradeFeed<number>({
          liveRows,
          normalizeRows: (rows) => rows as number[],
          lengthEndpoint: '/trades/closed/length',
          pageEndpoint: (offset) => `/trades/closed/${offset}`,
          itemLabel: 'trades',
        })
        return () => h('div')
      },
    }),
  )
  return feed
}
