const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    resolveControlCenterNavigation,
} = loadFrontendModule('src/control-center/routerGuard.ts')

function createReadiness(overrides = {}) {
    return {
        complete: false,
        firstRun: true,
        attentionNeeded: false,
        blockers: [],
        nextMode: 'setup',
        nextTarget: 'exchange',
        dryRun: true,
        configuredEssentials: 0,
        ...overrides,
    }
}

test('router guard clamps pre-readiness deep links back to setup', () => {
    const result = resolveControlCenterNavigation(
        {
            name: 'controlCenter',
            query: {
                mode: 'advanced',
                target: 'backup-restore',
            },
        },
        {
            loadError: null,
            readiness: createReadiness(),
        },
    )

    assert.deepEqual(result, {
        name: 'controlCenter',
        query: {
            mode: 'setup',
            target: 'exchange',
        },
        replace: true,
    })
})

test('router guard preserves setup targets while readiness is incomplete', () => {
    const result = resolveControlCenterNavigation(
        {
            name: 'controlCenter',
            query: {
                mode: 'advanced',
                target: 'signal',
            },
        },
        {
            loadError: null,
            readiness: createReadiness({
                firstRun: false,
                attentionNeeded: true,
                nextTarget: 'signal',
                configuredEssentials: 4,
            }),
        },
    )

    assert.deepEqual(result, {
        name: 'controlCenter',
        query: {
            mode: 'setup',
            target: 'signal',
        },
        replace: true,
    })
})

test('router guard opens the advanced editor for an advanced-only blocker', () => {
    const result = resolveControlCenterNavigation(
        {
            name: 'controlCenter',
            query: {
                mode: 'setup',
                target: 'dca',
            },
        },
        {
            loadError: null,
            readiness: createReadiness({
                firstRun: false,
                attentionNeeded: true,
                nextMode: 'advanced',
                nextTarget: 'dca',
                configuredEssentials: 7,
            }),
        },
    )

    assert.deepEqual(result, {
        name: 'controlCenter',
        query: {
            mode: 'advanced',
            target: 'dca',
        },
        replace: true,
    })
})
