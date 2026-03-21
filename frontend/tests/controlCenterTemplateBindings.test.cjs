const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
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
    const requiredSnippets = [
        "const showSetupEntryGate = computed(",
        "const showRestoreSetupFlow = computed(",
        "const setupShowsAdvancedFields = computed(",
        "setupStyle.value === 'full'",
        'How do you want to begin?',
        'Restore existing installation',
        'Start a new setup',
    ]

    for (const snippet of requiredSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
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
