const assert = require('node:assert/strict')
const test = require('node:test')

const { computed } = require('vue')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterRuntimeActions } = loadFrontendModule(
    'src/composables/useControlCenterRuntimeActions.ts',
)

function createRuntimeHarness(overrides = {}) {
    const announcements = []
    const navigation = []
    const syncCalls = []
    const intents = []
    const trackEvents = []
    const freshnessChecks = []

    const options = {
        announce(message) {
            announcements.push(message)
        },
        apiUrl(path) {
            return `http://moonwalker.test${path}`
        },
        hasUnsavedChanges() {
            return false
        },
        isDirty: computed(() => false),
        async navigateToControlCenter(mode, target = null) {
            navigation.push([mode, target])
        },
        normalizeBlockers(rawBlockers) {
            return Array.isArray(rawBlockers) ? rawBlockers : []
        },
        readiness: computed(() => ({
            complete: true,
            firstRun: false,
            attentionNeeded: false,
            blockers: [],
            nextMode: 'overview',
            nextTarget: null,
            dryRun: false,
            configuredEssentials: 5,
        })),
        routeState: computed(() => ({
            mode: 'overview',
            target: 'live-activation',
        })),
        setTransitionIntent(nextIntent) {
            intents.push(nextIntent)
        },
        snapshotStore: {
            async checkFreshness() {
                freshnessChecks.push('check')
                return {
                    status: 'unchanged',
                    updatedAt: null,
                }
            },
        },
        async syncControlCenterConfigChange(origin) {
            syncCalls.push(origin)
            return {
                status: 'success',
                message: 'Workspace refreshed.',
            }
        },
        confirmAction() {
            return true
        },
        async postActivateRequest() {
            return {
                data: {
                    message: 'Live trading activated.',
                },
            }
        },
        trackEvent(eventName) {
            trackEvents.push(eventName)
        },
        ...overrides,
    }

    return {
        announcements,
        flow: useControlCenterRuntimeActions(options),
        freshnessChecks,
        intents,
        navigation,
        syncCalls,
        trackEvents,
    }
}

test.afterEach(() => {
    delete global.document
})

test('runtime actions block live activation while the draft is dirty', async () => {
    const harness = createRuntimeHarness({
        isDirty: computed(() => true),
    })

    await harness.flow.handleActivateLiveTrading()

    assert.equal(harness.flow.activationLoading.value, false)
    assert.deepEqual(harness.syncCalls, [])
    assert.deepEqual(harness.navigation, [])
    assert.deepEqual(harness.trackEvents, [])
    assert.equal(harness.intents.length, 1)
    assert.equal(harness.intents[0].status, 'blocked')
    assert.equal(
        harness.intents[0].message,
        'Save the current draft before activating live trading.',
    )
    assert.deepEqual(harness.announcements, [
        'Save the current draft before activating live trading.',
    ])
})

test('runtime actions activate live trading through the extracted seam', async () => {
    const harness = createRuntimeHarness()

    await harness.flow.handleActivateLiveTrading()

    assert.equal(harness.flow.activationLoading.value, false)
    assert.deepEqual(harness.trackEvents, [
        'control_center_live_activation_requested',
    ])
    assert.deepEqual(harness.syncCalls, ['live_activation'])
    assert.deepEqual(harness.navigation, [['overview', 'live-activation']])
    assert.equal(harness.intents.length, 1)
    assert.equal(harness.intents[0].status, 'success')
    assert.equal(harness.intents[0].mode, 'overview')
    assert.equal(harness.intents[0].target, 'live-activation')
    assert.deepEqual(harness.announcements, ['Live trading activated.'])
})

test('runtime actions announce a newer external config when local drafts exist', async () => {
    const harness = createRuntimeHarness({
        hasUnsavedChanges() {
            return true
        },
    })

    await harness.flow.handleDetectedExternalConfigChange(true)

    assert.deepEqual(harness.syncCalls, [])
    assert.deepEqual(harness.announcements, [
        'A newer configuration is available from another client.',
    ])
})

test('runtime actions reload the latest config after stale prompt confirmation', async () => {
    const confirmMessages = []
    const harness = createRuntimeHarness({
        hasUnsavedChanges() {
            return true
        },
        confirmAction(message) {
            confirmMessages.push(message)
            return true
        },
        routeState: computed(() => ({
            mode: 'advanced',
            target: 'signal',
        })),
    })

    await harness.flow.handleReloadAfterStalePrompt()

    assert.deepEqual(confirmMessages, [
        'Reload the newer configuration now and discard local draft changes?',
    ])
    assert.deepEqual(harness.syncCalls, ['external_invalidation'])
    assert.equal(harness.intents.length, 1)
    assert.equal(harness.intents[0].kind, 'retry')
    assert.equal(harness.intents[0].mode, 'advanced')
    assert.equal(harness.intents[0].target, 'signal')
    assert.deepEqual(harness.announcements, [
        'Loaded the latest configuration from another client.',
    ])
})

test('runtime actions refresh when freshness checks detect an external update', async () => {
    global.document = { hidden: false }

    const harness = createRuntimeHarness({
        snapshotStore: {
            async checkFreshness() {
                harness.freshnessChecks.push('check')
                return {
                    status: 'stale',
                    updatedAt: '2026-04-06T09:00:00Z',
                }
            },
        },
    })

    await harness.flow.checkForExternalConfigChanges()

    assert.deepEqual(harness.freshnessChecks, ['check'])
    assert.deepEqual(harness.syncCalls, ['external_invalidation'])
    assert.deepEqual(harness.announcements, [
        'Configuration refreshed after external changes.',
    ])
})
