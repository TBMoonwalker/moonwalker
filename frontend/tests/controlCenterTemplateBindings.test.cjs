const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
    'utf8',
)
const blockersSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'control-center', 'blockers.ts'),
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
const advancedModeSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterAdvancedMode.vue',
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
const ownerConfidenceSummarySource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterOwnerConfidenceSummary.vue',
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
const setupProgressGridSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterSetupProgressGrid.vue',
    ),
    'utf8',
)
const setupRestoreFlowSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterSetupRestoreFlow.vue',
    ),
    'utf8',
)
const setupStyleSelectorSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterSetupStyleSelector.vue',
    ),
    'utf8',
)
const setupTaskSectionSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterSetupTaskSection.vue',
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
const setupShellInteractionsSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterSetupShellInteractions.ts',
    ),
    'utf8',
)
const targetRegistrySource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterTargetRegistry.ts',
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
const lifecycleSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useControlCenterLifecycle.ts',
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
        controlCenterViewSource.includes('<ControlCenterSetupMode'),
        'expected setup targets to be routed through the setup mode component',
    )
    assert.ok(
        setupModeSource.includes(':bind-target-element="bindTargetElement"'),
        'expected the setup mode to forward target bindings into the setup workspace',
    )
    assert.ok(
        controlCenterViewSource.includes(
            "import { useControlCenterTargetRegistry } from '../composables/useControlCenterTargetRegistry'",
        ),
        'expected target bindings to come from the target registry composable',
    )
    assert.ok(
        controlCenterViewSource.includes(
            ":bind-backup-restore-target-ref=\"bindTargetElement('backup-restore')\"",
        ),
        'expected the utilities workspace to receive the backup target ref binder',
    )
    assert.ok(
        setupTaskSectionSource.includes(':ref="bindTargetElement(task.target)"'),
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
    assert.equal(
        overviewWorkspaceSource.includes(':ref="liveActivationRef"'),
        false,
    )
    assert.ok(
        overviewWorkspaceSource.includes(
            ':ref="visibleBlockers.length === 0 ? liveActivationRef : undefined"',
        ),
        'expected overview workspace to expose the live activation anchor ref on the overview shell',
    )
    assert.ok(
        targetRegistrySource.includes(
            'export function useControlCenterTargetRegistry()',
        ),
        'expected target registry composable to expose the binding seam',
    )
    assert.equal(
        controlCenterViewSource.includes('const targetElements: Record<'),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'function bindTargetElement(target: ControlCenterTarget)',
        ),
        false,
    )
})

