const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const upnlChartSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'UpnlChart.vue'),
    'utf8',
)

test('profit overall and funds locked legend follow the active theme text token', () => {
    // Both light and dark chart surfaces need their matching contrast token.
    assert.ok(
        upnlChartSource.includes("const chartLegendTextColor = colors['--mw-color-text-secondary']"),
        'expected the UPnL chart legend to use the active theme text token',
    )
    assert.ok(
        upnlChartSource.includes('color: chartLegendTextColor'),
        'expected the legend text style to use the chart legend contrast token',
    )
})
