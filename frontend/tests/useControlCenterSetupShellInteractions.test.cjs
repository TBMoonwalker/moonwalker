const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterSetupShellInteractions } = loadFrontendModule(
    'src/composables/useControlCenterSetupShellInteractions.ts',
)

function createSetupShellHarness(overrides = {}) {
    const selections = []

    const flow = useControlCenterSetupShellInteractions({
        async handleSetupTaskSelect(target) {
            selections.push(target)
        },
        isSetupTaskExpanded() {
            return false
        },
        isInteractiveTarget() {
            return false
        },
        ...overrides,
    })

    return {
        flow,
        selections,
    }
}

test('setup shell interactions select collapsed tasks when the shell itself is clicked', async () => {
    const harness = createSetupShellHarness()

    await harness.flow.handleSetupSectionShellClick('signal', {
        target: null,
    })

    assert.deepEqual(harness.selections, ['signal'])
})

test('setup shell interactions ignore clicks when the task is already expanded', async () => {
    const harness = createSetupShellHarness({
        isSetupTaskExpanded() {
            return true
        },
    })

    await harness.flow.handleSetupSectionShellClick('signal', {
        target: null,
    })

    assert.deepEqual(harness.selections, [])
})

test('setup shell interactions ignore nested interactive targets', async () => {
    const harness = createSetupShellHarness({
        isInteractiveTarget() {
            return true
        },
    })

    await harness.flow.handleSetupSectionShellClick('signal', {
        target: { nodeName: 'BUTTON' },
    })

    assert.deepEqual(harness.selections, [])
})