test('control center gates first-run setup behind explicit onboarding choices', () => {
    // Regression: FINDING-001/FINDING-004 — first run exposed all peer modes
    // immediately and buried restore inside Utilities instead of asking for the
    // operator's intent up front.
    const requiredViewSnippets = [
        "import { useControlCenterSetupFlow } from '../composables/useControlCenterSetupFlow'",
        "import ControlCenterSetupMode from '../components/control-center/ControlCenterSetupMode.vue'",
        '} = useControlCenterSetupFlow({',
        'showSetupEntryGate,',
        'showRestoreSetupFlow,',
        'setupShowsAdvancedFields,',
        '<ControlCenterSetupMode',
    ]
    const requiredSetupModeSnippets = [
        "from '../../config-editor/types'",
        "import ControlCenterSetupWorkspace from './ControlCenterSetupWorkspace.vue'",
        '<ControlCenterSetupWorkspace',
    ]
    const requiredSetupWorkspaceSnippets = [
        "import ControlCenterSetupEntryGate from './ControlCenterSetupEntryGate.vue'",
        '<ControlCenterSetupEntryGate',
    ]
    const requiredSetupEntryGateSnippets = [
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
    for (const snippet of requiredSetupFlowSnippets) {
        assert.ok(
            setupFlowSource.includes(snippet),
            `expected setup flow to include ${snippet}`,
        )
    }
})

test('control center keeps guided setup focused and avoids duplicate advanced headings', () => {
    const requiredViewSnippets = [
        '<ControlCenterSetupMode',
    ]
    const requiredSetupModeSnippets = [
        ':show-debug="setupShowsAdvancedFields"',
    ]
    const requiredSetupWorkspaceSnippets = [
        "import ControlCenterSetupProgressGrid from './ControlCenterSetupProgressGrid.vue'",
        "import ControlCenterSetupStyleSelector from './ControlCenterSetupStyleSelector.vue'",
        "import ControlCenterSetupTaskSection from './ControlCenterSetupTaskSection.vue'",
        '<ControlCenterSetupProgressGrid',
        '<ControlCenterSetupStyleSelector',
        '<ControlCenterSetupTaskSection',
    ]
    const requiredSetupProgressSnippets = [
        'class="setup-progress-grid"',
    ]
    const requiredSetupStyleSnippets = [
        'Choose your setup pace',
    ]
    const requiredSetupTaskSectionSnippets = [
        '<slot />',
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
    for (const snippet of requiredSetupProgressSnippets) {
        assert.ok(
            setupProgressGridSource.includes(snippet),
            `expected setup progress grid to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupStyleSnippets) {
        assert.ok(
            setupStyleSelectorSource.includes(snippet),
            `expected setup style selector to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupTaskSectionSnippets) {
        assert.ok(
            setupTaskSectionSource.includes(snippet),
            `expected setup task section to include ${snippet}`,
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
        "import { useControlCenterSetupShellInteractions } from '../composables/useControlCenterSetupShellInteractions'",
        'useControlCenterSetupShellInteractions({',
        'handleSetupSectionShellClick',
        '@setup-shell-click="handleSetupSectionShellClick"',
    ]
    const requiredSetupModeSnippets = [
        '<ControlCenterSetupWorkspace',
        '@setup-shell-click="(target, event) => emit(\'setup-shell-click\', target, event)"',
    ]
    const requiredSetupShellSnippets = [
        'function defaultIsInteractiveTarget(',
        'async function handleSetupSectionShellClick(',
        "target.closest('button, a, input, select, textarea, label, [role=\"button\"]')",
    ]
    const requiredSetupWorkspaceSnippets = ['<ControlCenterSetupTaskSection']
    const requiredSetupTaskSectionSnippets = [
        "@click=\"emit('setup-shell-click', task.target, $event)\"",
        "@click=\"emit('select-setup-target', task.target)\"",
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupModeSnippets) {
        assert.ok(
            setupModeSource.includes(snippet),
            `expected setup mode to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupShellSnippets) {
        assert.ok(
            setupShellInteractionsSource.includes(snippet),
            `expected setup shell interactions to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupWorkspaceSnippets) {
        assert.ok(
            setupWorkspaceSource.includes(snippet),
            `expected setup workspace to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupTaskSectionSnippets) {
        assert.ok(
            setupTaskSectionSource.includes(snippet),
            `expected setup task section to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes('function isInteractiveTarget('),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes(
            'async function handleSetupSectionShellClick(',
        ),
        false,
    )
})

test('control center delegates lifecycle and window wiring to a dedicated composable', () => {
    const requiredViewSnippets = [
        "import { useControlCenterLifecycle } from '../composables/useControlCenterLifecycle'",
        'useControlCenterLifecycle({',
        'confirmDiscardUnsavedChanges,',
        'handleDetectedExternalConfigChange,',
        'refreshWorkspaceFromSnapshot,',
        'syncSetupChoiceForReadiness,',
    ]
    const requiredLifecycleSnippets = [
        'export function createControlCenterLifecycleHandlers(',
        'export function useControlCenterLifecycle(',
        "windowObject.addEventListener(",
        "windowObject.removeEventListener(",
        'hooks.watch(',
        'hooks.onMounted(handlers.handleMounted)',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredLifecycleSnippets) {
        assert.ok(
            lifecycleSource.includes(snippet),
            `expected lifecycle composable to include ${snippet}`,
        )
    }

    assert.equal(controlCenterViewSource.includes('watch('), false)
    assert.equal(controlCenterViewSource.includes('onMounted('), false)
    assert.equal(controlCenterViewSource.includes('onUnmounted('), false)
    assert.equal(controlCenterViewSource.includes('onBeforeRouteLeave('), false)
    assert.equal(
        controlCenterViewSource.includes("window.addEventListener('beforeunload'"),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes("window.removeEventListener('beforeunload'"),
        false,
    )
})

test('control center delegates blocker normalization to the shared blocker helper', () => {
    const requiredViewSnippets = [
        "import { normalizeControlCenterBlockers } from '../control-center/blockers'",
        'normalizeBlockers: normalizeControlCenterBlockers,',
    ]
    const requiredBlockerSnippets = [
        'export function resolveControlCenterBlocker(',
        'export function normalizeControlCenterBlockers(',
        'resolveTargetForConfigKey(key)',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredBlockerSnippets) {
        assert.ok(
            blockersSource.includes(snippet),
            `expected blocker helper to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes(
            'function normalizeBackendBlockers(rawBlockers: unknown): ControlCenterBlocker[] {',
        ),
        false,
    )
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
        'function openMonitoringPage(): void {',
        '@activate-live="handleActivateLiveTrading"',
        "@open-config=\"handleModeSelect('setup')\"",
        "@open-monitoring=\"openMonitoringPage\"",
    ]
    const requiredMissionPanelSnippets = [
        'Save changes',
        'Reload latest config',
        'The shared snapshot changed in another browser or tab.',
    ]
    const requiredModeStripSnippets = [
        'Operate',
        'Configure',
        'Utilities',
        "emit('select-mode', 'overview')",
        "emit('select-mode', 'utilities')",
    ]
    const requiredOverviewSnippets = [
        'Recovery priorities',
        'Operator overview',
        'Operator systems',
        'ControlCenterOwnerConfidenceSummary',
        'ControlCenterConfigPreview',
        'ControlCenterMonitoringPreview',
        ':ref="visibleBlockers.length === 0 ? liveActivationRef : undefined"',
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
        controlCenterViewSource.includes('Operator overview'),
        false,
    )
    assert.equal(
        overviewWorkspaceSource.includes('Current operating baseline'),
        false,
    )
    assert.equal(
        controlCenterViewSource.includes('Reload latest config'),
        false,
    )
})

test('owner confidence summary stays compact and evidence-based', () => {
    const requiredSnippets = [
        'Owner confidence',
        'Operating mode',
        'Configuration',
        'Autopilot',
        'Live data',
        'High confidence',
        'Guarded confidence',
        'Low confidence',
    ]

    for (const snippet of requiredSnippets) {
        assert.ok(
            ownerConfidenceSummarySource.includes(snippet),
            `expected owner confidence summary to include ${snippet}`,
        )
    }

    assert.equal(
        ownerConfidenceSummarySource.includes('Reconnects'),
        false,
    )
})

test('control center delegates setup mode presentation to dedicated components', () => {
    const requiredViewSnippets = [
        "import ControlCenterSetupMode from '../components/control-center/ControlCenterSetupMode.vue'",
        '<ControlCenterSetupMode',
        '@select-entry-choice="handleSetupEntryChoice"',
        '@select-setup-style="handleSetupStyleChange"',
        '@select-setup-target="handleSetupTaskSelect"',
        '@setup-shell-click="handleSetupSectionShellClick"',
    ]
    const requiredSetupModeSnippets = [
        "import ControlCenterSetupWorkspace from './ControlCenterSetupWorkspace.vue'",
        "import ConfigGeneralSection from '../config/ConfigGeneralSection.vue'",
        "import ConfigExchangeSection from '../config/ConfigExchangeSection.vue'",
        "import ConfigSignalSection from '../config/ConfigSignalSection.vue'",
        "import ConfigDcaSection from '../config/ConfigDcaSection.vue'",
        "import ConfigMonitoringSection from '../config/ConfigMonitoringSection.vue'",
        '<ControlCenterSetupWorkspace',
        '<template #general>',
        '<template #exchange>',
        '<template #signal>',
        '<template #dca>',
        '<template #monitoring>',
    ]
    const requiredSetupWorkspaceSnippets = [
        "import ControlCenterSetupRestoreFlow from './ControlCenterSetupRestoreFlow.vue'",
        "import ControlCenterSetupStyleSelector from './ControlCenterSetupStyleSelector.vue'",
        "import ControlCenterSetupTaskSection from './ControlCenterSetupTaskSection.vue'",
        '<ControlCenterSetupRestoreFlow',
        '<ControlCenterSetupStyleSelector',
        '<ControlCenterSetupTaskSection',
    ]
    const requiredSetupRestoreFlowSnippets = [
        "import ConfigBackupRestoreControls from '../config/ConfigBackupRestoreControls.vue'",
        'Restore and review',
        '<ConfigBackupRestoreControls',
    ]
    const requiredSetupStyleSnippets = [
        'Choose your setup pace',
        "@click=\"emit('select-entry-choice', 'restore')\"",
    ]
    const requiredSetupTaskSectionSnippets = [
        '<slot />',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
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
    for (const snippet of requiredSetupRestoreFlowSnippets) {
        assert.ok(
            setupRestoreFlowSource.includes(snippet),
            `expected setup restore flow to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupStyleSnippets) {
        assert.ok(
            setupStyleSelectorSource.includes(snippet),
            `expected setup style selector to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupTaskSectionSnippets) {
        assert.ok(
            setupTaskSectionSource.includes(snippet),
            `expected setup task section to include ${snippet}`,
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
    assert.equal(
        controlCenterViewSource.includes('<template #general>'),
        false,
    )
    assert.equal(setupModeSource.includes(': any'), false)
})

test('control center delegates advanced and utilities presentation to dedicated components', () => {
    const requiredViewSnippets = [
        "import ControlCenterAdvancedMode from '../components/control-center/ControlCenterAdvancedMode.vue'",
        "import ControlCenterUtilitiesWorkspace from '../components/control-center/ControlCenterUtilitiesWorkspace.vue'",
        '<ControlCenterAdvancedMode',
        '<ControlCenterUtilitiesWorkspace',
        '@update:backup-include-trade-data="backupIncludeTradeData = $event"',
    ]
    const requiredAdvancedModeSnippets = [
        "from '../../config-editor/types'",
        "import ControlCenterAdvancedWorkspace from './ControlCenterAdvancedWorkspace.vue'",
        "import ConfigGeneralAdvancedSection from '../config/ConfigGeneralAdvancedSection.vue'",
        "import ConfigExchangeAdvancedSection from '../config/ConfigExchangeAdvancedSection.vue'",
        "import ConfigDcaAdvancedSection from '../config/ConfigDcaAdvancedSection.vue'",
        "import ConfigFilterSection from '../config/ConfigFilterSection.vue'",
        "import ConfigAutopilotSection from '../config/ConfigAutopilotSection.vue'",
        "import ConfigIndicatorSection from '../config/ConfigIndicatorSection.vue'",
        '<ControlCenterAdvancedWorkspace',
        '<template #general>',
        '<template #filter>',
        '<template #indicator>',
    ]
    const requiredAdvancedWorkspaceSnippets = [
        'slot :name="section.target"',
        'task-section-header',
    ]
    const requiredUtilitiesWorkspaceSnippets = [
        "import ConfigBackupDownloadControls from '../config/ConfigBackupDownloadControls.vue'",
        "import ConfigBackupRestoreControls from '../config/ConfigBackupRestoreControls.vue'",
        'Backup & Restore',
        'Connectivity test',
        '<ConfigBackupDownloadControls',
        '<ConfigBackupRestoreControls',
        "@click=\"emit('monitoring-test')\"",
        "@update:backup-include-trade-data=\"emit('update:backup-include-trade-data', $event)\"",
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
    for (const snippet of requiredAdvancedModeSnippets) {
        assert.ok(
            advancedModeSource.includes(snippet),
            `expected advanced mode to include ${snippet}`,
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
    assert.equal(
        controlCenterViewSource.includes('<template #indicator>'),
        false,
    )
    assert.equal(advancedModeSource.includes(': any'), false)
})

test('control center delegates derived readiness and route state to a dedicated composable', () => {
    const requiredViewSnippets = [
        "import { useControlCenterDerivedState } from '../composables/useControlCenterDerivedState'",
        '} = useControlCenterDerivedState({',
        'configTrustState,',
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
