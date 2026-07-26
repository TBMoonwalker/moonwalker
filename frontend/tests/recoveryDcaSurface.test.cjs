const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const rootDir = path.resolve(__dirname, '..')

test('advanced DCA settings expose shadow and bounded recovery modes', () => {
    const source = fs.readFileSync(
        path.join(
            rootDir,
            'src/components/config/ConfigDcaAdvancedSection.vue',
        ),
        'utf8',
    )

    assert.match(source, /Recovery safety orders/)
    assert.match(source, /recovery_shadow/)
    assert.match(source, /recovery_target/)
    assert.match(source, /Maximum quote per deal/)
    assert.match(source, /Trading candles/)
    assert.match(source, /value: 'trading'/)
    assert.match(source, /only when a new deal opens/)
})

test('open trade expansion exposes recovery trigger and projected TP', () => {
    const source = fs.readFileSync(
        path.join(rootDir, 'src/components/OpenTradeExpandedRow.vue'),
        'utf8',
    )

    assert.match(source, /Recovery DCA status/)
    assert.match(source, /Next trigger/)
    assert.match(source, /Reference ATR/)
    assert.match(source, /Projected TP/)
    assert.match(source, /Last sized SO/)
})
