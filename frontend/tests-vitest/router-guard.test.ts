import type { RouteLocationNormalized } from 'vue-router'
import { createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchJson } from '../src/api/client'
import { createAppRouter } from '../src/router/index'
import { resetSharedConfigSnapshotState } from '../src/control-center/configSnapshotStore'
import { resolveControlCenterNavigation } from '../src/control-center/routerGuard'
import type { ControlCenterReadiness } from '../src/control-center/types'

vi.mock('../src/api/client', () => ({ fetchJson: vi.fn() }))
vi.mock('../src/views/TradesView.vue', () => ({ default: { name: 'TradesStub', template: '<div />' } }))
vi.mock('../src/views/ControlCenterView.vue', () => ({ default: { name: 'ControlCenterStub', template: '<div />' } }))
vi.mock('../src/views/AutopilotMemoryView.vue', () => ({ default: { name: 'AutopilotStub', template: '<div />' } }))
vi.mock('../src/views/BacktestView.vue', () => ({ default: { name: 'BacktestStub', template: '<div />' } }))
vi.mock('../src/views/MonitoringView.vue', () => ({ default: { name: 'MonitoringStub', template: '<div />' } }))
vi.mock('../src/views/StatisticsView.vue', () => ({ default: { name: 'StatisticsStub', template: '<div />' } }))

const completeReadiness: ControlCenterReadiness = {
  complete: true,
  firstRun: false,
  attentionNeeded: false,
  blockers: [],
  nextMode: 'setup',
  nextTarget: 'live-activation',
  dryRun: true,
  configuredEssentials: 7,
}

function route(
  name: string,
  query: Record<string, unknown> = {},
): RouteLocationNormalized {
  return { name, query } as unknown as RouteLocationNormalized
}

describe('resolveControlCenterNavigation', () => {
  it('redirects incomplete setups to their next task', () => {
    const result = resolveControlCenterNavigation(route('trades'), {
      loadError: null,
      readiness: {
        ...completeReadiness,
        complete: false,
        firstRun: true,
        blockers: [
          {
            key: 'exchange',
            title: 'Exchange missing',
            description: 'Choose an exchange.',
            mode: 'setup',
            target: 'exchange',
          },
        ],
        nextMode: 'setup',
        nextTarget: 'exchange',
      },
    })

    expect(result).toEqual({
      name: 'controlCenter',
      query: { mode: 'setup', target: 'exchange' },
      replace: true,
    })
  })

  it('does not loop when the incomplete route is already canonical', () => {
    const result = resolveControlCenterNavigation(
      route('controlCenter', { mode: 'setup', target: 'exchange' }),
      {
        loadError: null,
        readiness: {
          ...completeReadiness,
          complete: false,
          firstRun: true,
          nextMode: 'setup',
          nextTarget: 'exchange',
        },
      },
    )

    expect(result).toBe(true)
  })

  it('normalizes a healthy Control Center route', () => {
    const result = resolveControlCenterNavigation(
      route('controlCenter', { mode: 'invalid', target: 'dca' }),
      { loadError: null, readiness: completeReadiness },
    )

    expect(result).toEqual({
      name: 'controlCenter',
      query: { mode: 'setup', target: 'dca' },
      replace: true,
    })
  })

  it('allows non-Control-Center routes after readiness or load failure', () => {
    expect(
      resolveControlCenterNavigation(route('stats'), {
        loadError: 'offline',
        readiness: completeReadiness,
      }),
    ).toBe(true)
  })

  it('allows Strategy Builder as an explicit escape when only the accumulation pin is missing', () => {
    const readiness: ControlCenterReadiness = {
      ...completeReadiness, complete: false, attentionNeeded: true, nextTarget: 'dca',
      blockers: [{ key: 'accumulation_strategy_version_id', title: 'Missing strategy', description: 'Select a version', mode: 'setup', target: 'dca' }],
    }
    expect(resolveControlCenterNavigation(route('controlCenter', { mode: 'strategy-builder', target: 'strategy-builder' }), { loadError: null, readiness })).toBe(true)
    const blocked = { ...readiness, blockers: [...readiness.blockers, { key: 'exchange', title: 'Missing exchange', description: 'Select exchange', mode: 'setup' as const, target: 'exchange' as const }] }
    expect(resolveControlCenterNavigation(route('controlCenter', { mode: 'strategy-builder' }), { loadError: null, readiness: blocked })).not.toBe(true)
  })
})

describe('createAppRouter config revalidation', () => {
  let serverRevision = 1
  let serverUpdatedAt = '2026-03-27T09:00:00Z'
  const fetchUrls: string[] = []

  beforeEach(() => {
    serverRevision = 1
    serverUpdatedAt = '2026-03-27T09:00:00Z'
    fetchUrls.length = 0
    vi.mocked(fetchJson).mockImplementation(async (url: string) => {
      fetchUrls.push(String(url))
      if (String(url).endsWith('/config/all')) {
        return { dry_run: true, config_updated_at: serverUpdatedAt, config_revision: serverRevision }
      }
      return { updated_at: serverUpdatedAt, config_revision: serverRevision }
    })
    resetSharedConfigSnapshotState()
  })

  afterEach(() => {
    resetSharedConfigSnapshotState()
  })

  // Value: protects=the core promise of this branch at the router seam:
  // the full /config/all is fetched once and every later navigation only
  // runs the lightweight /config/freshness revalidation, refetching the
  // full config only when a newer snapshot is detected;
  // fails_when=a regression calls the full load per navigation or misses
  // the stale refetch; why_new=the existing tests only cover the pure
  // resolveControlCenterNavigation helper, not the guard wiring;
  // seam=none; no_claim=real HTTP (fetchJson is mocked), view rendering
  // (views are stubbed), readiness side effects (redirects are allowed).
  it('fetches the full config once, then revalidates freshness per navigation', async () => {
    const router = createAppRouter(createMemoryHistory())

    await router.push('/trades')
    await router.push('/monitoring')

    expect(fetchUrls.filter(url => url.endsWith('/config/all'))).toHaveLength(1)
    expect(fetchUrls.filter(url => url.endsWith('/config/freshness')).length).toBeGreaterThanOrEqual(2)

    // The server publishes a newer snapshot between navigations.
    serverRevision = 2
    serverUpdatedAt = '2026-03-27T09:05:00Z'

    await router.push('/stats')

    expect(fetchUrls.filter(url => url.endsWith('/config/all'))).toHaveLength(2)
  })
})
