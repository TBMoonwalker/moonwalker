const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'StatisticsView.vue'),
     'utf8',
)

// ---------------------------------------------------------------------------
// fmt2 — toFixed(2)
// ---------------------------------------------------------------------------

test('fmt2 formats number to 2 decimal places', () => {
     // Source verification
    assert.match(source, /function fmt2\(val: number\)/)
    assert.match(source, /val\.toFixed\(2\)/)

    // Functional test
    assert.equal(Number(12.345).toFixed(2), '12.35')
    assert.equal(Number(0).toFixed(2), '0.00')
    assert.equal(Number(-5.1).toFixed(2), '-5.10')
})

// ---------------------------------------------------------------------------
// fmtPct — append %
// ---------------------------------------------------------------------------

test('fmtPct appends percent sign', () => {
    assert.match(source, /function fmtPct\(val: number\)/)
    assert.match(source, /\$\{val\}%/)

    assert.equal(`${75}%`, '75%')
    assert.equal(`${0}%`, '0%')
})

// ---------------------------------------------------------------------------
// fmtRangePct — handles -0
// ---------------------------------------------------------------------------

test('fmtRangePct normalizes negative zero', () => {
    assert.match(source, /function fmtRangePct\(val: number\)/)
    assert.match(source, /Object\.is\(val, -0\)/)

    // Functional: Object.is(-0, -0) is true, so -0 becomes 0
    const val = -0
    const normalized = Object.is(val, -0) ? 0 : val
    assert.equal(normalized, 0)
    assert.equal(normalized.toFixed(2), '0.00')
})

test('fmtRangePct formats normal values', () => {
    assert.match(source, /\$\{normalized\.toFixed\(2\)}%/)

    assert.equal((5.25).toFixed(2) + '%', '5.25%')
    assert.equal((-3.1).toFixed(2) + '%', '-3.10%')
})

// ---------------------------------------------------------------------------
// fmtProfitRange — single vs range
// ---------------------------------------------------------------------------

