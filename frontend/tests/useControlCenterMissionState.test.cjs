const assert = require('node:assert/strict')
const test = require('node:test')

const { computed, ref } = require('vue')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterMissionState } = loadFrontendModule(
    'src/composables/useControlCenterMissionState.ts',
)

function createMissionStateHarness(overrides = {}) {
    const transitionIntent = ref(null)

    const options = {
        changedSectionLabels: computed(() => ['Exchange connection']),
        configTrustState: computed(() => ({
            kind: 'trusted',
            summary: 'Configuration is current.',
            tone: 'success',
            updatedAt: null,
        })),
        isDirty: computed(() => true),
        readiness: computed(() => ({
            complete: false,
            firstRun: false,
            attentionNeeded: true,
            blockers: [],
            nextMode: 'setup',
            nextTarget: 'signal',
            dryRun: true,
            configuredEssentials: 4,
        })),
        routeState: computed(() => ({
            mode: 'setup',
            target: 'signal',
        })),
        showRestoreSetupFlow: computed(() => false),
        showSetupEntryGate: computed(() => false),
        transitionIntent,
        viewState: computed(() => ({
            kind: 'attention_needed',
            badge: 'Needs attention',
            title: 'Keep setup moving',
            summary: 'Resolve the next blocker.',
            defaultMode: 'setup',
        })),
        ...overrides,
    }

    return {
        missionState: useControlCenterMissionState(options),
        transitionIntent,
    }
}

test('mission state derives labels and summaries for incomplete setup', () => {
    const harness = createMissionStateHarness()

    assert.equal(harness.missionState.showModeStrip.value, false)
    assert.equal(harness.missionState.showMissionPanel.value, true)
    assert.equal(harness.missionState.missionPrimaryLabel.value, 'Fix Signal source')
    assert.equal(harness.missionState.missionSummaryTone.value, 'warning')
    assert.equal(harness.missionState.missionAlertTone.value, 'warning')
    assert.equal(
        harness.missionState.dirtySummary.value,
        'Draft changes: Exchange connection',
    )
    assert.equal(harness.missionState.advancedSections.value[0].title, 'Runtime diagnostics')
})

test('mission state surfaces stale trust timestamps and matching alert tone', () => {
    const harness = createMissionStateHarness({
        configTrustState: computed(() => ({
            kind: 'stale_but_safe',
            summary: 'A newer snapshot is available.',
            tone: 'warning',
            updatedAt: '2026-04-06T09:00:00Z',
        })),
        isDirty: computed(() => false),
        readiness: computed(() => ({
            complete: true,
            firstRun: false,
            attentionNeeded: false,
            blockers: [],
            nextMode: 'overview',
            nextTarget: 'live-activation',
            dryRun: true,
            configuredEssentials: 8,
        })),
        routeState: computed(() => ({
            mode: 'overview',
            target: 'live-activation',
        })),
        viewState: computed(() => ({
            kind: 'healthy',
            badge: 'Healthy',
            title: 'Ready to go',
            summary: 'Everything is configured.',
            defaultMode: 'overview',
        })),
    })

    assert.equal(harness.missionState.isStaleConfigTrustState('stale_but_safe'), true)
    assert.equal(harness.missionState.missionAlertTone.value, 'warning')
    assert.equal(typeof harness.missionState.formattedTrustTimestamp.value, 'string')
    assert.equal(harness.missionState.dirtySummary.value, 'No pending draft changes.')
})

test('mission state hides the mission panel behind first-run intent gating', () => {
    const harness = createMissionStateHarness({
        showSetupEntryGate: computed(() => true),
    })

    assert.equal(harness.missionState.showMissionPanel.value, false)
})

test('mission state uses the mission tone while a transition is active', () => {
    const harness = createMissionStateHarness({
        readiness: computed(() => ({
            complete: true,
            firstRun: false,
            attentionNeeded: false,
            blockers: [],
            nextMode: 'overview',
            nextTarget: 'live-activation',
            dryRun: false,
            configuredEssentials: 8,
        })),
        routeState: computed(() => ({
            mode: 'overview',
            target: 'live-activation',
        })),
        viewState: computed(() => ({
            kind: 'post_action_success',
            badge: 'Updated',
            title: 'Saved',
            summary: 'Changes are live.',
            defaultMode: 'overview',
        })),
    })
    harness.transitionIntent.value = {
        kind: 'save',
        status: 'success',
        message: 'Saved.',
        at: 1,
        mode: 'overview',
    }

    assert.equal(harness.missionState.missionSummaryTone.value, 'success')
    assert.equal(harness.missionState.missionAlertTone.value, 'success')
    assert.equal(harness.missionState.missionPrimaryLabel.value, 'Review overview')
})
