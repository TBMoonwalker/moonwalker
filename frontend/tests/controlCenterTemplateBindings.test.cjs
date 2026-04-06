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

test('control center target sections use dynamic element refs', () => {
    // Regression: ISSUE-003 — "Fix this" could not jump because setup targets
    // were bound as literal ref strings instead of dynamic ref callbacks.
    // Found by /qa on 2026-03-20
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-03-20.md
    const targets = [
        'live-activation',
        'general',
        'exchange',
        'signal',
        'dca',
        'monitoring',
        'backup-restore',
    ]

    for (const target of targets) {
        assert.ok(
            controlCenterViewSource.includes(
                `:ref="bindTargetElement('${target}')"`
            ),
            `expected ${target} section to use a dynamic ref binding`,
        )
    }

    assert.equal(
        /(?:^|[\s<])ref="bindTargetElement\('[^']+'\)"/m.test(
            controlCenterViewSource,
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
        '} = useControlCenterSetupFlow({',
        'showSetupEntryGate,',
        'showRestoreSetupFlow,',
        'setupShowsAdvancedFields,',
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
    for (const snippet of requiredSetupFlowSnippets) {
        assert.ok(
            setupFlowSource.includes(snippet),
            `expected setup flow to include ${snippet}`,
        )
    }
})

test('control center keeps guided setup focused and avoids duplicate advanced headings', () => {
    const requiredSnippets = [
        'class="setup-progress-grid"',
        "v-show=\"isSetupTaskExpanded('general')\"",
        ':show-debug="setupShowsAdvancedFields"',
        'ConfigGeneralAdvancedSection',
        'ConfigExchangeAdvancedSection',
        'ConfigDcaAdvancedSection',
        ':card-title="null"',
        'Complete Telegram credentials in Setup first.',
    ]

    for (const snippet of requiredSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }

    assert.equal(
        controlCenterViewSource.includes('Expert tuning'),
        false,
        'expected advanced view to avoid a duplicate intro card heading',
    )
})

test('collapsed setup shells route clicks to their section', () => {
    const requiredSnippets = [
        'function isInteractiveTarget(',
        'function handleSetupSectionShellClick(',
        "target.closest('button, a, input, select, textarea, label, [role=\"button\"]')",
        `@click="handleSetupSectionShellClick('general', $event)"`,
        `@click="handleSetupSectionShellClick('exchange', $event)"`,
        `@click="handleSetupSectionShellClick('signal', $event)"`,
        `@click="handleSetupSectionShellClick('dca', $event)"`,
        `@click="handleSetupSectionShellClick('monitoring', $event)"`,
    ]

    for (const snippet of requiredSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
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
