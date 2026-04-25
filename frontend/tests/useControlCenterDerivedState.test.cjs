const assert = require('node:assert/strict')
const test = require('node:test')

const { ref } = require('vue')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterDerivedState } = loadFrontendModule(
    'src/composables/useControlCenterDerivedState.ts',
)

function createDerivedStateHarness(overrides = {}) {
    const loadRescueMessage = ref(null)
    const transitionIntent = ref(null)

    const options = {
        hasUnsavedChanges() {
            return false
        },
        loadRescueMessage,
        requestedMode() {
            return 'overview'
        },
        requestedTarget() {
            return 'signal'
        },
        snapshotStore: {
            hasKnownNewerSnapshot: ref(false),
            isHydrated: ref(true),
            latestKnownUpdatedAt: ref('2026-04-06T09:00:00Z'),
            loadError: ref(null),
            loadState: ref('ready'),
            snapshot: ref({
                timezone: 'Europe/Vienna',
                signal: 'asap',
                exchange: 'binance',
                timeframe: '1h',
                key: 'api-key',
                secret: 'api-secret',
                currency: 'USDT',
                max_bots: 2,
                bo: 20,
                capital_max_fund: 250,
                tp: 1.5,
                history_lookback_time: '180d',
                symbol_list: 'BTC/USDT',
                dry_run: true,
            }),
        },
        transitionIntent,
        ...overrides,
    }

    return {
        derivedState: useControlCenterDerivedState(options),
        loadRescueMessage,
        transitionIntent,
    }
}

test('derived state prefers explicit load rescue messages and route normalization', () => {
    const harness = createDerivedStateHarness({
        loadRescueMessage: ref('Failed to load configuration.'),
        requestedMode() {
            return 'advanced'
        },
        requestedTarget() {
            return 'signal'
        },
    })

    assert.equal(
        harness.derivedState.effectiveLoadError.value,
        'Failed to load configuration.',
    )
    assert.equal(harness.derivedState.routeState.value.mode, 'setup')
    assert.equal(harness.derivedState.routeState.value.target, 'signal')
})

test('derived state prefers transition blockers over readiness blockers', () => {
    const transitionIntent = ref({
        kind: 'save',
        status: 'blocked',
        message: 'Blocked.',
        at: 1,
        blockers: [
            {
                key: 'secret',
                title: 'Exchange connection',
                description: 'Add API credentials.',
                mode: 'setup',
                target: 'exchange',
            },
        ],
    })
    const harness = createDerivedStateHarness({
        transitionIntent,
    })

    assert.deepEqual(harness.derivedState.visibleBlockers.value, [
        {
            key: 'secret',
            title: 'Exchange connection',
            description: 'Add API credentials.',
            mode: 'setup',
            target: 'exchange',
        },
    ])
})

test('derived state exposes stale trust when another client saved a newer config', () => {
    const harness = createDerivedStateHarness({
        hasUnsavedChanges() {
            return true
        },
        snapshotStore: {
            hasKnownNewerSnapshot: ref(true),
            isHydrated: ref(true),
            latestKnownUpdatedAt: ref('2026-04-06T09:05:00Z'),
            loadError: ref(null),
            loadState: ref('ready'),
            snapshot: ref({
                timezone: 'Europe/Vienna',
            }),
        },
    })

    assert.equal(
        harness.derivedState.configTrustState.value.kind,
        'stale_with_draft_conflict',
    )
    assert.equal(
        harness.derivedState.configTrustState.value.updatedAt,
        '2026-04-06T09:05:00Z',
    )
})