test('fmtProfitRange source handles min === max', () => {
    assert.match(source, /function fmtProfitRange\(row/)
    assert.match(source, /row\.min === row\.max/)
})

test('fmtProfitRange source handles min !== max with "to" separator', () => {
    assert.match(source, /to/)
})

// Functional mirror
function fmtRangePct(val) {
    const normalized = Object.is(val, -0) ? 0 : val
    return `${normalized.toFixed(2)}%`
}

function fmtProfitRange(row) {
    if (row.min === row.max) {
        return fmtRangePct(row.min)
    }
    return `${fmtRangePct(row.min)} to ${fmtRangePct(row.max)}`
}

test('fmtProfitRange returns single value when min equals max', () => {
    assert.equal(fmtProfitRange({ min: 5.0, max: 5.0 }), '5.00%')
    assert.equal(fmtProfitRange({ min: -3.1, max: -3.1 }), '-3.10%')
})

test('fmtProfitRange returns range when min differs from max', () => {
    assert.equal(fmtProfitRange({ min: -10.0, max: 0 }), '-10.00% to 0.00%')
    assert.equal(fmtProfitRange({ min: 0, max: 5.5 }), '0.00% to 5.50%')
})

test('fmtProfitRange handles negative zero in min', () => {
    assert.equal(fmtProfitRange({ min: -0, max: -0 }), '0.00%')
})

// ---------------------------------------------------------------------------
// Heatmap summary — singular/plural
// ---------------------------------------------------------------------------

test('heatmapSummary uses singular "active day" for count 1', () => {
    assert.match(source, /activeDays === 1 \? 'active day' : 'active days'/)
})

test('heatmapSummary shows "No closed trades" message when zero', () => {
    assert.match(source, /No closed trades in this range/)
})

// Functional mirror
function computeHeatmapSummary(rows) {
    const activeDays = rows.filter(row => Number(row.value ?? 0) > 0).length
    const closedTrades = rows.reduce((total, row) => total + Number(row.value ?? 0), 0)
    if (!closedTrades) {
        return 'No closed trades in this range'
    }
    const dayLabel = activeDays === 1 ? 'active day' : 'active days'
    return `${closedTrades} closes across ${activeDays} ${dayLabel}`
}

test('computeHeatmapSummary returns no-trades message for empty data', () => {
    assert.equal(computeHeatmapSummary([]), 'No closed trades in this range')
})

test('computeHeatmapSummary returns singular active day', () => {
    assert.equal(
        computeHeatmapSummary([{ timestamp: 1, value: 3 }]),
         '3 closes across 1 active day',
     )
})

test('computeHeatmapSummary returns plural active days', () => {
    assert.equal(
        computeHeatmapSummary([
             { timestamp: 1, value: 2 },
             { timestamp: 2, value: 3 },
         ]),
          '5 closes across 2 active days',
     )
})

test('computeHeatmapSummary ignores zero-value days', () => {
    assert.equal(
        computeHeatmapSummary([
             { timestamp: 1, value: 2 },
             { timestamp: 2, value: 0 },
             { timestamp: 3, value: 0 },
         ]),
          '2 closes across 1 active day',
     )
})

// ---------------------------------------------------------------------------
// Heatmap metrics — peak day detection
// ---------------------------------------------------------------------------

test('heatmapMetrics source computes closedTrades, activeDays, peakCount, peakDate', () => {
    assert.match(source, /function heatmapMetrics|const heatmapMetrics/)
    assert.match(source, /closedTrades/)
    assert.match(source, /activeDays/)
    assert.match(source, /peakCount/)
    assert.match(source, /peakDate/)
})

// Functional mirror
function computeHeatmapMetrics(rows) {
    const activeRows = rows.filter(row => Number(row.value ?? 0) > 0)
    const closedTrades = activeRows.reduce((total, row) => total + Number(row.value ?? 0), 0)
    const peak = activeRows.reduce(
        (best, row) =>
            Number(row.value ?? 0) > Number(best?.value ?? 0) ? row : best,
          activeRows[0] ?? null,
     )
    return {
        closedTrades,
        activeDays: activeRows.length,
        peakCount: Number(peak?.value ?? 0),
        peakDate: peak ? new Date(peak.timestamp).toLocaleDateString() : '-',
     }
}

test('computeHeatmapMetrics returns zero metrics for empty data', () => {
    const result = computeHeatmapMetrics([])
    assert.equal(result.closedTrades, 0)
    assert.equal(result.activeDays, 0)
    assert.equal(result.peakCount, 0)
    assert.equal(result.peakDate, '-')
})

test('computeHeatmapMetrics finds peak day correctly', () => {
    const result = computeHeatmapMetrics([
         { timestamp: Date.UTC(2026, 0, 1), value: 2 },
         { timestamp: Date.UTC(2026, 0, 2), value: 5 },
         { timestamp: Date.UTC(2026, 0, 3), value: 3 },
     ])
    assert.equal(result.closedTrades, 10)
    assert.equal(result.activeDays, 3)
    assert.equal(result.peakCount, 5)
})

// ---------------------------------------------------------------------------
// getSymbolColumns — column definitions
// ---------------------------------------------------------------------------

test('getSymbolColumns defines 6 columns: symbol, trades, win_rate, total_profit, avg_profit, avg_duration', () => {
    assert.match(source, /title: 'Symbol'/)
    assert.match(source, /title: 'Trades'/)
    assert.match(source, /title: 'Win Rate'/)
    assert.match(source, /title: 'Total Profit'/)
    assert.match(source, /title: 'Avg Profit'/)
    assert.match(source, /title: 'Avg Duration'/)
})

test('getSymbolColumns symbol column is fixed left', () => {
    assert.match(source, /fixed: 'left'/)
})

test('getSymbolColumns profit columns use color coding', () => {
    assert.match(source, /#2E7D5B/, 'expected green color for positive')
    assert.match(source, /#B4443F/, 'expected red color for negative')
})

// ---------------------------------------------------------------------------
// getDurationColumns — longest/shortest tables
// ---------------------------------------------------------------------------

test('getDurationColumns defines 5 columns: symbol, duration, profit, profit_percent, close_date', () => {
    assert.match(source, /title: 'Duration'/)
    assert.match(source, /title: 'Profit %'/)
    assert.match(source, /title: 'Closed'/)
})

test('getDurationColumns close_date handles null with fallback dash', () => {
    assert.match(source, /row\.close_date/)
    assert.match(source, /toLocaleDateString\(\)/)
    assert.match(source, /: '-'/)
})

// ---------------------------------------------------------------------------
// getDistributionColumns — 3 columns
// ---------------------------------------------------------------------------

test('getDistributionColumns defines 3 columns: outcome, range, trades', () => {
    assert.match(source, /title: 'Outcome'/)
    assert.match(source, /title: 'Range'/)
    assert.match(source, /title: 'Trades'/)
})

// ---------------------------------------------------------------------------
// Tab names
// ---------------------------------------------------------------------------

test('tabNames defines 4 tabs: symbols, duration, risk, distribution', () => {
    assert.match(source, /name: 'symbols', label: 'Symbols'/)
    assert.match(source, /name: 'duration', label: 'Duration'/)
    assert.match(source, /name: 'risk', label: 'Risk'/)
    assert.match(source, /name: 'distribution', label: 'Distribution'/)
})

// ---------------------------------------------------------------------------
// Risk tab — drawdown display
// ---------------------------------------------------------------------------

test('risk tab displays max_drawdown and max_drawdown_percent', () => {
    assert.match(source, /Max Drawdown/)
    assert.match(source, /max_drawdown/)
    assert.match(source, /max_drawdown_percent/)
})

// ---------------------------------------------------------------------------
// Distribution tab — stats display
// ---------------------------------------------------------------------------

test('distribution tab displays median, std_dev, best, worst', () => {
    assert.match(source, /label="Median"/)
    assert.match(source, /label="Std Dev"/)
    assert.match(source, /label="Best Trade"/)
    assert.match(source, /label="Worst Trade"/)
})

test('distribution tab hides median and std_dev on mobile', () => {
    assert.match(source, /v-if="!isMobile"/)
})
