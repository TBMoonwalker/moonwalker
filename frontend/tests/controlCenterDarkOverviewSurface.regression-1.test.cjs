const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

// Regression: ISSUE-001 — Control Center overview shells stayed on light surfaces in dark mode
// Found by /qa on 2026-04-28
// Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-04-28.md

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

const ownerConfidenceSource = fs.readFileSync(
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

test('shared overview workspace uses theme-aware shell surfaces', () => {
    assert.match(overviewWorkspaceSource, /background:\s*var\(--mw-surface-card-muted\)/)
    assert.match(overviewWorkspaceSource, /border:\s*1px solid var\(--mw-color-border-strong\)/)
    assert.doesNotMatch(overviewWorkspaceSource, /background:\s*rgba\(247,\s*248,\s*246,\s*0\.58\)/)
})

test('owner confidence summary uses theme-aware raised surface', () => {
    assert.match(ownerConfidenceSource, /background:\s*var\(--mw-surface-card\)/)
    assert.match(ownerConfidenceSource, /border:\s*1px solid var\(--mw-color-border-strong\)/)
    assert.doesNotMatch(ownerConfidenceSource, /background:\s*rgba\(247,\s*248,\s*246,\s*0\.74\)/)
})
