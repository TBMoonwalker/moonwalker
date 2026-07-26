const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const backtestViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'BacktestView.vue'),
    'utf8',
)

test('backtest icon-only controls expose action-specific names', () => {
    // Regression: ISSUE-004 — refresh and numeric steppers were unnamed buttons.
    // Found by /qa on 2026-07-17.
    // Report: .gstack/qa-reports/qa-report-192-168-6-5-8150-2026-07-17.md
    assert.ok(
        backtestViewSource.includes('aria-label="Refresh symbols"'),
        'expected the symbol refresh action to have an accessible name',
    )
    assert.equal(
        (backtestViewSource.match(/v-accessible-stepper=/g) || []).length,
        6,
        'expected all six numeric inputs to label their paired stepper buttons',
    )
    assert.ok(
        backtestViewSource.includes(
            "setAttribute('aria-label', `Decrease ${normalizedLabel}`)",
        ) &&
            backtestViewSource.includes(
                "setAttribute('aria-label', `Increase ${normalizedLabel}`)",
            ),
        'expected decrement and increment buttons to receive distinct names',
    )
})
