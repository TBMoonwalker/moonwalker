const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const signalSectionSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'config',
        'ConfigSignalSection.vue',
    ),
    'utf8',
)
const openTradeColumnsSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useOpenTradeColumns.ts',
    ),
    'utf8',
)

test('signal source owns the optional delisting protection setting', () => {
    assert.match(signalSectionSource, /Protect against delisting/)
    assert.match(
        signalSectionSource,
        /v-model:value="signal\.delisting_protection_enabled"/,
    )
    assert.match(
        signalSectionSource,
        /Existing exits remain enabled\./,
    )
})

test('open trade table marks delisting risk and disables manual buys', () => {
    assert.match(openTradeColumnsSource, /Boolean\(rowData\.delisting_warning\)/)
    assert.match(openTradeColumnsSource, /Delisting risk/)
    assert.match(openTradeColumnsSource, /Scheduled for delisting at/)
})
