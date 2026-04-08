const assert = require('node:assert/strict')
const test = require('node:test')

const { computed, ref } = require('vue')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    createControlCenterLifecycleHandlers,
    useControlCenterLifecycle,
} = loadFrontendModule('src/composables/useControlCenterLifecycle.ts')

function createLifecycleHarness(overrides = {}) {
    const confirmations = []
    const detectedExternalChanges = []
    const disposed = []
    const focusCalls = []
    const initCalls = []
    const refreshCalls = []
    const syncReadinessCalls = []
    const windowAdditions = []
    const windowRemovals = []
    const windowIntervals = []
    const clearedIntervals = []

    const routeState = ref({
        mode: 'setup',
        target: 'signal',
    })
    const readiness = ref({
        complete: false,
        firstRun: true,
        attentionNeeded: true,
        blockers: [],
        nextMode: 'setup',
        nextTarget: 'signal',
        dryRun: true,
        configuredEssentials: 0,
    })
    const externalInvalidationToken = ref(0)

    const options = {
        checkForExternalConfigChanges: async () => {},
        confirmDiscardUnsavedChanges(reason) {
            confirmations.push(reason)
            return true
        },
        disposeFeedback() {
            disposed.push('dispose')
        },
        async focusTarget(target) {
            focusCalls.push(target)
            return true
        },
        handleBeforeUnload() {},
        async handleDetectedExternalConfigChange(shouldAnnounce) {
            detectedExternalChanges.push(shouldAnnounce)
        },
        handleGlobalKeydown() {},
        handleSetupEntryChoicePopState() {},
        initializeClientTimezoneOptions() {
            initCalls.push(['timezone'])
        },
        initializeSetupFlow() {
            initCalls.push(['setup'])
        },
        readiness: computed(() => readiness.value),
        async refreshWorkspaceFromSnapshot(force = false) {
            refreshCalls.push(force)
            return {
                status: 'success',
                message: 'Loaded.',
            }
        },
        routeState: computed(() => routeState.value),
        snapshotStore: {
            externalInvalidationToken,
        },
        staleCheckIntervalMs: 15000,
        syncSetupChoiceForReadiness(firstRun) {
            syncReadinessCalls.push(firstRun)
        },
        documentObject: { hidden: false },
        windowObject: {
            addEventListener(name, listener) {
                windowAdditions.push([name, listener])
            },
            removeEventListener(name, listener) {
                windowRemovals.push([name, listener])
            },
            setInterval(handler, timeout) {
                windowIntervals.push([handler, timeout])
                return 42
            },
            clearInterval(id) {
                clearedIntervals.push(id)
            },
        },
        ...overrides,
    }

    return {
        confirmations,
        detectedExternalChanges,
        disposed,
        externalInvalidationToken,
        focusCalls,
        handlers: createControlCenterLifecycleHandlers(options),
        initCalls,
        options,
        readiness,
        refreshCalls,
        routeState,
        syncReadinessCalls,
        windowAdditions,
        windowIntervals,
        windowRemovals,
        clearedIntervals,
    }
}

test('control center lifecycle mounts listeners, refreshes, and focuses the active target', async () => {
    const harness = createLifecycleHarness()

    await harness.handlers.handleMounted()

    assert.deepEqual(harness.initCalls, [['timezone'], ['setup']])
    assert.deepEqual(
        harness.windowAdditions.map(([name]) => name),
        ['beforeunload', 'keydown', 'focus', 'popstate'],
    )
    assert.equal(harness.windowIntervals.length, 1)
    assert.equal(harness.windowIntervals[0][1], 15000)
    assert.deepEqual(harness.refreshCalls, [false])
    assert.deepEqual(harness.focusCalls, ['signal'])
})

test('control center lifecycle tears down listeners and clears stale polling on unmount', () => {
    const harness = createLifecycleHarness()

    return harness.handlers.handleMounted().then(() => {
        harness.handlers.handleUnmounted()

        assert.deepEqual(
            harness.windowRemovals.map(([name]) => name),
            ['beforeunload', 'keydown', 'focus', 'popstate'],
        )
        assert.deepEqual(harness.clearedIntervals, [42])
        assert.deepEqual(harness.disposed, ['dispose'])
    })
})

test('control center lifecycle routes watcher callbacks through the extracted handlers', async () => {
    const harness = createLifecycleHarness({
        documentObject: { hidden: true },
    })

    await harness.handlers.handleRouteStateChange()
    harness.handlers.handleReadinessChange(false)
    await harness.handlers.handleExternalInvalidationTokenChange(0, undefined)
    await harness.handlers.handleExternalInvalidationTokenChange(7, 7)
    await harness.handlers.handleExternalInvalidationTokenChange(8, 7)

    assert.deepEqual(harness.focusCalls, ['signal'])
    assert.deepEqual(harness.syncReadinessCalls, [false])
    assert.deepEqual(harness.detectedExternalChanges, [false])
})

test('control center lifecycle keeps route-leave confirmation behind the extracted seam', () => {
    const harness = createLifecycleHarness()

    const allowed = harness.handlers.handleBeforeRouteLeave()

    assert.equal(allowed, true)
    assert.deepEqual(harness.confirmations, ['route_leave'])
})

test('control center lifecycle registers route, readiness, invalidation, and mount hooks', () => {
    const watchers = []
    const registered = {
        mounted: null,
        unmounted: null,
        beforeRouteLeave: null,
    }

    useControlCenterLifecycle({
        ...createLifecycleHarness().options,
        hooks: {
            onBeforeRouteLeave(handler) {
                registered.beforeRouteLeave = handler
            },
            onMounted(handler) {
                registered.mounted = handler
            },
            onUnmounted(handler) {
                registered.unmounted = handler
            },
            watch(source, callback, options) {
                watchers.push([source, callback, options ?? null])
            },
        },
    })

    assert.equal(watchers.length, 3)
    assert.deepEqual(watchers[0][2], { flush: 'post' })
    assert.equal(typeof registered.beforeRouteLeave, 'function')
    assert.equal(typeof registered.mounted, 'function')
    assert.equal(typeof registered.unmounted, 'function')
})
