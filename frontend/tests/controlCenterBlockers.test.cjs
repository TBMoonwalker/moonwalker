const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    normalizeControlCenterBlockers,
    resolveControlCenterBlocker,
} = loadFrontendModule('src/control-center/blockers.ts')

test('control center blocker helper maps backend blocker payloads to guided tasks', () => {
    const blockers = normalizeControlCenterBlockers([
        {
            key: 'exchange',
            message: 'Choose an exchange first.',
        },
    ])

    assert.deepEqual(blockers, [
        {
            key: 'exchange',
            title: 'Exchange connection',
            description: 'Choose an exchange first.',
            mode: 'setup',
            target: 'exchange',
        },
    ])
})

test('control center blocker helper ignores malformed blocker rows', () => {
    const blockers = normalizeControlCenterBlockers([
        null,
        {},
        { key: '   ' },
        { key: 'timezone' },
    ])

    assert.deepEqual(blockers, [
        {
            key: 'timezone',
            title: 'General runtime',
            description: 'Resolve this blocker before continuing.',
            mode: 'setup',
            target: 'general',
        },
    ])
})

test('control center blocker helper preserves custom titles for readiness copy', () => {
    const blocker = resolveControlCenterBlocker(
        'key',
        'Add the exchange API key.',
        'Exchange key missing',
    )

    assert.deepEqual(blocker, {
        key: 'key',
        title: 'Exchange key missing',
        description: 'Add the exchange API key.',
        mode: 'setup',
        target: 'exchange',
    })
})
