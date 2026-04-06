const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    buildControlCenterQuery,
    normalizeControlCenterRouteState,
} = loadFrontendModule('src/control-center/routeState.ts')

test('normalizeControlCenterRouteState falls back for unknown values', () => {
    const state = normalizeControlCenterRouteState({
        requestedMode: 'unknown',
        requestedTarget: 'missing',
        fallbackMode: 'overview',
    })

    assert.deepEqual(state, {
        mode: 'overview',
        target: null,
    })
})

test('normalizeControlCenterRouteState uses the task default mode when needed', () => {
    const state = normalizeControlCenterRouteState({
        requestedMode: 'utilities',
        requestedTarget: 'exchange',
        fallbackMode: 'overview',
    })

    assert.deepEqual(state, {
        mode: 'setup',
        target: 'exchange',
    })
    assert.deepEqual(buildControlCenterQuery(state), {
        mode: 'setup',
        target: 'exchange',
    })
})

test('buildControlCenterQuery omits target when route state has no target', () => {
    assert.deepEqual(
        buildControlCenterQuery({
            mode: 'overview',
            target: null,
        }),
        {
            mode: 'overview',
        },
    )
})
