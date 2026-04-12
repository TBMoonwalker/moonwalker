<script setup lang="ts">
import { computed } from 'vue'

import type {
    ControlCenterConfigTrustState,
    ControlCenterReadiness,
} from '../../control-center/types'

const props = defineProps<{
    activationLoading: boolean
    configTrustState: ControlCenterConfigTrustState
    formattedTrustTimestamp: string | null
    readiness: ControlCenterReadiness
}>()

const emit = defineEmits<{
    'activate-live': []
    'open-config': []
}>()

const isStale = computed(
    () =>
        props.configTrustState.kind === 'stale_but_safe' ||
        props.configTrustState.kind === 'stale_with_draft_conflict',
)

const statusTitle = computed(() => {
    if (props.configTrustState.kind === 'checking') {
        return 'Configuration is being verified'
    }
    if (props.configTrustState.kind === 'stale_with_draft_conflict') {
        return 'Configuration needs a reload decision'
    }
    if (props.configTrustState.kind === 'stale_but_safe') {
        return 'Configuration has a newer saved version'
    }
    return 'Configuration is current'
})

const statusBody = computed(() => {
    if (props.configTrustState.kind === 'checking') {
        return props.configTrustState.summary
    }
    if (isStale.value) {
        return props.configTrustState.summary
    }
    if (props.readiness.dryRun) {
        return 'Moonwalker is using the latest saved configuration in safe dry run.'
    }
    return 'Moonwalker is using the latest saved configuration for live trading.'
})

const featuredInsight = computed(() => {
    if (props.configTrustState.kind === 'stale_with_draft_conflict') {
        return 'This browser is behind a newer saved config and also has local draft changes.'
    }
    if (props.configTrustState.kind === 'stale_but_safe') {
        return 'A newer saved config is available, and this page can reload it safely.'
    }
    if (props.configTrustState.kind === 'checking') {
        return 'Moonwalker is checking whether this page still matches the latest saved configuration.'
    }
    if (props.readiness.dryRun) {
        return 'Safe dry-run configuration is current and ready for operator review.'
    }
    return 'Live trading is running on the latest saved configuration.'
})

const latestSavedLabel = computed(
    () => props.formattedTrustTimestamp ?? 'No timestamp yet',
)

const tradingPostureLabel = computed(() =>
    props.readiness.dryRun ? 'Dry run' : 'Live',
)

const snapshotLabel = computed(() => {
    if (props.configTrustState.kind === 'checking') {
        return 'Checking'
    }
    if (isStale.value) {
        return 'Behind'
    }
    return 'Current'
})

const alertTitle = computed(() => {
    if (props.configTrustState.kind === 'checking') {
        return 'Checking config freshness'
    }
    if (props.configTrustState.kind === 'stale_with_draft_conflict') {
        return 'Reload required before trusting this draft'
    }
    if (props.configTrustState.kind === 'stale_but_safe') {
        return 'Newer saved config available'
    }
    return null
})
</script>

<template>
    <n-card
        class="config-preview"
        content-style="padding: 18px 20px;"
    >
        <n-flex vertical :size="14" class="preview-stack">
            <div class="preview-header">
                <div class="preview-copy">
                    <h2 class="preview-title">{{ statusTitle }}</h2>
                    <n-text depth="3" class="preview-summary">
                        {{ statusBody }}
                    </n-text>
                </div>
                <div class="preview-actions">
                    <n-button
                        v-if="readiness.dryRun"
                        type="primary"
                        strong
                        :loading="activationLoading"
                        @click="emit('activate-live')"
                    >
                        Activate live trading
                    </n-button>
                    <n-button secondary @click="emit('open-config')">
                        Open Setup
                    </n-button>
                </div>
            </div>

            <n-alert
                v-if="alertTitle"
                :type="configTrustState.tone"
                :bordered="false"
                :title="alertTitle"
            >
                {{ configTrustState.summary }}
            </n-alert>

            <div class="hero-insight">
                <p class="hero-insight-copy">{{ featuredInsight }}</p>
                <p class="hero-insight-meta">
                    Latest saved {{ latestSavedLabel }}
                </p>
            </div>

            <div class="preview-metrics">
                <div class="metric-chip">
                    <span class="metric-label">Snapshot</span>
                    <strong class="metric-value">{{ snapshotLabel }}</strong>
                </div>
                <div class="metric-chip">
                    <span class="metric-label">Trading posture</span>
                    <strong class="metric-value">{{ tradingPostureLabel }}</strong>
                </div>
                <div class="metric-chip">
                    <span class="metric-label">Latest saved</span>
                    <strong class="metric-value">{{ latestSavedLabel }}</strong>
                </div>
            </div>
        </n-flex>
    </n-card>
</template>

<style scoped>
.config-preview {
    width: 100%;
    border-color: rgba(29, 92, 73, 0.14);
    background: var(--mw-surface-shell);
    box-shadow: var(--mw-shadow-card);
    color: var(--mw-color-text-primary);
}

.preview-title {
    margin: 6px 0 4px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.preview-copy {
    flex: 1 1 auto;
    min-width: 0;
}

.preview-actions {
    display: flex;
    flex: 0 0 auto;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-end;
}

.preview-header {
    width: 100%;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: nowrap;
}

.preview-summary {
    display: block;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.hero-insight {
    padding: 14px 16px;
    border-radius: 10px;
    background: var(--mw-surface-card-subtle);
    border: 1px solid rgba(29, 92, 73, 0.1);
}

.hero-insight-copy {
    margin: 0 0 6px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.1rem;
    font-weight: 600;
    letter-spacing: -0.015em;
}

.hero-insight-meta {
    margin: 0;
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-body);
    font-size: 0.95rem;
}

.preview-metrics {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(3, minmax(0, 1fr));
}

.metric-chip {
    padding: 12px 14px;
    border-radius: 10px;
    background: var(--mw-surface-card-muted);
    border: 1px solid var(--mw-color-border-subtle, #d5dbd5);
}

.metric-label {
    display: block;
    margin-bottom: 6px;
    color: var(--mw-color-text-secondary);
    font-size: 0.84rem;
}

.metric-value {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-mono);
    font-size: 1rem;
}

@media (max-width: 768px) {
    .preview-header {
        flex-wrap: wrap;
    }

    .preview-actions {
        width: 100%;
        justify-content: flex-start;
    }

    .preview-actions :deep(.n-button) {
        flex: 1 1 auto;
    }

    .preview-metrics {
        grid-template-columns: 1fr;
    }

    .preview-summary {
        white-space: normal;
    }
}
</style>
