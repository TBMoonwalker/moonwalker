const assert = require('node:assert/strict')
const test = require('node:test')

const { computed } = require('vue')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterNavigation } = loadFrontendModule(
    'src/composables/useControlCenterNavigation.ts',
)
const { deriveGuidedFocusTarget } = loadFrontendModule(
    'src/control-center/focusFlow.ts',
)

function createNavigationHarness(overrides = {}) {
    const announcements = []
    const pushes = []
    const replacements = []
    const trackEvents = []
    const elements = new Map()

    const options = {
        announce(message) {
            announcements.push(message)
        },
        async nextTick() {},
        readTargetElement(target) {
            return elements.get(target) ?? null
        },
        routeState: computed(() => ({
            mode: 'setup',
            target: 'signal',
        })),
        router: {
            async push(location) {
                pushes.push(location)
            },
            async replace(location) {
                replacements.push(location)
            },
        },
        trackEvent(eventName, payload) {
            trackEvents.push([eventName, payload ?? null])
        },
        async waitForTarget({ read }) {
            return read()
        },
        ...overrides,
    }

    return {
        announcements,
        elements,
        flow: useControlCenterNavigation(options),
        pushes,
        replacements,
        trackEvents,
    }
}

test('navigation normalizes control-center routes for push and replace', async () => {
    const harness = createNavigationHarness()

    await harness.flow.navigateToControlCenter('setup', 'signal')
    await harness.flow.navigateToControlCenter('overview', 'signal', true)

    assert.deepEqual(harness.pushes, [
        {
            name: 'controlCenter',
            query: {
                mode: 'setup',
                target: 'signal',
            },
        },
    ])
    assert.deepEqual(harness.replacements, [
        {
            name: 'controlCenter',
            query: {
                mode: 'setup',
                target: 'signal',
            },
        },
    ])
})

test('navigation focuses a target and announces the guided jump', async () => {
    const focusCalls = []
    const scrollCalls = []
    const harness = createNavigationHarness()
    const focusAnchor = {
        focus(options) {
            focusCalls.push(options)
        },
    }

    harness.elements.set('signal', {
        querySelector() {
            return focusAnchor
        },
        scrollIntoView(options) {
            scrollCalls.push(options)
        },
    })

    const focused = await harness.flow.focusTarget('signal')

    assert.equal(focused, true)
    assert.deepEqual(scrollCalls, [
        {
            behavior: 'auto',
            block: 'start',
        },
    ])
    assert.deepEqual(focusCalls, [{ preventScroll: true }])
    assert.deepEqual(harness.announcements, [
        deriveGuidedFocusTarget('signal').announcement,
    ])
})

test('navigation guides to a target and focuses immediately when already on the right route', async () => {
    const focusTargets = []
    const harness = createNavigationHarness({
        async waitForTarget({ read }) {
            focusTargets.push('signal')
            return read()
        },
    })

    harness.elements.set('signal', {
        querySelector() {
            return null
        },
        focus() {},
        scrollIntoView() {},
    })

    await harness.flow.guideToTarget('signal')

    assert.deepEqual(harness.trackEvents, [
        ['control_center_fix_this_requested', { target: 'signal', mode: 'setup' }],
    ])
    assert.deepEqual(harness.pushes, [
        {
            name: 'controlCenter',
            query: {
                mode: 'setup',
                target: 'signal',
            },
        },
    ])
    assert.deepEqual(focusTargets, ['signal'])
})

test('navigation avoids early focus when the route must change first', async () => {
    const harness = createNavigationHarness({
        routeState: computed(() => ({
            mode: 'overview',
            target: null,
        })),
        async waitForTarget() {
            throw new Error('focusTarget should not run before the route changes')
        },
    })

    await harness.flow.guideToTarget('signal')

    assert.deepEqual(harness.pushes, [
        {
            name: 'controlCenter',
            query: {
                mode: 'setup',
                target: 'signal',
            },
        },
    ])
})

test('navigation preserves compatible targets across mode changes', async () => {
    const harness = createNavigationHarness({
        routeState: computed(() => ({
            mode: 'setup',
            target: 'signal',
        })),
    })

    await harness.flow.handleModeSelect('setup')
    await harness.flow.handleModeSelect('utilities')

    assert.deepEqual(harness.pushes, [
        {
            name: 'controlCenter',
            query: {
                mode: 'setup',
                target: 'signal',
            },
        },
        {
            name: 'controlCenter',
            query: {
                mode: 'utilities',
            },
        },
    ])
})
