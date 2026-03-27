const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    buildControlCenterQuery,
    buildLegacyControlCenterRedirect,
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

test('buildLegacyControlCenterRedirect preserves setup intent and normalizes targets', () => {
    const redirect = buildLegacyControlCenterRedirect({
        setup: 'required',
        target: 'signal',
        mode: 'advanced',
    })

    assert.deepEqual(redirect, {
        name: 'controlCenter',
        query: {
            mode: 'setup',
            target: 'signal',
        },
    })
})
