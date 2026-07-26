import type { RouteLocationNormalized } from 'vue-router'
import { describe, expect, it } from 'vitest'

import { resolveControlCenterNavigation } from '../src/control-center/routerGuard'
import type { ControlCenterReadiness } from '../src/control-center/types'

const completeReadiness: ControlCenterReadiness = {
  complete: true,
  firstRun: false,
  attentionNeeded: false,
  blockers: [],
  nextMode: 'overview',
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
})
