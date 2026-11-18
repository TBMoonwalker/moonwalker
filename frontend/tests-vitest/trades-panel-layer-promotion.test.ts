import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

// Tests run from the frontend root.
const tradesViewPath = join(process.cwd(), 'src/views/TradesView.vue')

// Safari/WebKit can leave the trade table panel unpainted (stale white
// region) after window-resize reflows; it only repaints on the next scroll
// or resize. The panel is promoted to its own compositing layer as the
// workaround, which the resize path re-rasterizes instead of relying on
// main-frame dirty-rect repaints. The defect is not reproducible outside
// Safari, so this source-level guard protects the workaround from being
// dropped by accident.
describe('TradesView WebKit layer promotion', () => {
    it('promotes the trade table panel to its own compositing layer', async () => {
        const source = await readFile(tradesViewPath, 'utf8')
        const rule = source.match(/\.trade-table-panel\s*{[^}]*}/)?.[0] ?? ''
        expect(rule).toContain('transform: translateZ(0)')
    })
})
