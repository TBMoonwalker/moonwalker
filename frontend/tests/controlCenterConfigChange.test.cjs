const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { createControlCenterConfigChangeSynchronizer } = loadFrontendModule(
    'src/control-center/configChangeSync.ts',
)

test('control center config change synchronizer emits invalidation for successful local changes', async () => {
    const calls = []
    const syncControlCenterConfigChange =
        createControlCenterConfigChangeSynchronizer({
            emitInvalidation(origin) {
                calls.push(['emit', origin])
            },
            async refreshWorkspace(force) {
                calls.push(['refresh', force])
                return {
                    status: 'success',
                    message: 'Reloaded workspace.',
                }
            },
        })

    await syncControlCenterConfigChange('save')
    await syncControlCenterConfigChange('restore')
    await syncControlCenterConfigChange('live_activation')

    assert.deepEqual(calls, [
        ['refresh', true],
        ['emit', 'save'],
        ['refresh', true],
        ['emit', 'restore'],
        ['refresh', true],
        ['emit', 'live_activation'],
    ])
})

test('control center config change synchronizer coalesces overlapping refreshes', async () => {
    let refreshCalls = 0
    let resolveRefresh
    const emittedOrigins = []

    const syncControlCenterConfigChange =
        createControlCenterConfigChangeSynchronizer({
            emitInvalidation(origin) {
                emittedOrigins.push(origin)
            },
            async refreshWorkspace() {
                refreshCalls += 1
                return await new Promise((resolve) => {
                    resolveRefresh = () =>
                        resolve({
                            status: 'success',
                            message: 'Reloaded workspace.',
                        })
                })
            },
        })

    const firstRefresh = syncControlCenterConfigChange('external_invalidation')
    const secondRefresh = syncControlCenterConfigChange('external_invalidation')

    resolveRefresh()
    const [firstResult, secondResult] = await Promise.all([
        firstRefresh,
        secondRefresh,
    ])

    assert.equal(firstResult.status, 'success')
    assert.deepEqual(firstResult, secondResult)
    assert.equal(refreshCalls, 1)
    assert.deepEqual(emittedOrigins, [])
})

test('control center config change synchronizer does not emit invalidation when refresh fails', async () => {
    const emittedOrigins = []
    const syncControlCenterConfigChange =
        createControlCenterConfigChangeSynchronizer({
            emitInvalidation(origin) {
                emittedOrigins.push(origin)
            },
            async refreshWorkspace() {
                return {
                    status: 'error',
                    message: 'Failed to reload configuration.',
                }
            },
        })

    const result = await syncControlCenterConfigChange('save')

    assert.equal(result.status, 'error')
    assert.deepEqual(emittedOrigins, [])
})
