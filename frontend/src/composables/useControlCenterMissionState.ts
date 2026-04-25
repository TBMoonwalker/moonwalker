import { computed, type ComputedRef, type Ref } from 'vue'

import { getTaskPresentation, getTasksForMode } from '../control-center/taskRegistry'
import type {
    ControlCenterConfigTrustKind,
    ControlCenterConfigTrustState,
    ControlCenterReadiness,
    ControlCenterRouteState,
    ControlCenterTransitionIntent,
    ControlCenterViewState,
} from '../control-center/types'

interface UseControlCenterMissionStateOptions {
    changedSectionLabels: ComputedRef<string[]>
    configTrustState: ComputedRef<ControlCenterConfigTrustState>
    isDirty: ComputedRef<boolean>
    readiness: ComputedRef<ControlCenterReadiness>
    routeState: ComputedRef<ControlCenterRouteState>
    showRestoreSetupFlow: ComputedRef<boolean>
    showSetupEntryGate: ComputedRef<boolean>
    transitionIntent: Ref<ControlCenterTransitionIntent | null>
    viewState: ComputedRef<ControlCenterViewState>
}

function isStaleConfigTrustState(kind: ControlCenterConfigTrustKind): boolean {
    return kind === 'stale_but_safe' || kind === 'stale_with_draft_conflict'
}

export function useControlCenterMissionState(
    options: UseControlCenterMissionStateOptions,
) {
    const showModeStrip = computed(() => options.readiness.value.complete)
    const showMissionPanel = computed(
        () =>
            !(
                options.routeState.value.mode === 'setup' &&
                (options.showSetupEntryGate.value ||
                    options.showRestoreSetupFlow.value)
            ),
    )
    const advancedSections = computed(() => {
        const expertDomains = getTasksForMode('advanced').filter((task) =>
            ['filter', 'autopilot', 'indicator'].includes(task.target),
        )

        return [
            {
                target: 'general',
                title: 'Runtime diagnostics',
                summary:
                    'Debug logging and WebSocket watchdog tuning for experienced operators.',
                sectionId: 'control-center-general',
            },
            {
                target: 'exchange',
                title: 'Exchange overrides',
                summary:
                    'Rare hostname overrides for custom exchange domains and edge deployments.',
                sectionId: 'control-center-exchange',
            },
            {
                target: 'dca',
                title: 'Expert safeguards',
                summary:
                    'Advanced take-profit confirmation controls for noisy or thin markets.',
                sectionId: 'control-center-dca',
            },
            {
                target: 'capital',
                title: 'Capital guardrails',
                summary:
                    'Global max fund, safety-order reserve, and buy-admission buffer.',
                sectionId: 'control-center-capital',
            },
            ...expertDomains,
        ]
    })
    const missionPrimaryLabel = computed(() => {
        if (!options.readiness.value.complete) {
            const nextTarget = options.readiness.value.nextTarget
            return nextTarget
                ? `Fix ${getTaskPresentation(nextTarget).title}`
                : 'Continue setup'
        }
        if (options.readiness.value.dryRun) {
            return 'Activate live trading'
        }
        return 'Review overview'
    })
    const missionSummaryTone = computed(() => {
        if (options.viewState.value.kind === 'rescue') {
            return 'error'
        }
        if (options.viewState.value.kind === 'attention_needed') {
            return 'warning'
        }
        if (options.viewState.value.kind === 'post_action_success') {
            return 'success'
        }
        if (options.viewState.value.kind === 'healthy') {
            return 'success'
        }
        return 'info'
    })
    const missionAlertTone = computed(() => {
        if (options.transitionIntent.value) {
            return missionSummaryTone.value
        }
        if (isStaleConfigTrustState(options.configTrustState.value.kind)) {
            return options.configTrustState.value.tone
        }
        if (options.configTrustState.value.kind === 'checking') {
            return options.configTrustState.value.tone
        }
        return missionSummaryTone.value
    })
    const formattedTrustTimestamp = computed(() =>
        options.configTrustState.value.updatedAt
            ? new Date(options.configTrustState.value.updatedAt).toLocaleTimeString()
            : null,
    )
    const dirtySummary = computed(() => {
        if (!options.isDirty.value) {
            return 'No pending draft changes.'
        }
        return `Draft changes: ${options.changedSectionLabels.value.join(', ')}`
    })

    return {
        advancedSections,
        dirtySummary,
        formattedTrustTimestamp,
        isStaleConfigTrustState,
        missionAlertTone,
        missionPrimaryLabel,
        missionSummaryTone,
        showMissionPanel,
        showModeStrip,
    }
}
