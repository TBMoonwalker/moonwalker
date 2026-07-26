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
    <n-card class="mission-panel dashboard-panel" content-style="padding: 14px 16px;">
        <n-flex vertical :size="10">
            <n-flex
                justify="space-between"
                align="center"
                :wrap="true"
                class="mission-header-row"
            >
                <n-flex vertical :size="6" class="mission-copy">
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

                <n-flex
                    align="center"
                    :wrap="true"
                    :size="[10, 10]"
                    class="mission-actions"
                >
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
                        v-if="!(readiness.complete && readiness.dryRun)"
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
    border-color: rgba(29, 92, 73, 0.14);
    background: rgba(29, 92, 73, 0.05);
}

.mission-heading-group {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    min-width: 0;
}

.mission-heading-group :deep(.mission-status-tag) {
    border-radius: 999px;
    padding: 4px 10px;
}

.mission-heading-group :deep(.mission-status-tag.n-tag--success-type) {
    background: var(--mw-color-primary);
    border-color: var(--mw-color-primary);
    box-shadow: inset 0 0 0 1px rgba(24, 65, 58, 0.08);
}

.mission-heading-group
    :deep(.mission-status-tag.n-tag--success-type .n-tag__content) {
    color: #f7f8f6;
}

.mission-heading-group :deep(.mission-status-tag .n-tag__content) {
    font-size: 0.86rem;
    font-weight: 500;
    line-height: 1;
}

.mission-header-row {
    width: 100%;
}

.mission-copy {
    flex: 1 1 42rem;
    min-width: 0;
}

.mission-actions {
    flex: 0 0 auto;
    justify-content: flex-end;
}

.mission-title {
    margin: 0;
    font-family: var(--mw-font-display);
    font-size: 1.35rem;
    line-height: 1.2;
    font-weight: 450;
    letter-spacing: 0;
}

.mission-summary {
    display: block;
    min-width: 0;
    max-width: 72ch;
    font-size: 0.95rem;
    line-height: 1.45;
}

.mission-panel :deep(.n-card__content) {
    padding: 14px 16px !important;
}

.mission-panel :deep(.n-alert) {
    padding: 10px 12px;
    border-radius: var(--mw-radius-sm);
}

.mission-panel :deep(.n-alert-body__title) {
    margin-bottom: 2px;
    font-size: 0.95rem;
    font-weight: 550;
}

.mission-panel :deep(.n-alert-body__content) {
    font-size: 0.9rem;
    line-height: 1.35;
}

.mission-panel :deep(.n-button--primary-type .n-button__content) {
    color: #f7f8f6;
    font-weight: 500;
    letter-spacing: 0.01em;
}

@media (max-width: 768px) {
    .mission-summary {
        white-space: normal;
    }

    .mission-panel :deep(.n-alert) {
        padding-right: 0;
    }
}
</style>
