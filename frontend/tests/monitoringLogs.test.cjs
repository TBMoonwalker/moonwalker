const test = require('node:test')
const assert = require('node:assert/strict')

const {
    appendMonitoringLogLines,
    filterMonitoringLogLines,
    parseMonitoringLogLevel,
    prependMonitoringLogLines,
} = require('./helpers/loadFrontendModule.cjs').loadFrontendModule(
    '/src/helpers/monitoringLogs.ts',
)

test('parseMonitoringLogLevel extracts structured logger levels', () => {
    assert.equal(
        parseMonitoringLogLevel(
            '2026-03-19 12:00:00 - WARNING - watcher : reconnecting',
        ),
        'WARNING',
    )
    assert.equal(parseMonitoringLogLevel('plain line without formatter'), null)
})

test('filterMonitoringLogLines applies minimum severity thresholds', () => {
    const lines = [
        '2026-03-19 - DEBUG - watcher : verbose detail',
        '2026-03-19 - INFO - watcher : startup complete',
        '2026-03-19 - ERROR - watcher : socket failed',
    ]

    assert.deepEqual(filterMonitoringLogLines(lines, 'all'), lines)
    assert.deepEqual(filterMonitoringLogLines(lines, 'info+'), [
        '2026-03-19 - INFO - watcher : startup complete',
        '2026-03-19 - ERROR - watcher : socket failed',
    ])
    assert.deepEqual(filterMonitoringLogLines(lines, 'critical'), [])
})

test('appendMonitoringLogLines keeps the newest window of lines', () => {
    assert.deepEqual(
        appendMonitoringLogLines(['line 1', 'line 2'], ['line 3', 'line 4'], 3),
        ['line 2', 'line 3', 'line 4'],
    )
})

test('prependMonitoringLogLines keeps the oldest loaded window first', () => {
    assert.deepEqual(
        prependMonitoringLogLines(['line 3', 'line 4'], ['line 1', 'line 2'], 3),
        ['line 1', 'line 2', 'line 3'],
    )
})
