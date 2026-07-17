const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const tradesViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'TradesView.vue'),
    'utf8',
)

test('dashboard tab groups implement the ARIA tabs pattern', () => {
    // Regression: ISSUE-003 — chart and trade tabs were pointer-only divs.
    // Found by /qa on 2026-07-17.
    // Report: .gstack/qa-reports/qa-report-192-168-6-5-8150-2026-07-17.md
    assert.equal(
        (tradesViewSource.match(/:tab-props="get(?:Profit|Trade)TabProps/g) || [])
            .length,
        8,
        'expected every chart and trade tab to receive semantic tab props',
    )
    assert.equal(
        (tradesViewSource.match(/role="tabpanel"/g) || []).length,
        8,
        'expected every tab content pane to expose the tabpanel role',
    )
    for (const token of [
        "role: 'tab'",
        "'aria-selected': String(selected)",
        "'aria-controls': `${group}-panel-${name}`",
        "setAttribute('role', 'tablist')",
    ]) {
        assert.ok(
            tradesViewSource.includes(token),
            `expected dashboard tab semantics to include ${token}`,
        )
    }
})

test('dashboard tabs support standard keyboard navigation', () => {
    for (const key of ['ArrowRight', 'ArrowLeft', 'Home', 'End', 'Enter']) {
        assert.ok(
            tradesViewSource.includes(`event.key === '${key}'`),
            `expected tab keyboard handling for ${key}`,
        )
    }
    assert.ok(
        tradesViewSource.includes("event.key === ' '") &&
            tradesViewSource.includes('nextTab.click()') &&
            tradesViewSource.includes('nextTab.focus()'),
        'expected Space activation and roving focus between tabs',
    )
})
