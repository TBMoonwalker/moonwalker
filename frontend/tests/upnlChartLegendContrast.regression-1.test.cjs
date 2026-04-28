const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const upnlChartSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'UpnlChart.vue'),
    'utf8',
)

test('profit overall and funds locked legend keep high-contrast text on the dark chart', () => {
    // Regression: a design cleanup swapped the legend from a light chart token
    // to a dark light-surface token, making both series labels harder to read
    // than the rest of the chart on the dark replay surface.
    assert.ok(
        upnlChartSource.includes("const chartLegendTextColor = '#ECEFEA'"),
        'expected the UPnL chart legend to use the light chart legend token',
    )
    assert.ok(
        upnlChartSource.includes('color: chartLegendTextColor'),
        'expected the legend text style to use the chart legend contrast token',
    )
})
