const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
    'utf8',
)
const setupFlowSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterSetupFlow.ts',
    ),
    'utf8',
)
const missionPanelSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterMissionPanel.vue',
    ),
    'utf8',
)
const advancedWorkspaceSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterAdvancedWorkspace.vue',
    ),
    'utf8',
)
const modeStripSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterModeStrip.vue',
    ),
    'utf8',
)
const overviewWorkspaceSource = fs.readFileSync(
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
const utilitiesWorkspaceSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterUtilitiesWorkspace.vue',
    ),
    'utf8',
)
const feedbackSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterFeedback.ts',
    ),
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
const workspaceActionsSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterWorkspaceActions.ts',
    ),
    'utf8',
)
const derivedStateSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterDerivedState.ts',
    ),
    'utf8',
)
const workspaceRefreshSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterWorkspaceRefresh.ts',
    ),
    'utf8',
)

test('control center target sections use dynamic element refs', () => {
    // Regression: ISSUE-003 — "Fix this" could not jump because setup targets
    // were bound as literal ref strings instead of dynamic ref callbacks.
    // Found by /qa on 2026-03-20
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-03-20.md
    assert.ok(
        controlCenterViewSource.includes('<ControlCenterSetupWorkspace'),
        'expected setup targets to be routed through the setup workspace component',
    )
    assert.ok(
        controlCenterViewSource.includes(
            ':bind-target-element="bindTargetElement"',
        ),
        'expected the setup workspace to receive the target ref binder',
    )
    assert.ok(
        controlCenterViewSource.includes(
            ":bind-backup-restore-target-ref=\"bindTargetElement('backup-restore')\"",
        ),
        'expected the utilities workspace to receive the backup target ref binder',
    )
    assert.ok(
        setupWorkspaceSource.includes(':ref="bindTargetElement(task.target)"'),
        'expected setup task sections to use dynamic target ref bindings',
    )
    assert.ok(
        utilitiesWorkspaceSource.includes(':ref="bindBackupRestoreTargetRef"'),
        'expected the utilities workspace to expose the backup target ref binding',
    )

    assert.equal(
        /(?:^|[\s<])ref="bindTargetElement\('[^']+'\)"/m.test(
            controlCenterViewSource,
        ),
        false,
    )
    assert.ok(
        controlCenterViewSource.includes(
            ":live-activation-ref=\"bindTargetElement('live-activation')\"",
        ),
        'expected live activation anchor to stay wired through the overview component',
    )
    assert.ok(
        overviewWorkspaceSource.includes(':ref="liveActivationRef"'),
        'expected overview workspace to expose the live activation anchor ref',
    )
})

