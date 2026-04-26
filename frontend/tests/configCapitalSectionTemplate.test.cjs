const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const capitalSectionSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'config',
        'ConfigCapitalSection.vue',
    ),
    'utf8',
)

test('Capital settings expose buffer only for dynamic DCA', () => {
    assert.match(
        capitalSectionSource,
        /Budget buffer for dynamic safety orders \(%\)/,
    )
    assert.match(capitalSectionSource, /v-if="dynamicDcaEnabled"/)
    assert.match(capitalSectionSource, /dynamicDcaEnabled: boolean/)
    assert.doesNotMatch(capitalSectionSource, /Budget buffer \(%\)/)
})
