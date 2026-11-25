const assert = require('node:assert/strict')
const test = require('node:test')

// Self-hosted font build contract (DV-2, 2026-11-25 design review):
// build.assetsInlineLimit must keep every .woff2 as a separate file so
// unicode-range can gate each subset at the network level, while everything
// else keeps Vite's default 4KB inline threshold. The build-boundary test
// proves the woff2 side end-to-end; this pins the function's own branches
// and the 4096 boundary so a config "simplification" cannot silently
// re-inline small font subsets or change unrelated asset behavior.
//
// Value: protects=the assetsInlineLimit contract (woff2 never inlined;
// everything else keeps Vite's 4KB default with the 4095/4096 boundary);
// fails_when=the function is simplified, collapsed to a boolean, or Vite's
// contract changes and small font subsets get re-inlined; why_new=the
// build-boundary test proves real-build woff2 emission but not the
// function's branches or the non-woff2 default; seam=none; no_claim=unit
// level - real asset emission is the buildLazyBoundaries bundle assertion.

const CONTENT = (size) => new Uint8Array(size)

test('assetsInlineLimit keeps woff2 out of the inline threshold', async () => {
    const { default: config } = await import('../vite.config.mts')
    const limit = config.build.assetsInlineLimit
    assert.equal(typeof limit, 'function', 'assetsInlineLimit must be a function')
    assert.equal(limit('assets/fonts/general-sans-400.woff2', CONTENT(100)), false)
    assert.equal(limit('assets/fonts/x.woff2', CONTENT(1024 * 1024)), false)
})

test('assetsInlineLimit keeps the 4KB default for non-woff2 assets', async () => {
    const { default: config } = await import('../vite.config.mts')
    const limit = config.build.assetsInlineLimit
    assert.equal(limit('assets/logo.png', CONTENT(10)), true)
    assert.equal(limit('assets/logo.png', CONTENT(4095)), true)
    assert.equal(limit('assets/logo.png', CONTENT(4096)), false)
    assert.equal(limit('assets/logo.png', CONTENT(1024 * 1024)), false)
    assert.equal(limit('components/icon.svg', CONTENT(10)), true)
})
