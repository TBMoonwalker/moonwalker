const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const { JSDOM } = require('jsdom')

const dom = new JSDOM('<!doctype html><html><body></body></html>')
globalThis.window = dom.window
globalThis.document = dom.window.document
for (const key of Object.getOwnPropertyNames(dom.window)) {
    if (key in globalThis) {
        continue
    }
    try {
        globalThis[key] = dom.window[key]
    } catch {
        // Read-only globals: leave Node's own value in place.
    }
}

const { createApp } = require('vue')
const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')
const rootDir = path.resolve(__dirname, '..')
const useViewportSource = fs.readFileSync(
    path.join(rootDir, 'src/composables/useViewport.ts'),
    'utf8',
)

const {
    VIEWPORT_BREAKPOINTS,
    VIEWPORT_COMMIT_DEBOUNCE_MS,
    useViewport,
} = loadFrontendModule('src/composables/useViewport.ts')

function resizeTo(width) {
    Object.defineProperty(dom.window, 'innerWidth', {
        configurable: true,
        writable: true,
        value: width,
    })
    dom.window.dispatchEvent(new dom.window.Event('resize'))
}

function settleCommits() {
    const delay = (typeof VIEWPORT_COMMIT_DEBOUNCE_MS === 'number'
        ? VIEWPORT_COMMIT_DEBOUNCE_MS
        : 120) + 60
    return new Promise((resolve) => setTimeout(resolve, delay))
}

function mountConsumer(captured) {
    const host = dom.window.document.createElement('div')
    dom.window.document.body.appendChild(host)
    const app = createApp({
        setup() {
            captured.viewport = useViewport()
            return () => null
        },
    })
    app.mount(host)
    return app
}

test('breakpoint commit debounce is exported as a small positive budget', () => {
    assert.equal(typeof VIEWPORT_COMMIT_DEBOUNCE_MS, 'number')
    assert.ok(
        VIEWPORT_COMMIT_DEBOUNCE_MS > 0,
        'the commit must be deferred, not synchronous',
    )
    assert.ok(
        VIEWPORT_COMMIT_DEBOUNCE_MS <= 300,
        'the commit must stay short enough to feel immediate once the window settles',
    )
    assert.equal(VIEWPORT_BREAKPOINTS.mobile, 768)
    assert.equal(VIEWPORT_BREAKPOINTS.desktop, 1200)
})

test('raw viewport width still tracks every resize immediately', () => {
    // The resize handler must update the raw ref before it schedules the
    // debounced breakpoint commit.
    const handlerBody = /function handleViewportResize\(\): void \{([\s\S]*?)\n\}/.exec(
        useViewportSource,
    )
    assert.ok(handlerBody, 'handleViewportResize not found')
    const rawAssign = handlerBody[1].indexOf(
        'viewportWidth.value = readViewportWidth()',
    )
    const schedule = handlerBody[1].indexOf('setTimeout(')
    assert.notEqual(rawAssign, -1, 'raw width must update on resize')
    assert.notEqual(schedule, -1, 'commit must be scheduled on resize')
    assert.ok(
        rawAssign < schedule,
        'raw width must update before the debounced commit is scheduled',
    )
})

test('breakpoint booleans hold the last settled band while a resize is in flight', async (t) => {
    const captured = {}
    const app = mountConsumer(captured)
    t.after(() => app.unmount())
    await settleCommits()

    // Settle in the desktop band.
    resizeTo(1240)
    await settleCommits()
    assert.equal(captured.viewport.isMobile.value, false)
    assert.equal(captured.viewport.isTablet.value, false)

    // A fast drag into the mobile band updates the raw width immediately,
    // but must not flip the booleans before the resizes settle. Microtasks
    // run before the debounced commit timer, so this observation point is
    // deterministic.
    resizeTo(700)
    await Promise.resolve()
    assert.equal(captured.viewport.viewportWidth.value, 700)
    assert.equal(
        captured.viewport.isMobile.value,
        false,
        'isMobile must not flip mid-gesture',
    )
    assert.equal(captured.viewport.isTablet.value, false)

    // Once the drag settles, the booleans commit to the settled band.
    await settleCommits()
    assert.equal(captured.viewport.isMobile.value, true)
    assert.equal(captured.viewport.isTablet.value, false)

    // And the way back: the booleans hold the committed band until settle.
    resizeTo(1200)
    await Promise.resolve()
    assert.equal(captured.viewport.viewportWidth.value, 1200)
    assert.equal(
        captured.viewport.isMobile.value,
        true,
        'isMobile must hold the committed band until the settle',
    )
    await settleCommits()
    assert.equal(captured.viewport.isMobile.value, false)
    assert.equal(captured.viewport.isTablet.value, false)
})

test('rapid oscillation across breakpoints does not flip the column booleans', async (t) => {
    const captured = {}
    const app = mountConsumer(captured)
    t.after(() => app.unmount())
    await settleCommits()

    resizeTo(1240)
    await settleCommits()
    assert.equal(captured.viewport.isMobile.value, false)
    assert.equal(captured.viewport.isTablet.value, false)

    // The reported bug: a fast width drag crossing desktop -> tablet ->
    // mobile -> tablet -> desktop must not flip the booleans between
    // resize events. Observing after each event (microtask only) is what a
    // re-render would see mid-gesture.
    for (const width of [1100, 700, 640, 900, 1240]) {
        resizeTo(width)
        await Promise.resolve()
        assert.equal(
            captured.viewport.viewportWidth.value,
            width,
            `raw width must track the drag (saw ${captured.viewport.viewportWidth.value}, wanted ${width})`,
        )
        assert.equal(
            captured.viewport.isMobile.value,
            false,
            `isMobile must not flip mid-oscillation at width ${width}`,
        )
        assert.equal(
            captured.viewport.isTablet.value,
            false,
            `isTablet must not flip mid-oscillation at width ${width}`,
        )
    }

    await settleCommits()
    assert.equal(captured.viewport.isMobile.value, false)
    assert.equal(captured.viewport.isTablet.value, false)
})

test('detaching the last consumer cancels the pending commit', async (t) => {
    const captured = {}
    const app = mountConsumer(captured)
    await settleCommits()

    resizeTo(1240)
    await settleCommits()
    assert.equal(captured.viewport.isMobile.value, false)
    assert.equal(captured.viewport.isTablet.value, false)

    // Start a drag and tear down before it settles.
    resizeTo(640)
    app.unmount()
    await settleCommits()
    // The commit must have been cancelled: the booleans still hold the
    // last settled (desktop) band.
    assert.equal(captured.viewport.isMobile.value, false)
    assert.equal(
        captured.viewport.isTablet.value,
        false,
        'a cancelled commit must not flip the booleans later',
    )
})
