const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
    'utf8',
)
const missionStateSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterMissionState.ts',
    ),
    'utf8',
)
const setupModeSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterSetupMode.vue',
    ),
    'utf8',
)
const setupWorkspaceSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterSetupWorkspace.vue',
    ),
    'utf8',
)
const setupEntryGateSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterSetupEntryGate.vue',
    ),
    'utf8',
)

test('first-run control center shows the intent gate before the mission panel', () => {
    // Regression: ISSUE-006 — first-run setup showed a status-heavy mission panel
    // before asking whether the operator wanted to restore or start fresh.
    // Found by /qa on 2026-03-21
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-03-21.md
    const requiredViewSnippets = [
        "import { useControlCenterMissionState } from '../composables/useControlCenterMissionState'",
        "import ControlCenterMissionPanel from '../components/control-center/ControlCenterMissionPanel.vue'",
        "import ControlCenterSetupMode from '../components/control-center/ControlCenterSetupMode.vue'",
        '} = useControlCenterMissionState({',
        '<ControlCenterMissionPanel',
        '<ControlCenterSetupMode',
    ]
    const requiredSetupModeSnippets = [
        "import ControlCenterSetupWorkspace from './ControlCenterSetupWorkspace.vue'",
        '<ControlCenterSetupWorkspace',
    ]
    const requiredSetupWorkspaceSnippets = [
        "import ControlCenterSetupEntryGate from './ControlCenterSetupEntryGate.vue'",
        '<ControlCenterSetupEntryGate',
    ]
    const requiredSetupEntryGateSnippets = [
        'class="setup-entry-intro"',
        'class="workspace-kicker"',
        '<h1 class="workspace-title">How do you want to begin?</h1>',
    ]
    const requiredMissionStateSnippets = [
        'const showMissionPanel = computed(',
        "routeState.value.mode === 'setup'",
        'options.showSetupEntryGate.value ||',
        'options.showRestoreSetupFlow.value',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center first-run hierarchy to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupModeSnippets) {
        assert.ok(
            setupModeSource.includes(snippet),
            `expected setup mode to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupWorkspaceSnippets) {
        assert.ok(
            setupWorkspaceSource.includes(snippet),
            `expected setup workspace to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupEntryGateSnippets) {
        assert.ok(
            setupEntryGateSource.includes(snippet),
            `expected setup entry gate to include ${snippet}`,
        )
    }
    for (const snippet of requiredMissionStateSnippets) {
        assert.ok(
            missionStateSource.includes(snippet),
            `expected mission state to include ${snippet}`,
        )
    }
})
