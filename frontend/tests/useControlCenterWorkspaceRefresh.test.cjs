const assert = require('node:assert/strict')
const test = require('node:test')

const { ref } = require('vue')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterWorkspaceRefresh } = loadFrontendModule(
    'src/composables/useControlCenterWorkspaceRefresh.ts',
)

function createWorkspaceRefreshHarness(overrides = {}) {
    const loadRescueMessage = ref('stale')
    const routerCalls = []
    const snapshotCalls = []

    const options = {
        async fetchDefaultValues() {
            return {
                status: 'success',
                message: 'Loaded.',
            }
        },
        loadRescueMessage,
        readRouteState() {
            return {
                mode: 'advanced',
                target: 'signal',
            }
        },
        readViewState() {
            return {
                defaultMode: 'setup',
            }
        },
        router: {
            async replace(location) {
                routerCalls.push(location)
            },
        },
        snapshotStore: {
            async ensureLoaded(force) {
                snapshotCalls.push(['ensureLoaded', force])
            },
            async refresh() {
                snapshotCalls.push(['refresh'])
            },
        },
        ...overrides,
    }

    return {
        loadRescueMessage,
        refreshState: useControlCenterWorkspaceRefresh(options),
        routerCalls,
        snapshotCalls,
    }
}

test('workspace refresh normalizes the current route after a successful load', async () => {
    const harness = createWorkspaceRefreshHarness()

    const result =
        await harness.refreshState.refreshWorkspaceFromSnapshot(false)

    assert.deepEqual(result, {
        status: 'success',
        message: 'Loaded.',
    })
    assert.equal(harness.loadRescueMessage.value, null)
    assert.deepEqual(harness.snapshotCalls, [['ensureLoaded', false]])
    assert.deepEqual(harness.routerCalls, [
        {
            name: 'controlCenter',
            query: {
                mode: 'setup',
                target: 'signal',
            },
        },
    ])
})

test('workspace refresh uses the forced snapshot path when requested', async () => {
    const harness = createWorkspaceRefreshHarness()

    await harness.refreshState.refreshWorkspaceFromSnapshot(true)

    assert.deepEqual(harness.snapshotCalls, [['refresh']])
})

test('workspace refresh preserves rescue copy when config loading returns an error result', async () => {
    const harness = createWorkspaceRefreshHarness({
        async fetchDefaultValues() {
            return {
                status: 'error',
                message: 'Could not load config.',
            }
        },
    })

    const result =
        await harness.refreshState.refreshWorkspaceFromSnapshot(false)

    assert.deepEqual(result, {
        status: 'error',
        message: 'Could not load config.',
    })
    assert.equal(harness.loadRescueMessage.value, 'Could not load config.')
    assert.deepEqual(harness.routerCalls, [])
})

test('workspace refresh surfaces thrown load errors with the shared API error helper', async () => {
    const harness = createWorkspaceRefreshHarness({
        async fetchDefaultValues() {
            throw new Error('Load failed.')
        },
    })

    const result =
        await harness.refreshState.refreshWorkspaceFromSnapshot(false)

    assert.deepEqual(result, {
        status: 'error',
        message: 'Load failed.',
    })
    assert.equal(harness.loadRescueMessage.value, 'Load failed.')
    assert.deepEqual(harness.routerCalls, [])
})
