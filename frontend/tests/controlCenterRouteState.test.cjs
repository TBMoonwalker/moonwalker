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
        fallbackMode: 'setup',
    })

    assert.deepEqual(state, {
        mode: 'setup',
        target: null,
    })
})

test('normalizeControlCenterRouteState uses the task default mode when needed', () => {
    const state = normalizeControlCenterRouteState({
        requestedMode: 'utilities',
        requestedTarget: 'exchange',
        fallbackMode: 'setup',
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

test('normalizeControlCenterRouteState treats strategy builder as a dedicated mode', () => {
    const state = normalizeControlCenterRouteState({
        requestedMode: 'advanced',
        requestedTarget: 'strategy-builder',
        fallbackMode: 'setup',
    })

    assert.deepEqual(state, {
        mode: 'strategy-builder',
        target: 'strategy-builder',
    })
    assert.deepEqual(buildControlCenterQuery(state), {
        mode: 'strategy-builder',
        target: 'strategy-builder',
    })
})

test('buildControlCenterQuery omits target when route state has no target', () => {
    assert.deepEqual(
        buildControlCenterQuery({
            mode: 'setup',
            target: null,
        }),
        {
            mode: 'setup',
        },
    )
})

test('normalizeControlCenterRouteState redirects legacy overview links to setup', () => {
    assert.deepEqual(normalizeControlCenterRouteState({
        requestedMode: 'overview',
        fallbackMode: 'setup',
    }), { mode: 'setup', target: null })
})
