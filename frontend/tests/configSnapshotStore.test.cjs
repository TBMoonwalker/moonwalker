const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    resetSharedConfigSnapshotState,
    useSharedConfigSnapshot,
} = loadFrontendModule('src/control-center/configSnapshotStore.ts')

const CONFIG_INVALIDATION_STORAGE_KEY =
    'moonwalker.controlCenter.configInvalidation'

class FakeBroadcastChannel {
    static instances = []

    constructor(name) {
        this.name = name
        this.closed = false
        this.messages = []
        this.listeners = new Map()
        FakeBroadcastChannel.instances.push(this)
    }

    addEventListener(type, listener) {
        this.listeners.set(type, listener)
    }

    postMessage(payload) {
        this.messages.push(payload)
    }

    close() {
        this.closed = true
    }

    emit(payload) {
        const listener = this.listeners.get('message')
        if (listener) {
            listener({ data: payload })
        }
        if (typeof this.onmessage === 'function') {
            this.onmessage({ data: payload })
        }
    }
}

function createWindowHarness() {
    const listeners = new Map()
    const storage = new Map()

    return {
        hidden: false,
        localStorage: {
            getItem(key) {
                return storage.has(key) ? storage.get(key) : null
            },
            removeItem(key) {
                storage.delete(key)
            },
            setItem(key, value) {
                storage.set(key, String(value))
            },
        },
        addEventListener(type, listener) {
            listeners.set(type, listener)
        },
        removeEventListener(type, listener) {
            if (listeners.get(type) === listener) {
                listeners.delete(type)
            }
        },
        dispatchStorage(event) {
            const listener = listeners.get('storage')
            if (listener) {
                listener(event)
            }
        },
        listenerCount(type) {
            return listeners.has(type) ? 1 : 0
        },
    }
}

function createJsonResponse(payload) {
    return {
        ok: true,
        status: 200,
        statusText: 'OK',
        async json() {
            return payload
        },
    }
}

test.beforeEach(() => {
    FakeBroadcastChannel.instances.length = 0
    global.window = createWindowHarness()
    global.BroadcastChannel = FakeBroadcastChannel
    resetSharedConfigSnapshotState()
})

test.afterEach(() => {
    resetSharedConfigSnapshotState()
    delete global.BroadcastChannel
    delete global.fetch
    delete global.window
})

test('shared config snapshot store records external invalidations from BroadcastChannel', () => {
    const snapshotStore = useSharedConfigSnapshot()
    snapshotStore.applySnapshot({ dry_run: true }, '2026-03-27T09:00:00Z')

    assert.equal(FakeBroadcastChannel.instances.length, 1)
    assert.equal(global.window.listenerCount('storage'), 1)

    FakeBroadcastChannel.instances[0].emit({
        at: 42,
        id: 'external-save-1',
        origin: 'save',
        senderId: 'other-tab',
        updatedAt: '2026-03-27T09:05:00Z',
    })

    assert.equal(
        snapshotStore.latestKnownUpdatedAt.value,
        '2026-03-27T09:05:00Z',
    )
    assert.equal(
        snapshotStore.lastExternalInvalidationUpdatedAt.value,
        '2026-03-27T09:05:00Z',
    )
    assert.equal(snapshotStore.lastExternalInvalidationOrigin.value, 'save')
    assert.equal(snapshotStore.externalInvalidationToken.value, 1)
    assert.equal(snapshotStore.hasKnownNewerSnapshot.value, true)

    resetSharedConfigSnapshotState()

    assert.equal(FakeBroadcastChannel.instances[0].closed, true)
    assert.equal(global.window.listenerCount('storage'), 0)
})

test('shared config snapshot store falls back to storage events without BroadcastChannel', () => {
    delete global.BroadcastChannel
    resetSharedConfigSnapshotState()

    const snapshotStore = useSharedConfigSnapshot()
    snapshotStore.applySnapshot({ dry_run: true }, '2026-03-27T09:00:00Z')

    global.window.dispatchStorage({
        key: CONFIG_INVALIDATION_STORAGE_KEY,
        newValue: JSON.stringify({
            at: 84,
            id: 'external-restore-1',
            origin: 'restore',
            senderId: 'other-tab',
            updatedAt: '2026-03-27T09:06:00Z',
        }),
    })

    assert.equal(
        snapshotStore.latestKnownUpdatedAt.value,
        '2026-03-27T09:06:00Z',
    )
    assert.equal(snapshotStore.lastExternalInvalidationOrigin.value, 'restore')
    assert.equal(snapshotStore.externalInvalidationToken.value, 1)
})

test('shared config snapshot store distinguishes unchanged, stale, and unknown freshness states', async () => {
    const snapshotStore = useSharedConfigSnapshot()
    snapshotStore.applySnapshot({ dry_run: true }, '2026-03-27T09:00:00Z')

    const responses = [
        createJsonResponse({ updated_at: '2026-03-27T09:00:00Z' }),
        createJsonResponse({ updated_at: '2026-03-27T09:07:00Z' }),
    ]

    global.fetch = async () => {
        const nextResponse = responses.shift()
        if (!nextResponse) {
            throw new Error('network down')
        }
        return nextResponse
    }

    const unchanged = await snapshotStore.checkFreshness()
    assert.deepEqual(unchanged, {
        status: 'unchanged',
        updatedAt: '2026-03-27T09:00:00Z',
    })

    const stale = await snapshotStore.checkFreshness()
    assert.deepEqual(stale, {
        status: 'stale',
        updatedAt: '2026-03-27T09:07:00Z',
    })

    const unknown = await snapshotStore.checkFreshness()
    assert.deepEqual(unknown, {
        status: 'unknown',
        updatedAt: '2026-03-27T09:07:00Z',
    })
})

test('shared config snapshot store coalesces overlapping forced refreshes', async () => {
    const snapshotStore = useSharedConfigSnapshot()
    let resolveConfigFetch
    const fetchUrls = []

    global.fetch = async (url) => {
        fetchUrls.push(url)
        if (String(url).endsWith('/config/all')) {
            return await new Promise((resolve) => {
                resolveConfigFetch = () =>
                    resolve(createJsonResponse({ dry_run: true }))
            })
        }
        return createJsonResponse({ updated_at: '2026-03-27T09:10:00Z' })
    }

    const firstRefresh = snapshotStore.refresh()
    const secondRefresh = snapshotStore.refresh()

    resolveConfigFetch()
    const [firstResult, secondResult] = await Promise.all([
        firstRefresh,
        secondRefresh,
    ])

    assert.deepEqual(firstResult, secondResult)

    assert.equal(
        fetchUrls.filter((url) => String(url).endsWith('/config/all')).length,
        1,
    )
    assert.equal(
        fetchUrls.filter((url) => String(url).endsWith('/config/freshness'))
            .length,
        1,
    )
})
