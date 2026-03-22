const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
    'utf8',
)
const setupEntryHistorySource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'control-center', 'setupEntryHistory.ts'),
    'utf8',
)

test('first-run setup entry choices create browser history state', () => {
    // Regression: ISSUE-007 — browser Back from the first-run setup entry
    // choices exited to about:blank because the selection only changed local
    // state and did not create a distinct browser-history entry.
    // Found by /qa on 2026-03-22
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-03-22.md
    const requiredViewSnippets = [
        'buildSetupEntryChoiceHistoryState,',
        'getSetupEntryChoiceFromHistoryState,',
        'window.history.pushState(',
        'window.history.replaceState(',
        'function handleSetupEntryChoicePopState(): void {',
        "window.addEventListener('popstate', handleSetupEntryChoicePopState)",
        "window.removeEventListener('popstate', handleSetupEntryChoicePopState)",
    ]
    const requiredHelperSnippets = [
        "export const CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY =",
        'export function getSetupEntryChoiceFromHistoryState(',
        'export function buildSetupEntryChoiceHistoryState(',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected control center entry history wiring to include ${snippet}`,
        )
    }
    for (const snippet of requiredHelperSnippets) {
        assert.ok(
            setupEntryHistorySource.includes(snippet),
            `expected setup entry history helper to include ${snippet}`,
        )
    }
})
