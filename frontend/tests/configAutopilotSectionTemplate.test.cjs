const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const autopilotSectionSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'config',
        'ConfigAutopilotSection.vue',
    ),
    'utf8',
)

test('Autopilot settings name base-order stretch and omit unused safety stretch', () => {
    assert.match(autopilotSectionSource, /Base order stretch multiplier/)
    assert.match(autopilotSectionSource, /base_order_stretch_max_multiplier/)
    assert.doesNotMatch(autopilotSectionSource, /Entry stretch multiplier/)
    assert.doesNotMatch(autopilotSectionSource, /Safety stretch multiplier/)
    assert.doesNotMatch(autopilotSectionSource, /safety_stretch_max_multiplier/)
})
