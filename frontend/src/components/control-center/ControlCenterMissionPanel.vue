<script setup lang="ts">
import type {
    ControlCenterConfigTrustState,
    ControlCenterReadiness,
    ControlCenterTransitionIntent,
    ControlCenterViewState,
} from '../../control-center/types'

defineProps<{
    activationLoading: boolean
    configTrustState: ControlCenterConfigTrustState
    dirtySummary: string
    formattedTrustTimestamp: string | null
    isDirty: boolean
    isStaleConfigTrustState: (kind: ControlCenterConfigTrustState['kind']) => boolean
    isSubmitDisabled: boolean
    missionAlertTone: 'info' | 'success' | 'warning'
    missionPrimaryLabel: string
    missionSummaryTone: 'info' | 'success' | 'warning'
    readiness: ControlCenterReadiness
    saveState: string
    transitionIntent: ControlCenterTransitionIntent | null
    viewState: ControlCenterViewState
}>()

defineEmits<{
    'mission-primary': []
    'reload-latest': []
    save: []
}>()
</script>

<template>
    <n-card class="mission-panel" content-style="padding: 22px 24px;">
        <n-flex vertical :size="18">
            <n-flex justify="space-between" align="center" :wrap="true">
                <n-flex vertical :size="6">
                    <n-text depth="3" class="control-center-kicker">
                        Control Center
                    </n-text>
                    <div class="mission-heading-group">
                        <n-tag class="mission-status-tag" :type="missionSummaryTone">
                            {{ viewState.badge }}
                        </n-tag>
                        <h1 class="mission-title">
                            {{ viewState.title }}
                        </h1>
                    </div>
                    <n-text depth="3" class="mission-summary">
                        {{ viewState.summary }}
                    </n-text>
                </n-flex>

                <n-flex align="center" :wrap="true" :size="[10, 10]">
                    <n-button
                        v-if="isDirty"
                        type="primary"
                        secondary
                        :loading="saveState === 'saving'"
                        :disabled="isSubmitDisabled"
                        @click="$emit('save')"
                    >
                        Save changes
                    </n-button>
                    <n-button
                        type="primary"
                        strong
                        :loading="activationLoading"
                        :disabled="
                            viewState.kind === 'rescue' ||
                            (readiness.complete && readiness.dryRun
                                ? activationLoading
                                : false)
                        "
                        @click="$emit('mission-primary')"
                    >
                        {{ missionPrimaryLabel }}
                    </n-button>
                </n-flex>
            </n-flex>

            <n-alert
                :type="missionAlertTone"
                :title="dirtySummary"
                role="status"
                aria-live="polite"
            >
                <template v-if="transitionIntent">
                    {{ transitionIntent.message }}
                </template>
                <template v-else-if="configTrustState.kind === 'checking'">
                    {{ configTrustState.summary }}
                </template>
                <template v-else-if="isStaleConfigTrustState(configTrustState.kind)">
                    {{ configTrustState.summary }}
                    <span v-if="formattedTrustTimestamp">
                        Latest change detected at {{ formattedTrustTimestamp }}.
                    </span>
                </template>
                <template v-else>
                    {{
                        readiness.complete
                            ? readiness.dryRun
                                ? 'Moonwalker is configured for safe dry-run operation.'
                                : 'Moonwalker is operating live on the configured exchange.'
                            : `${readiness.blockers.length} setup item(s) still need attention.`
                    }}
                </template>
            </n-alert>

            <n-flex
                v-if="isStaleConfigTrustState(configTrustState.kind)"
                class="stale-actions"
                align="center"
                :wrap="true"
                :size="[10, 10]"
            >
                <n-button secondary type="warning" @click="$emit('reload-latest')">
                    Reload latest config
                </n-button>
                <n-text depth="3">
                    The shared snapshot changed in another browser or tab.
                </n-text>
            </n-flex>
        </n-flex>
    </n-card>
</template>

<style scoped>
.control-center-kicker {
    font-size: 0.82rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--mw-color-text-muted);
    font-family: var(--mw-font-body);
    font-weight: 600;
}

.mission-panel {
    border: 1px solid rgba(29, 92, 73, 0.26);
    background: var(--mw-surface-mission);
    box-shadow: var(--mw-shadow-card);
    color: var(--mw-color-text-primary);
}

.mission-heading-group {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
}

.mission-heading-group :deep(.mission-status-tag) {
    border-radius: 999px;
    padding: 6px 12px;
}

.mission-heading-group :deep(.mission-status-tag .n-tag__content) {
    font-size: 0.95rem;
    font-weight: 600;
    line-height: 1;
}

.mission-title {
    font-family: var(--mw-font-display);
    font-size: clamp(1.5rem, 3vw, 2.25rem);
    line-height: 1.1;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.mission-summary {
    max-width: 72ch;
}

.mission-panel :deep(.n-button--primary-type .n-button__content) {
    color: #f7f8f6;
    font-weight: 700;
    letter-spacing: 0.01em;
}

@media (max-width: 768px) {
    .mission-panel :deep(.n-alert) {
        padding-right: 0;
    }
}
</style>
