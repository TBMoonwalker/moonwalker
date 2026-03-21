const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
    'utf8',
)

test('first-run control center shows the intent gate before the mission panel', () => {
    // Regression: ISSUE-006 — first-run setup showed a status-heavy mission panel
    // before asking whether the operator wanted to restore or start fresh.
    // Found by /qa on 2026-03-21
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-03-21.md
    const requiredSnippets = [
        'const showMissionPanel = computed(',
        "routeState.value.mode === 'setup'",
        'showSetupEntryGate.value || showRestoreSetupFlow.value',
        '<n-flex v-if="showMissionPanel" class="page-section" vertical>',
        'class="setup-entry-intro"',
        'class="workspace-kicker"',
        '<h1 class="workspace-title">How do you want to begin?</h1>',
    ]

    for (const snippet of requiredSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center first-run hierarchy to include ${snippet}`,
        )
    }
})
