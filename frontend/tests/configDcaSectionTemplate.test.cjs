const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const dcaSectionSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'config',
        'ConfigDcaSection.vue',
    ),
    'utf8',
)

test('DCA settings warns when TP limit pre-arm conflicts with TP guards', () => {
    assert.match(dcaSectionSource, /<n-alert[\s\S]+type="warning"/)
    assert.match(dcaSectionSource, /showTpLimitPrearmConflictWarning/)
    assert.match(dcaSectionSource, /TP limit pre-arm does not support/)
    assert.match(dcaSectionSource, /props\.dca\.trailing_tp/)
    assert.match(dcaSectionSource, /props\.dca\.tp_spike_confirm_enabled/)
})
