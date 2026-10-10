const assert = require('node:assert/strict')
const path = require('node:path')
const test = require('node:test')
const { gzipSync } = require('node:zlib')

test('production startup keeps charts behind lazy route boundaries', async () => {
    const { build } = await import('vite')
    const frontendRoot = path.resolve(__dirname, '..')
    let checked = false

    await build({
        root: frontendRoot,
        configFile: path.join(frontendRoot, 'vite.config.mts'),
        logLevel: 'error',
        build: { write: false },
        plugins: [{
            name: 'verify-startup-dependencies',
            generateBundle(_options, bundle) {
                const chunks = Object.values(bundle).filter(
                    (item) => item.type === 'chunk',
                )
                const byName = new Map(chunks.map((chunk) => [chunk.fileName, chunk]))
                const entry = chunks.find((chunk) => chunk.isEntry)
                assert.ok(entry, 'missing application entry')
                const startup = new Set()
                function visit(name) {
                    if (startup.has(name) || !byName.has(name)) return
                    startup.add(name)
                    for (const dependency of byName.get(name).imports) visit(dependency)
                }
                visit(entry.fileName)
                const modules = [...startup].flatMap(
                    (name) => Object.keys(byName.get(name).modules),
                )
                const eagerCharts = modules.filter(
                    (id) => /\/node_modules\/(echarts|zrender|vue-echarts)\//.test(id),
                )
                assert.deepEqual(eagerCharts, [], 'chart code became a startup dependency')
                const compressedBytes = [...startup].reduce(
                    (total, name) => total + gzipSync(byName.get(name).code).length,
                    0,
                )
                assert.ok(
                    compressedBytes < 250_000,
                    `startup JS exceeded its 250 KB gzip budget: ${compressedBytes}`,
                )
                for (const view of ['MonitoringView', 'StatisticsView', 'ControlCenterView']) {
                    assert.ok(chunks.some((chunk) =>
                        chunk.isDynamicEntry &&
                        chunk.facadeModuleId?.endsWith(`/views/${view}.vue`),
                    ), `${view} lost its lazy entry`)
                }
                checked = true
            },
        }],
    })
    assert.ok(checked, 'build dependency check did not run')
})
