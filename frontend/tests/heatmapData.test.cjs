const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { normalizeTradeHeatmapData } = loadFrontendModule('src/helpers/heatmap.ts')

function utcDate(year, month, day) {
    return Date.UTC(year, month - 1, day)
}

test('trade heatmap pads sparse data to full first and last months', () => {
    const result = normalizeTradeHeatmapData([
        { timestamp: utcDate(2026, 2, 23), value: 2 },
        { timestamp: utcDate(2026, 4, 15), value: 3 },
        { timestamp: utcDate(2026, 5, 4), value: 1 },
    ])

    assert.equal(result[0].timestamp, utcDate(2026, 2, 1))
    assert.equal(result[0].value, 0)
    assert.equal(result.at(-1).timestamp, utcDate(2026, 5, 31))
    assert.equal(result.at(-1).value, 0)
    assert.deepEqual(
        result.filter((entry) => entry.value > 0),
        [
            { timestamp: utcDate(2026, 2, 23), value: 2 },
            { timestamp: utcDate(2026, 4, 15), value: 3 },
            { timestamp: utcDate(2026, 5, 4), value: 1 },
        ],
    )
})

test('trade heatmap preserves real trades on month boundary anchors', () => {
    const result = normalizeTradeHeatmapData([
        { timestamp: utcDate(2026, 2, 1), value: 2 },
        { timestamp: utcDate(2026, 2, 1), value: 3 },
        { timestamp: utcDate(2026, 2, 28), value: 1 },
    ])

    assert.deepEqual(result, [
        { timestamp: utcDate(2026, 2, 1), value: 5 },
        { timestamp: utcDate(2026, 2, 28), value: 1 },
    ])
})
