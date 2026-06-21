const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const statisticsSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'StatisticsView.vue'),
    'utf8',
)
const analyticsStoreSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'stores', 'analytics.ts'),
    'utf8',
)

test('statistics page renders the AI Trust Cockpit shadow-observation section', () => {
    assert.match(statisticsSource, /AI Trust Cockpit/)
    assert.match(statisticsSource, /AI observed is disabled/)
    assert.match(statisticsSource, /AI would have warned/)
    assert.match(statisticsSource, /warning entries are blocked/)
    assert.match(statisticsSource, /Blocked/)
    assert.match(statisticsSource, /Preflight/)
    assert.match(statisticsSource, /Recent Predictions/)
    assert.match(statisticsSource, /Bad-entry Review/)
    assert.match(statisticsSource, /aiTrust\?\.status === 'missing_model'/)
})

test('AI Trust Cockpit keeps trading-control language out of the section copy', () => {
    const section = statisticsSource.slice(
        statisticsSource.indexOf('<!-- AI Trust Cockpit -->'),
        statisticsSource.indexOf('<!-- Analytics Tabs -->'),
    )

    assert.doesNotMatch(section, /\bAI says\b/i)
    assert.doesNotMatch(section, /\bAI recommends\b/i)
    assert.doesNotMatch(section, /\bAI will\b/i)
    assert.doesNotMatch(section, /\bbuy\b/i)
    assert.doesNotMatch(section, /\bsell\b/i)
})

test('analytics store exposes AI trust states and calibration rows', () => {
    assert.match(analyticsStoreSource, /ai_trust:/)
    assert.match(analyticsStoreSource, /enforce_warnings: boolean/)
    assert.match(analyticsStoreSource, /source_event: string/)
    assert.match(analyticsStoreSource, /status: 'disabled' \| 'missing_model' \| 'ready'/)
    assert.match(analyticsStoreSource, /recent_predictions: AiTrustPrediction\[\]/)
    assert.match(analyticsStoreSource, /bad_entry_review: AiTrustPrediction\[\]/)
    assert.match(analyticsStoreSource, /provider_status_counts: Record<string, number>/)
})

test('AI Trust Cockpit tables use the shared statistics pagination rhythm', () => {
    assert.match(statisticsSource, /const recentPredictionsPagination = reactive<PaginationProps>/)
    assert.match(statisticsSource, /const badEntryReviewPagination = reactive<PaginationProps>/)
    assert.match(statisticsSource, /:pagination="recentPredictionsPagination"/)
    assert.match(statisticsSource, /:pagination="badEntryReviewPagination"/)
    assert.match(statisticsSource, /@update:page="handleRecentPredictionsPageChange"/)
    assert.match(statisticsSource, /@update:page="handleBadEntryReviewPageChange"/)

    const aiTrustSection = statisticsSource.slice(
        statisticsSource.indexOf('<!-- AI Trust Cockpit -->'),
        statisticsSource.indexOf('<!-- Analytics Tabs -->'),
    )

    assert.doesNotMatch(aiTrustSection, /:pagination="false"/)
})
