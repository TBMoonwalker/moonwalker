const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { waitForTargetElement } = loadFrontendModule(
    'src/control-center/focusFlow.ts',
)

test('waitForTargetElement retries until a routed section mounts', async () => {
    // Regression: ISSUE-003 — "Fix this" landed in setup mode without jumping
    // Found by /qa on 2026-03-20
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-03-20.md
    let reads = 0
    const element = { id: 'control-center-signal' }

    const result = await waitForTargetElement({
        attempts: 4,
        nextTick: async () => {},
        read: () => {
            reads += 1
            return reads >= 3 ? element : null
        },
        requestAnimationFrame: (callback) => {
            callback(0)
            return 1
        },
    })

    assert.equal(result, element)
    assert.equal(reads, 3)
})

test('waitForTargetElement tolerates slower routed section mounts by default', async () => {
    // Regression: ISSUE-003 — "Fix this" changed routes before the section mounted
    // Found by /qa on 2026-03-20
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-03-20.md
    let reads = 0
    const element = { id: 'control-center-signal' }

    const result = await waitForTargetElement({
        nextTick: async () => {},
        read: () => {
            reads += 1
            return reads >= 9 ? element : null
        },
        requestAnimationFrame: (callback) => {
            callback(0)
            return 1
        },
    })

    assert.equal(result, element)
    assert.equal(reads, 9)
})

test('waitForTargetElement returns null after exhausting retries', async () => {
    // Regression: ISSUE-003 — "Fix this" landed in setup mode without jumping
    // Found by /qa on 2026-03-20
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-03-20.md
    let reads = 0

    const result = await waitForTargetElement({
        attempts: 3,
        nextTick: async () => {},
        read: () => {
            reads += 1
            return null
        },
        requestAnimationFrame: (callback) => {
            callback(0)
            return 1
        },
    })

    assert.equal(result, null)
    assert.equal(reads, 3)
})
