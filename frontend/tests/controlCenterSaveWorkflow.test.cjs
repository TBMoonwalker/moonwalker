const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    submitControlCenterWorkspace,
} = loadFrontendModule('src/control-center/saveWorkflow.ts')

test('submitControlCenterWorkspace routes successful saves into overview', async () => {
    const calls = []
    const result = await submitControlCenterWorkspace({
        announce(message) {
            calls.push(['announce', message])
        },
        async navigateToMode(mode) {
            calls.push(['navigate', mode])
        },
        normalizeBlockers() {
            throw new Error('normalizeBlockers should not run for success')
        },
        now: () => 123,
        setTransitionIntent(intent) {
            calls.push(['transition', intent])
        },
        async submitForm() {
            calls.push(['submit'])
            return {
                status: 'success',
                message: 'Configuration saved successfully.',
            }
        },
    })

    assert.equal(result.status, 'success')
    assert.deepEqual(calls, [
        ['submit'],
        ['navigate', 'overview'],
        [
            'transition',
            {
                kind: 'save',
                status: 'success',
                message: 'Configuration saved.',
                at: 123,
                mode: 'overview',
            },
        ],
        ['announce', 'Configuration saved.'],
    ])
})

test('submitControlCenterWorkspace preserves backend blockers', async () => {
    const blocker = {
        key: 'secret',
        message: 'Add secret',
        mode: 'setup',
        target: 'exchange',
    }
    const calls = []
    const result = await submitControlCenterWorkspace({
        announce(message) {
            calls.push(['announce', message])
        },
        async navigateToMode() {
            calls.push(['navigate'])
        },
        normalizeBlockers(rawBlockers) {
            calls.push(['normalize', rawBlockers])
            return [blocker]
        },
        now: () => 456,
        setTransitionIntent(intent) {
            calls.push(['transition', intent])
        },
        async submitForm() {
            calls.push(['submit'])
            return {
                status: 'blocked',
                message: 'Missing exchange credentials.',
                blockers: [{ key: 'secret' }],
            }
        },
    })

    assert.equal(result.status, 'blocked')
    assert.deepEqual(calls, [
        ['submit'],
        ['normalize', [{ key: 'secret' }]],
        [
            'transition',
            {
                kind: 'save',
                status: 'blocked',
                message: 'Missing exchange credentials.',
                at: 456,
                blockers: [blocker],
            },
        ],
        ['announce', 'Missing exchange credentials.'],
    ])
})
