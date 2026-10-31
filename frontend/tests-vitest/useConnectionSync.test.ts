import { describe, expect, it } from 'vitest'

import {
  deriveConnectionState,
  type ConnectionPhase,
  type SyncStreamView,
} from '../src/composables/useConnectionSync'

function stream(overrides: Partial<SyncStreamView> = {}): SyncStreamView {
  return {
    status: 'OPEN',
    fresh: true,
    hasReceivedData: true,
    isRecovery: true,
    ...overrides,
  }
}

function phaseOf(streams: SyncStreamView[]): ConnectionPhase {
  return deriveConnectionState(streams).phase
}

describe('deriveConnectionState', () => {
  it('reports connected with no feeds', () => {
    const state = deriveConnectionState([])
    expect(state.phase).toBe('connected')
    expect(state.connected).toBe(true)
    expect(state.label).toBe('Connected')
  })

  it('is connected when every recovery feed is open and fresh', () => {
    expect(phaseOf([
      stream({ isRecovery: true, status: 'OPEN', fresh: true }),
      stream({ isRecovery: true, status: 'OPEN', fresh: true }),
    ])).toBe('connected')
  })

  it('treats an empty supplementary feed as fine when the recovery feed is fresh', () => {
    expect(phaseOf([
      stream({ isRecovery: true, status: 'OPEN', fresh: true }),
      stream({ isRecovery: false, status: 'OPEN', hasReceivedData: false }),
    ])).toBe('connected')
  })

  it('is syncing when every socket is open but the authoritative feed is not fresh', () => {
    expect(phaseOf([
      stream({ isRecovery: true, status: 'OPEN', fresh: false, hasReceivedData: true }),
      stream({ isRecovery: false, status: 'OPEN', hasReceivedData: true }),
    ])).toBe('syncing')
  })

  it('is reconnecting when a socket is down but authoritative data was received', () => {
    expect(phaseOf([
      stream({ isRecovery: true, status: 'OPEN', fresh: true, hasReceivedData: true }),
      stream({ isRecovery: false, status: 'CLOSED', hasReceivedData: true }),
    ])).toBe('reconnecting')
  })

  it('is reconnecting when a recovery feed dropped after having data', () => {
    expect(phaseOf([
      stream({ isRecovery: true, status: 'CLOSED', fresh: false, hasReceivedData: true }),
    ])).toBe('reconnecting')
  })

  it('is connecting when a socket is down and no authoritative data has arrived yet', () => {
    expect(phaseOf([
      stream({ isRecovery: true, status: 'CONNECTING', fresh: false, hasReceivedData: false }),
      stream({ isRecovery: false, status: 'CONNECTING', hasReceivedData: false }),
    ])).toBe('connecting')
  })

  it('exposes connected only in the connected phase', () => {
    expect(deriveConnectionState([stream()]).connected).toBe(true)
    expect(deriveConnectionState([
      stream({ isRecovery: false, status: 'CLOSED', hasReceivedData: true }),
    ]).connected).toBe(false)
    expect(deriveConnectionState([
      stream({ isRecovery: true, status: 'OPEN', fresh: false, hasReceivedData: true }),
    ]).connected).toBe(false)
  })

  it('maps phases to user-facing labels', () => {
    expect(deriveConnectionState([]).label).toBe('Connected')
    expect(deriveConnectionState([
      stream({ isRecovery: true, status: 'OPEN', fresh: false, hasReceivedData: true }),
    ]).label).toBe('Syncing…')
    expect(deriveConnectionState([
      stream({ isRecovery: true, status: 'CLOSED', hasReceivedData: true }),
    ]).label).toBe('Reconnecting…')
    expect(deriveConnectionState([
      stream({ isRecovery: true, status: 'CONNECTING', hasReceivedData: false }),
    ]).label).toBe('Connecting…')
  })

  it('falls back to all feeds when none are marked as recovery', () => {
    expect(phaseOf([
      {
        status: 'OPEN',
        fresh: false,
        hasReceivedData: true,
        isRecovery: false,
      },
      {
        status: 'OPEN',
        fresh: false,
        hasReceivedData: true,
        isRecovery: false,
      },
    ])).toBe('connected')
  })
})
