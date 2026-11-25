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
                // Self-hosted font subsets (DV-2): every woff2 must ship as a
                // separate asset so unicode-range can gate it at the network
                // level; inlining it as a data URI would defeat the gating.
                //
                // Value: protects=real production bundles emit all 23 woff2
                // as separate hashed assets and no CSS inlines a font data
                // URI; fails_when=assetsInlineLimit is removed or changed and
                // unicode-range network gating is defeated (data-URI faces
                // load fine, so the e2e font gate would stay green); why_new=
                // the existing lazy-boundary assertions cover route chunks,
                // not font assets; seam=none; no_claim=build output only -
                // network-level fetch behavior is the e2e's.
                const woff2Assets = Object.values(bundle).filter(
                    (item) => item.type === 'asset' && item.fileName.endsWith('.woff2'),
                )
                assert.equal(
                    woff2Assets.length,
                    23,
                    `expected the 23 vendored woff2 files as separate assets, found ${woff2Assets.length}`,
                )
                for (const item of Object.values(bundle)) {
                    if (item.type !== 'asset' || !item.fileName.endsWith('.css')) continue
                    const source = Buffer.isBuffer(item.source)
                        ? item.source.toString('utf8')
                        : String(item.source)
                    assert.ok(
                        !source.includes('data:font/woff2')
                            && !source.includes('data:application/font-woff2'),
                        `a font subset was inlined into ${item.fileName}`,
                    )
                }
                checked = true
            },
        }],
    })
    assert.ok(checked, 'build dependency check did not run')
})
