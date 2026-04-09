const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const previewSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterAutopilotPreview.vue',
    ),
    'utf8',
)
const overviewSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterOverviewWorkspace.vue',
    ),
    'utf8',
)
const pageSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'AutopilotMemoryView.vue'),
    'utf8',
)

test('overview workspace renders the Autopilot preview section', () => {
    assert.match(overviewSource, /ControlCenterAutopilotPreview/)
    assert.match(overviewSource, /@open-autopilot/)
    assert.match(overviewSource, /@tune-autopilot/)
})

test('preview exposes the required Autopilot actions and state copy', () => {
    assert.match(previewSource, /Open Autopilot/)
    assert.match(previewSource, /Tune Autopilot/)
    assert.match(previewSource, /Learning from/)
    assert.match(previewSource, /Adaptive TP band/)
})

test('full Autopilot page stays read-only and links tuning back to Advanced', () => {
    assert.match(pageSource, /Back to Control Center/)
    assert.match(pageSource, /Tune Autopilot/)
    assert.match(pageSource, /Latest Autopilot moves/)
    assert.doesNotMatch(pageSource, /n-form/i)
})
