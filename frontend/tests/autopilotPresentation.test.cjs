const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const {
    formatAutopilotEvent,
    formatAutopilotFeaturedInsight,
    formatAutopilotMemoryHint,
    formatAutopilotStatusBody,
    formatAutopilotStatusTitle,
} = loadFrontendModule('src/autopilot/presentation.ts')

test('formatAutopilotFeaturedInsight renders restrained favored copy', () => {
    const copy = formatAutopilotFeaturedInsight({
        symbol: 'BTC/USDT',
        trust_direction: 'favored',
        primary_reason_code: 'quick_profitable_closes',
        primary_reason_value: 6,
    })

    assert.equal(copy, 'Favored BTC/USDT after 6 quick profitable closes.')
})

test('formatAutopilotEvent renders stale fallback copy', () => {
    const copy = formatAutopilotEvent({
        event_type: 'memory_stale',
        tone: 'warning',
        symbol: null,
        reason_code: 'refresh_failed',
        reason_value: null,
        trust_score: null,
        created_at: null,
    })

    assert.equal(copy, 'Baseline mode active while memory refreshes.')
})

test('formatAutopilotStatusTitle distinguishes stale and learning states', () => {
    assert.equal(
        formatAutopilotStatusTitle({
            stale: true,
            status: 'fresh',
        }),
        'Autopilot memory is stale',
    )
    assert.equal(
        formatAutopilotStatusTitle({
            stale: false,
            status: 'warming_up',
        }),
        'Autopilot is still learning',
    )
    assert.equal(
        formatAutopilotStatusTitle({
            stale: false,
            status: 'fresh',
            enabled: false,
        }),
        'Autopilot is off',
    )
})

test('formatAutopilotStatusBody explains disabled ready state plainly', () => {
    assert.equal(
        formatAutopilotStatusBody({
            stale: false,
            status: 'fresh',
            enabled: false,
        }),
        'Moonwalker has enough history to rank symbols, but it is not applying symbol trust until Autopilot is enabled.',
    )
})

test('formatAutopilotMemoryHint summarizes warm-up progress', () => {
    const hint = formatAutopilotMemoryHint({
        currentCloses: 14,
        requiredCloses: 20,
        stale: false,
        staleReason: null,
        status: 'warming_up',
    })

    assert.equal(hint, 'Memory learning (14/20 closes)')
})
