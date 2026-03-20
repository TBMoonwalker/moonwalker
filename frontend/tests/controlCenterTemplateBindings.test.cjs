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

test('control center keeps setup essentials-only and reserves expert fields for advanced mode', () => {
    // Regression: ISSUE-004 — Setup and Advanced looked nearly identical because
    // Setup still exposed the shared advanced toggle and advanced-only fields.
    // Found by /qa on 2026-03-20
    const requiredSnippets = [
        ':show-advanced-general="setupShowsAdvancedFields"',
        ':show-advanced-toggle="false"',
        "const setupShowsAdvancedFields = computed(() => false)",
    ]

    for (const snippet of requiredSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center to include ${snippet}`,
        )
    }
})
