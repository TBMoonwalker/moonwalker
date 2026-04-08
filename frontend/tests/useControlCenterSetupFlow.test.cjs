const assert = require('node:assert/strict')
const test = require('node:test')

const { computed } = require('vue')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterSetupFlow } = loadFrontendModule(
    'src/composables/useControlCenterSetupFlow.ts',
)
const {
    CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY,
} = loadFrontendModule('src/control-center/setupEntryHistory.ts')

function createWindowHarness() {
    const storage = new Map()
    const pushes = []
    const replacements = []

    const history = {
        state: null,
        pushState(data, unused, url) {
            history.state = data
            pushes.push([data, unused, url])
        },
        replaceState(data, unused, url) {
            history.state = data
            replacements.push([data, unused, url])
        },
    }

    return {
        history,
        localStorage: {
            getItem(key) {
                return storage.has(key) ? storage.get(key) : null
            },
            removeItem(key) {
                storage.delete(key)
            },
            setItem(key, value) {
                storage.set(key, String(value))
            },
        },
        location: {
            href: 'http://moonwalker.test/control-center',
        },
        pushes,
        replacements,
        storage,
    }
}

function createSetupFlowHarness(overrides = {}) {
    const events = []
    const focusTargets = []
    const guidedTargets = []
    const navigation = []
    const liveActivations = []
    const window = createWindowHarness()

    const options = {
        async focusTarget(target) {
            focusTargets.push(target)
            return true
        },
        async guideToTarget(target) {
            guidedTargets.push(target)
        },
        async handleActivateLiveTrading() {
            liveActivations.push('activate')
        },
        async navigateToControlCenter(mode, target = null) {
            navigation.push([mode, target])
        },
        readiness: computed(() => ({
            complete: false,
            firstRun: true,
            attentionNeeded: false,
            blockers: [],
            nextMode: 'setup',
            nextTarget: 'general',
            dryRun: true,
            configuredEssentials: 0,
        })),
        routeState: computed(() => ({
            mode: 'setup',
            target: 'general',
        })),
        visibleBlockers: computed(() => []),
        trackEvent(eventName, payload) {
            events.push([eventName, payload ?? null])
        },
        window,
        ...overrides,
    }

    return {
        events,
        flow: useControlCenterSetupFlow(options),
        focusTargets,
        guidedTargets,
        liveActivations,
        navigation,
        window,
    }
}

test('setup flow initializes from history state and stored setup style', () => {
    const harness = createSetupFlowHarness()
    harness.window.history.state = {
        [CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]: 'restore',
    }
    harness.window.localStorage.setItem(
        'moonwalker.controlCenter.entryChoice',
        'new',
    )
    harness.window.localStorage.setItem(
        'moonwalker.controlCenter.setupStyle',
        'full',
    )

    harness.flow.initializeSetupFlow()

    assert.equal(harness.flow.setupStyle.value, 'full')
    assert.equal(harness.flow.showRestoreSetupFlow.value, true)
    assert.equal(harness.flow.showSetupEntryGate.value, false)
    assert.equal(harness.window.replacements.length, 1)
    assert.deepEqual(harness.window.replacements[0][0], {
        [CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]: 'restore',
    })
})

test('setup flow pushes browser history and focuses the active task for new setup', async () => {
    const harness = createSetupFlowHarness()

    await harness.flow.handleSetupEntryChoice('new')

    assert.equal(harness.flow.showSetupEntryGate.value, false)
    assert.equal(harness.window.storage.get('moonwalker.controlCenter.entryChoice'), 'new')
    assert.equal(harness.window.pushes.length, 1)
    assert.deepEqual(harness.window.pushes[0][0], {
        [CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]: 'new',
    })
    assert.deepEqual(harness.events, [
        ['control_center_setup_entry_selected', { choice: 'new' }],
    ])
    assert.deepEqual(harness.focusTargets, ['general'])
})

test('setup flow restores entry choice from browser history on popstate', () => {
    const harness = createSetupFlowHarness()
    harness.window.history.state = {
        [CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]: 'restore',
    }

    harness.flow.handleSetupEntryChoicePopState()

    assert.equal(harness.flow.showRestoreSetupFlow.value, true)
})

test('setup flow converts restore choice into new when first-run mode ends', async () => {
    const harness = createSetupFlowHarness()

    await harness.flow.handleSetupEntryChoice('restore')
    harness.flow.syncSetupChoiceForReadiness(false)

    assert.equal(harness.window.storage.get('moonwalker.controlCenter.entryChoice'), 'new')
    assert.equal(harness.window.replacements.length, 1)
    assert.deepEqual(harness.window.replacements[0][0], {
        [CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]: 'new',
    })
})

test('setup flow derives task status, summaries, and expansion state', () => {
    const harness = createSetupFlowHarness({
        visibleBlockers: computed(() => [
            {
                key: 'key',
                title: 'Exchange credentials',
                description: 'Add API credentials.',
                mode: 'setup',
                target: 'exchange',
            },
        ]),
    })

    assert.deepEqual(harness.flow.getSetupTaskStatus('general'), {
        label: 'Current',
        type: 'info',
    })
    assert.deepEqual(harness.flow.getSetupTaskStatus('exchange'), {
        label: 'Needs attention',
        type: 'warning',
    })
    assert.equal(
        harness.flow.getSetupTaskSummary('exchange'),
        'Add API credentials.',
    )
    assert.equal(harness.flow.isSetupTaskExpanded('general'), true)
    assert.equal(harness.flow.isSetupTaskExpanded('exchange'), false)

    harness.flow.handleSetupStyleChange('full')

    assert.equal(harness.flow.setupStyle.value, 'full')
    assert.equal(harness.flow.setupShowsAdvancedFields.value, true)
    assert.equal(harness.flow.isSetupTaskExpanded('exchange'), true)
})

test('setup flow mission action guides incomplete readiness to the next blocker', async () => {
    const harness = createSetupFlowHarness({
        readiness: computed(() => ({
            complete: false,
            firstRun: false,
            attentionNeeded: true,
            blockers: [],
            nextMode: 'setup',
            nextTarget: 'signal',
            dryRun: true,
            configuredEssentials: 4,
        })),
    })

    await harness.flow.handleMissionPrimaryAction()

    assert.deepEqual(harness.guidedTargets, ['signal'])
    assert.deepEqual(harness.liveActivations, [])
    assert.deepEqual(harness.navigation, [])
})

test('setup flow mission action activates dry-run setups and otherwise navigates home', async () => {
    const dryRunHarness = createSetupFlowHarness({
        readiness: computed(() => ({
            complete: true,
            firstRun: false,
            attentionNeeded: false,
            blockers: [],
            nextMode: 'overview',
            nextTarget: 'live-activation',
            dryRun: true,
            configuredEssentials: 8,
        })),
    })

    await dryRunHarness.flow.handleMissionPrimaryAction()

    assert.deepEqual(dryRunHarness.liveActivations, ['activate'])
    assert.deepEqual(dryRunHarness.navigation, [])

    const liveHarness = createSetupFlowHarness({
        readiness: computed(() => ({
            complete: true,
            firstRun: false,
            attentionNeeded: false,
            blockers: [],
            nextMode: 'overview',
            nextTarget: 'live-activation',
            dryRun: false,
            configuredEssentials: 8,
        })),
    })

    await liveHarness.flow.handleMissionPrimaryAction()

    assert.deepEqual(liveHarness.liveActivations, [])
    assert.deepEqual(liveHarness.navigation, [['overview', null]])
})
