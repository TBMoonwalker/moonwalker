const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    useConfigValidationFlow,
} = loadFrontendModule('src/composables/useConfigValidationFlow.ts')

test('handleGlobalKeydown uses the custom save shortcut when provided', async () => {
    global.window = {}
    let shortcutCalls = 0
    const messageCalls = []
    const flow = useConfigValidationFlow({
        message: {
            error(message) {
                messageCalls.push(message)
            },
        },
        onSubmitShortcut: () => {
            shortcutCalls += 1
        },
        onValidSubmit: () => {
            throw new Error('validateAndSubmit should not run for shortcut override')
        },
        setSaveError() {},
    })

    flow.generalFormRef.value = {
        validate: async () => {
            throw new Error('form validation should not run for shortcut override')
        },
    }

    flow.handleGlobalKeydown({
        key: 's',
        ctrlKey: true,
        metaKey: false,
        preventDefault() {},
    })

    await new Promise((resolve) => setImmediate(resolve))

    assert.equal(shortcutCalls, 1)
    assert.deepEqual(messageCalls, [])
    delete global.window
})
