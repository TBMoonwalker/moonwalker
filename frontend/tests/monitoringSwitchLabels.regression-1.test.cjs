const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const monitoringLogPanelSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'MonitoringLogPanel.vue'),
    'utf8',
)

test('monitoring log switches expose distinct accessible names', () => {
    // Regression: ISSUE-002 — both switches were announced only as generic controls.
    // Found by /qa on 2026-07-17.
    // Report: .gstack/qa-reports/qa-report-192-168-6-5-8150-2026-07-17.md
    assert.ok(
        monitoringLogPanelSource.includes(
            'v-model:value="paused" aria-label="Pause log polling"',
        ),
        'expected the pause switch to name its polling action',
    )
    assert.ok(
        monitoringLogPanelSource.includes(
            'v-model:value="followTail" aria-label="Follow log tail"',
        ),
        'expected the follow-tail switch to name its log-tail action',
    )
})
