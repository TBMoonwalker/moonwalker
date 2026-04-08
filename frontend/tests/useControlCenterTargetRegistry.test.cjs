const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterTargetRegistry } = loadFrontendModule(
    'src/composables/useControlCenterTargetRegistry.ts',
)

test.afterEach(() => {
    delete global.HTMLElement
})

test('target registry stores and reads bound target elements by control-center target', () => {
    class MockHTMLElement {}

    global.HTMLElement = MockHTMLElement

    const registry = useControlCenterTargetRegistry()
    const signalElement = new MockHTMLElement()

    registry.bindTargetElement('signal')(signalElement)

    assert.equal(registry.readTargetElement('signal'), signalElement)
    assert.equal(registry.readTargetElement('general'), null)
})

test('target registry ignores non-HTMLElement bindings', () => {
    class MockHTMLElement {}

    global.HTMLElement = MockHTMLElement

    const registry = useControlCenterTargetRegistry()

    registry.bindTargetElement('signal')({})

    assert.equal(registry.readTargetElement('signal'), null)
})
