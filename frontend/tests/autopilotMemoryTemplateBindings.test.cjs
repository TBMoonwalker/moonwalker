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
const monitoringPreviewSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterMonitoringPreview.vue',
    ),
    'utf8',
)
const configPreviewSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterConfigPreview.vue',
    ),
    'utf8',
)
const pageSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'AutopilotMemoryView.vue'),
    'utf8',
)
const statisticsSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'Statistics.vue'),
    'utf8',
)
const headerSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'AppHeader.vue'),
    'utf8',
)

test('overview workspace renders the Autopilot preview section', () => {
    assert.match(overviewSource, /ControlCenterAutopilotPreview/)
    assert.match(overviewSource, /ControlCenterConfigPreview/)
    assert.match(overviewSource, /ControlCenterMonitoringPreview/)
    assert.match(overviewSource, /@open-config/)
    assert.match(overviewSource, /@open-monitoring/)
    assert.match(overviewSource, /@toggle-autopilot/)
    assert.match(overviewSource, /@tune-autopilot/)
})

test('preview exposes the required Autopilot actions and state copy', () => {
    assert.match(previewSource, /Activate Autopilot/)
    assert.match(previewSource, /Deactivate Autopilot/)
    assert.match(previewSource, /Tune Autopilot/)
    assert.match(previewSource, /Learning from/)
    assert.match(previewSource, /Adaptive TP band/)
    assert.doesNotMatch(previewSource, /Autopilot is off'\s*"/)
    assert.doesNotMatch(previewSource, />Autopilot Memory</)
})

test('main dashboard Autopilot card opens the Autopilot page', () => {
    assert.match(statisticsSource, /role="link"/)
    assert.match(statisticsSource, /tabindex="0"/)
    assert.match(statisticsSource, /aria-label="Open Autopilot page"/)
    assert.match(statisticsSource, /@click="openAutopilotPage"/)
    assert.match(statisticsSource, /@keydown\.enter\.prevent="openAutopilotPage"/)
    assert.match(statisticsSource, /router\.push\(\{ name: 'controlCenterAutopilot' \}\)/)
})

test('full Autopilot page stays read-only and links tuning back to Advanced', () => {
    assert.match(pageSource, /Back to Control Center/)
    assert.match(pageSource, /Tune Autopilot/)
    assert.match(pageSource, /Latest Autopilot moves/)
    assert.doesNotMatch(pageSource, /n-form/i)
})

test('monitoring preview exposes the required Monitoring action and health copy', () => {
    assert.match(monitoringPreviewSource, /Open Monitoring/)
    assert.match(
        monitoringPreviewSource,
        /Monitoring needs attention|Monitoring is reconnecting|Monitoring is warming up|Monitoring is healthy/,
    )
    assert.match(monitoringPreviewSource, /Receiving payloads/)
    assert.doesNotMatch(monitoringPreviewSource, />Monitoring</)
})

test('config preview exposes the required config action and trust copy', () => {
    assert.match(configPreviewSource, /Activate live trading/)
    assert.match(configPreviewSource, /Open Setup/)
    assert.match(
        configPreviewSource,
        /Configuration is being verified|Configuration needs a reload decision|Configuration has a newer saved version|Configuration is current/,
    )
    assert.match(configPreviewSource, /Trading posture/)
    assert.doesNotMatch(configPreviewSource, />Configuration</)
})

test('header navigation keeps Control Center and removes duplicate Monitoring entry', () => {
    assert.match(headerSource, /Control Center/)
    assert.doesNotMatch(headerSource, /label:\s*'Monitoring'/)
})
