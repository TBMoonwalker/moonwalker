const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterFeedback } = loadFrontendModule(
    'src/composables/useControlCenterFeedback.ts',
)

function createFeedbackHarness(overrides = {}) {
    const scheduled = []
    const cancelled = []
    let nextId = 1

    const feedback = useControlCenterFeedback({
        schedule(callback, delayMs) {
            const handle = nextId
            nextId += 1
            scheduled.push({ callback, delayMs, handle })
            return handle
        },
        cancel(handle) {
            cancelled.push(handle)
        },
        ...overrides,
    })

    return {
        cancelled,
        feedback,
        scheduled,
    }
}

test('feedback announces trimmed live-region messages asynchronously', () => {
    const harness = createFeedbackHarness()

    harness.feedback.announce('  Configuration saved.  ')

    assert.equal(harness.feedback.liveRegionMessage.value, '')
    assert.deepEqual(
        harness.scheduled.map(({ delayMs }) => delayMs),
        [10],
    )

    harness.scheduled[0].callback()

    assert.equal(harness.feedback.liveRegionMessage.value, 'Configuration saved.')
})

test('feedback clears the previous success timeout before setting a new transition', () => {
    const harness = createFeedbackHarness()

    harness.feedback.setTransitionIntent({
        kind: 'save',
        status: 'success',
        message: 'Saved.',
        at: 1,
    })
    harness.feedback.setTransitionIntent({
        kind: 'save',
        status: 'error',
        message: 'Failed.',
        at: 2,
    })

    assert.deepEqual(harness.cancelled, [1])
    assert.equal(harness.feedback.transitionIntent.value.status, 'error')
    assert.equal(harness.scheduled.length, 1)
})

test('feedback clears successful transitions after the configured timeout', () => {
    const harness = createFeedbackHarness()

    harness.feedback.setTransitionIntent({
        kind: 'restore',
        status: 'success',
        message: 'Restored.',
        at: 1,
        mode: 'overview',
    })

    assert.equal(harness.feedback.transitionIntent.value.status, 'success')

    harness.scheduled[0].callback()

    assert.equal(harness.feedback.transitionIntent.value, null)
})

test('feedback dispose cancels a pending success timeout', () => {
    const harness = createFeedbackHarness()

    harness.feedback.setTransitionIntent({
        kind: 'save',
        status: 'success',
        message: 'Saved.',
        at: 1,
    })
    harness.feedback.disposeFeedback()

    assert.deepEqual(harness.cancelled, [1])
})
