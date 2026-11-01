const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { createAppRouter } = loadFrontendModule('src/router/index.ts')

test('createAppRouter redirects the legacy /config and /settings routes to control-center', () => {
    const router = createAppRouter()

    for (const legacyPath of ['/config', '/settings']) {
        const route = router.getRoutes().find(
            (candidate) => candidate.path === legacyPath,
        )
        assert.deepEqual(route.redirect, { name: 'controlCenter' })
    }
    assert.ok(
        router.getRoutes().some((route) => route.name === 'controlCenter'),
    )
})

test('createAppRouter redirects any unmatched top-level path to the trades overview', () => {
    const router = createAppRouter()

    const catchAll = router.getRoutes().find(
        (candidate) => candidate.path === '/:pathMatch(.*)*',
    )
    assert.deepEqual(catchAll.redirect, { name: 'trades' })
    assert.ok(router.getRoutes().some((route) => route.name === 'trades'))
})