test('control center gates first-run setup behind explicit onboarding choices', () => {
    // Regression: FINDING-001/FINDING-004 — first run exposed all peer modes
    // immediately and buried restore inside Utilities instead of asking for the
    // operator's intent up front.
    const requiredViewSnippets = [
        "import { useControlCenterSetupFlow } from '../composables/useControlCenterSetupFlow'",
        "import ControlCenterSetupWorkspace from '../components/control-center/ControlCenterSetupWorkspace.vue'",
        '} = useControlCenterSetupFlow({',
        'showSetupEntryGate,',
        'showRestoreSetupFlow,',
        'setupShowsAdvancedFields,',
        '<ControlCenterSetupWorkspace',
    ]
    const requiredSetupWorkspaceSnippets = [
        'How do you want to begin?',
        'Restore existing installation',
        'Start a new setup',
    ]
    const requiredSetupFlowSnippets = [
        "const showSetupEntryGate = computed(",
        "const showRestoreSetupFlow = computed(",
        "const setupShowsAdvancedFields = computed(",
        "setupStyle.value === 'full'",
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupWorkspaceSnippets) {
        assert.ok(
            setupWorkspaceSource.includes(snippet),
            `expected setup workspace to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupFlowSnippets) {
        assert.ok(
            setupFlowSource.includes(snippet),
            `expected setup flow to include ${snippet}`,
        )
    }
})

test('control center keeps guided setup focused and avoids duplicate advanced headings', () => {
    const requiredViewSnippets = [
        '<ControlCenterSetupWorkspace',
        ':show-debug="setupShowsAdvancedFields"',
    ]
    const requiredSetupWorkspaceSnippets = [
        'class="setup-progress-grid"',
        'slot :name="task.target"',
        'Choose your setup pace',
    ]
    const requiredAdvancedWorkspaceSnippets = [
        'slot :name="section.target"',
    ]
    const requiredUtilitiesWorkspaceSnippets = [
        'Complete Telegram credentials in Setup first.',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupWorkspaceSnippets) {
        assert.ok(
            setupWorkspaceSource.includes(snippet),
            `expected setup workspace to include ${snippet}`,
        )
    }
    for (const snippet of requiredAdvancedWorkspaceSnippets) {
        assert.ok(
            advancedWorkspaceSource.includes(snippet),
            `expected advanced workspace to include ${snippet}`,
        )
    }
    for (const snippet of requiredUtilitiesWorkspaceSnippets) {
        assert.ok(
            utilitiesWorkspaceSource.includes(snippet),
            `expected utilities workspace to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes('Expert tuning'),
        false,
        'expected advanced view to avoid a duplicate intro card heading',
    )
})

test('collapsed setup shells route clicks to their section', () => {
    const requiredViewSnippets = [
        'function isInteractiveTarget(',
        'function handleSetupSectionShellClick(',
        "target.closest('button, a, input, select, textarea, label, [role=\"button\"]')",
        '@setup-shell-click="handleSetupSectionShellClick"',
    ]
    const requiredSetupWorkspaceSnippets = [
        "@click=\"emit('setup-shell-click', task.target, $event)\"",
        "@click=\"emit('select-setup-target', task.target)\"",
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupWorkspaceSnippets) {
        assert.ok(
            setupWorkspaceSource.includes(snippet),
            `expected setup workspace to include ${snippet}`,
        )
    }
})

test('control center delegates runtime activation handling to a dedicated composable', () => {
    const requiredSnippets = [
        "import { useControlCenterRuntimeActions } from '../composables/useControlCenterRuntimeActions'",
        '} = useControlCenterRuntimeActions({',
        'handleActivateLiveTrading,',
        'handleReloadAfterStalePrompt,',
        'handleDetectedExternalConfigChange,',
        'checkForExternalConfigChanges,',
    ]

    for (const snippet of requiredSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes(
            'async function handleActivateLiveTrading(): Promise<void> {',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function handleReloadAfterStalePrompt(): Promise<void> {',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function handleDetectedExternalConfigChange(',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function checkForExternalConfigChanges(): Promise<void> {',
        ),
        false,
    )
})

test('control center delegates setup flow handling to a dedicated composable', () => {
    const requiredSnippets = [
        "import { useControlCenterSetupFlow } from '../composables/useControlCenterSetupFlow'",
        '} = useControlCenterSetupFlow({',
        'handleSetupEntryChoice,',
        'handleSetupStyleChange,',
        'handleSetupTaskSelect,',
        'handleMissionPrimaryAction,',
        'initializeSetupFlow,',
        'syncSetupChoiceForReadiness,',
    ]

    for (const snippet of requiredSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes(
            'async function handleSetupEntryChoice(',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'function handleSetupStyleChange(',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function handleSetupTaskSelect(',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function handleMissionPrimaryAction(',
        ),
        false,
    )
})

test('control center delegates navigation and guided focus handling to a dedicated composable', () => {
    const requiredSnippets = [
        "import { useControlCenterNavigation } from '../composables/useControlCenterNavigation'",
        '} = useControlCenterNavigation({',
        'focusTarget,',
        'guideToTarget,',
        'handleModeSelect,',
        'navigateToControlCenter,',
    ]

    for (const snippet of requiredSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes(
            'async function navigateToControlCenter(',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function focusTarget(',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function guideToTarget(',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function handleModeSelect(',
        ),
        false,
    )
})

test('control center delegates feedback and mission-state handling to dedicated composables', () => {
    const requiredViewSnippets = [
        "import { useControlCenterFeedback } from '../composables/useControlCenterFeedback'",
        "import { useControlCenterMissionState } from '../composables/useControlCenterMissionState'",
        '} = useControlCenterFeedback()',
        '} = useControlCenterMissionState({',
        'liveRegionMessage,',
        'transitionIntent,',
        'missionAlertTone,',
        'missionSummaryTone,',
        'showMissionPanel,',
    ]
    const requiredFeedbackSnippets = [
        'function announce(messageText: string | null): void {',
        'function setTransitionIntent(nextIntent: ControlCenterTransitionIntent): void {',
        'function disposeFeedback(): void {',
    ]
    const requiredMissionSnippets = [
        'const showMissionPanel = computed(',
        'const missionSummaryTone = computed(',
        'const missionAlertTone = computed(',
        'const dirtySummary = computed(',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredFeedbackSnippets) {
        assert.ok(
            feedbackSource.includes(snippet),
            `expected feedback state to include ${snippet}`,
        )
    }
    for (const snippet of requiredMissionSnippets) {
        assert.ok(
            missionStateSource.includes(snippet),
            `expected mission state to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes(
            'function announce(messageText: string | null): void {',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'function setTransitionIntent(nextIntent:',
        ),
        false,
    )
})

test('control center delegates mission, mode, and overview presentation to dedicated components', () => {
    const requiredViewSnippets = [
        "import ControlCenterMissionPanel from '../components/control-center/ControlCenterMissionPanel.vue'",
        "import ControlCenterModeStrip from '../components/control-center/ControlCenterModeStrip.vue'",
        "import ControlCenterOverviewWorkspace from '../components/control-center/ControlCenterOverviewWorkspace.vue'",
        '<ControlCenterMissionPanel',
        '<ControlCenterModeStrip',
        '<ControlCenterOverviewWorkspace',
    ]
    const requiredMissionPanelSnippets = [
        'Save changes',
        'Reload latest config',
        'The shared snapshot changed in another browser or tab.',
    ]
    const requiredModeStripSnippets = [
        'Primary',
        'Expert and utility',
        "emit('select-mode', 'overview')",
        "emit('select-mode', 'utilities')",
    ]
    const requiredOverviewSnippets = [
        'Targeted recovery cards',
        'Calm operator overview',
        'Activate live trading',
        ':ref="liveActivationRef"',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredMissionPanelSnippets) {
        assert.ok(
            missionPanelSource.includes(snippet),
            `expected mission panel component to include ${snippet}`,
        )
    }
    for (const snippet of requiredModeStripSnippets) {
        assert.ok(
            modeStripSource.includes(snippet),
            `expected mode strip component to include ${snippet}`,
        )
    }
    for (const snippet of requiredOverviewSnippets) {
        assert.ok(
            overviewWorkspaceSource.includes(snippet),
            `expected overview workspace component to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes('Calm operator overview'),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes('Reload latest config'),
        false,
    )
})

test('control center delegates setup workspace presentation to a dedicated component', () => {
    const requiredViewSnippets = [
        "import ControlCenterSetupWorkspace from '../components/control-center/ControlCenterSetupWorkspace.vue'",
        '<ControlCenterSetupWorkspace',
        '@select-entry-choice="handleSetupEntryChoice"',
        '@select-setup-style="handleSetupStyleChange"',
        '@select-setup-target="handleSetupTaskSelect"',
        '@setup-shell-click="handleSetupSectionShellClick"',
        '<template #general>',
        '<template #exchange>',
        '<template #signal>',
        '<template #dca>',
        '<template #monitoring>',
    ]
    const requiredSetupWorkspaceSnippets = [
        'Restore and review',
        'Choose your setup pace',
        'slot :name="task.target"',
        "@click=\"emit('restore-backup', 'config')\"",
        "@click=\"emit('select-entry-choice', 'restore')\"",
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupWorkspaceSnippets) {
        assert.ok(
            setupWorkspaceSource.includes(snippet),
            `expected setup workspace to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes('Restore and review'),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes('Choose your setup pace'),
        false,
    )
})

test('control center delegates advanced and utilities presentation to dedicated components', () => {
    const requiredViewSnippets = [
        "import ControlCenterAdvancedWorkspace from '../components/control-center/ControlCenterAdvancedWorkspace.vue'",
        "import ControlCenterUtilitiesWorkspace from '../components/control-center/ControlCenterUtilitiesWorkspace.vue'",
        '<ControlCenterAdvancedWorkspace',
        '<ControlCenterUtilitiesWorkspace',
        '@update:backup-include-trade-data="backupIncludeTradeData = $event"',
    ]
    const requiredAdvancedWorkspaceSnippets = [
        'slot :name="section.target"',
        'task-section-header',
    ]
    const requiredUtilitiesWorkspaceSnippets = [
        'Backup & Restore',
        'Connectivity test',
        "@click=\"emit('monitoring-test')\"",
        "@update:checked=\"emit('update:backup-include-trade-data', $event)\"",
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredAdvancedWorkspaceSnippets) {
        assert.ok(
            advancedWorkspaceSource.includes(snippet),
            `expected advanced workspace to include ${snippet}`,
        )
    }
    for (const snippet of requiredUtilitiesWorkspaceSnippets) {
        assert.ok(
            utilitiesWorkspaceSource.includes(snippet),
            `expected utilities workspace to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes('Backup & Restore'),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes('Connectivity test'),
        false,
    )
})

test('control center delegates derived readiness and route state to a dedicated composable', () => {
    const requiredViewSnippets = [
        "import { useControlCenterDerivedState } from '../composables/useControlCenterDerivedState'",
        '} = useControlCenterDerivedState({',
        'configTrustState,',
        'effectiveLoadError,',
        'readiness,',
        'routeState,',
        'viewState,',
        'visibleBlockers,',
    ]
    const requiredDerivedStateSnippets = [
        'const effectiveLoadError = computed(',
        'const readiness = computed(',
        'const visibleBlockers = computed(() => {',
        'const viewState = computed(() =>',
        'const routeState = computed(() =>',
        'const configTrustState = computed(() =>',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredDerivedStateSnippets) {
        assert.ok(
            derivedStateSource.includes(snippet),
            `expected derived state composable to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes('const effectiveLoadError = computed('),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes('const readiness = computed('),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes('const visibleBlockers = computed(() => {'),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes('const viewState = computed(() =>'),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes('const routeState = computed(() =>'),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes('const configTrustState = computed(() =>'),
        false,
    )
})

test('control center delegates workspace action wrappers to a dedicated composable', () => {
    const requiredViewSnippets = [
        "import { useControlCenterWorkspaceActions } from '../composables/useControlCenterWorkspaceActions'",
        '} = useControlCenterWorkspaceActions({',
        'handleSubmitWorkspace,',
        'handleBackupDownloadAction,',
        'handleRestoreBackupAction,',
        'handleMonitoringTestAction,',
    ]
    const requiredWorkspaceActionSnippets = [
        'async function handleSubmitWorkspace(): Promise<void> {',
        'async function handleBackupDownloadAction(): Promise<void> {',
        'async function handleRestoreBackupAction(',
        'async function handleMonitoringTestAction(): Promise<void> {',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredWorkspaceActionSnippets) {
        assert.ok(
            workspaceActionsSource.includes(snippet),
            `expected workspace actions to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes(
            'async function handleSubmitWorkspace(): Promise<void> {',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function handleBackupDownloadAction(): Promise<void> {',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function handleRestoreBackupAction(',
        ),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function handleMonitoringTestAction(): Promise<void> {',
        ),
        false,
    )
})

test('control center delegates shared snapshot refresh handling to a dedicated composable', () => {
    const requiredViewSnippets = [
        "import { useControlCenterWorkspaceRefresh } from '../composables/useControlCenterWorkspaceRefresh'",
        'const { refreshWorkspaceFromSnapshot } = useControlCenterWorkspaceRefresh({',
        'readRouteState: () => routeState.value,',
        'readViewState: () => viewState.value,',
    ]
    const requiredRefreshSnippets = [
        'async function refreshWorkspaceFromSnapshot(',
        'await options.snapshotStore.refresh()',
        'await options.snapshotStore.ensureLoaded(false)',
        'await options.router.replace({',
        'buildControlCenterQuery(normalizedState)',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredRefreshSnippets) {
        assert.ok(
            workspaceRefreshSource.includes(snippet),
            `expected workspace refresh composable to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes(
            'async function refreshWorkspaceFromSnapshot(',
        ),
        false,
    )
})
