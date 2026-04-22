const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { createAppRouter } = loadFrontendModule('src/router/index.ts')
const { deriveControlCenterReadiness } = loadFrontendModule(
    'src/control-center/readiness.ts',
)
const { resolveControlCenterNavigation } = loadFrontendModule(
    'src/control-center/routerGuard.ts',
)

test('createAppRouter keeps only canonical Control Center entry routes', () => {
    const router = createAppRouter()
    const routePaths = router.getRoutes().map((route) => route.path)
    const routeNames = router.getRoutes().map((route) => route.name)

    assert.equal(routePaths.includes('/control-center'), true)
    assert.equal(routePaths.includes('/control-center/autopilot'), true)
    assert.equal(routePaths.includes('/monitoring'), true)
    assert.equal(routePaths.includes('/settings'), false)
    assert.equal(routePaths.includes('/config'), false)
    assert.equal(routeNames.includes('legacySettings'), false)
    assert.equal(routeNames.includes('legacyConfig'), false)
})

test('resolveControlCenterNavigation normalizes invalid control-center query state', () => {
    const result = resolveControlCenterNavigation(
        {
            name: 'controlCenter',
            query: {
                mode: 'broken',
                target: 'missing',
            },
        },
        {
            loadError: null,
            readiness: deriveControlCenterReadiness({
                timezone: 'Europe/Vienna',
                signal: 'asap',
                exchange: 'binance',
                timeframe: '1h',
                key: 'api-key',
                secret: 'api-secret',
                currency: 'USDT',
                max_bots: 2,
                bo: 20,
                tp: 1.5,
                history_lookback_time: '180d',
                symbol_list: 'BTC/USDT',
                dry_run: true,
            }),
        },
    )

    assert.deepEqual(result, {
        name: 'controlCenter',
        query: {
            mode: 'overview',
        },
        replace: true,
    })
})

test('resolveControlCenterNavigation redirects incomplete routes into setup', () => {
    const result = resolveControlCenterNavigation(
        {
            name: 'monitoring',
            query: {},
        },
        {
            loadError: null,
            readiness: deriveControlCenterReadiness({}),
        },
    )

    assert.deepEqual(result, {
        name: 'controlCenter',
        query: {
            mode: 'setup',
            target: 'general',
        },
        replace: true,
    })
})

test('resolveControlCenterNavigation leaves an already-valid rescue deep link alone', () => {
    const result = resolveControlCenterNavigation(
        {
            name: 'controlCenter',
            query: {
                mode: 'setup',
                target: 'signal',
            },
        },
        {
            loadError: 'Request failed',
            readiness: deriveControlCenterReadiness({}),
        },
    )

    assert.equal(result, true)
})
