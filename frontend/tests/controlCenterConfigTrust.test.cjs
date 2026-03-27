const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { deriveControlCenterConfigTrustState } = loadFrontendModule(
    'src/control-center/configTrust.ts',
)

test('deriveControlCenterConfigTrustState reports checking and trusted states', () => {
    const checkingState = deriveControlCenterConfigTrustState({
        hasKnownNewerSnapshot: false,
        hasUnsavedChanges: false,
        isHydrated: false,
        latestKnownUpdatedAt: null,
        loadState: 'loading',
    })

    assert.deepEqual(checkingState, {
        kind: 'checking',
        summary:
            'Checking whether this page is using the latest saved configuration.',
        tone: 'info',
        updatedAt: null,
    })

    const trustedState = deriveControlCenterConfigTrustState({
        hasKnownNewerSnapshot: false,
        hasUnsavedChanges: false,
        isHydrated: true,
        latestKnownUpdatedAt: '2026-03-27T09:00:00Z',
        loadState: 'ready',
    })

    assert.deepEqual(trustedState, {
        kind: 'trusted',
        summary: 'This page is using the latest saved configuration.',
        tone: 'success',
        updatedAt: '2026-03-27T09:00:00Z',
    })
})

test('deriveControlCenterConfigTrustState distinguishes safe staleness from draft conflicts', () => {
    const staleButSafe = deriveControlCenterConfigTrustState({
        hasKnownNewerSnapshot: true,
        hasUnsavedChanges: false,
        isHydrated: true,
        latestKnownUpdatedAt: '2026-03-27T09:05:00Z',
        loadState: 'ready',
    })

    assert.equal(staleButSafe.kind, 'stale_but_safe')
    assert.equal(staleButSafe.tone, 'warning')
    assert.equal(staleButSafe.updatedAt, '2026-03-27T09:05:00Z')

    const draftConflict = deriveControlCenterConfigTrustState({
        hasKnownNewerSnapshot: true,
        hasUnsavedChanges: true,
        isHydrated: true,
        latestKnownUpdatedAt: '2026-03-27T09:05:00Z',
        loadState: 'ready',
    })

    assert.equal(draftConflict.kind, 'stale_with_draft_conflict')
    assert.equal(draftConflict.tone, 'warning')
    assert.match(draftConflict.summary, /discard local changes/i)
})
