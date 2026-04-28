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
    <section class="config-preview system-preview">
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
    </section>
</template>

<style scoped>
.config-preview {
    width: 100%;
    color: var(--mw-color-text-primary);
}

.preview-title {
    margin: 0 0 4px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.12rem;
    font-weight: 700;
    letter-spacing: -0.015em;
}

.preview-copy {
    flex: 1 1 auto;
    min-width: 0;
}

.preview-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-start;
}

.preview-header {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
}

.preview-summary {
    display: block;
    min-width: 0;
    color: var(--mw-color-text-secondary);
    line-height: 1.55;
    text-wrap: pretty;
}

.hero-insight {
    padding-left: 14px;
    border-left: 3px solid rgba(29, 92, 73, 0.24);
}

.hero-insight-copy {
    margin: 0 0 6px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1rem;
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
    gap: 10px 16px;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    padding-top: 8px;
    border-top: 1px solid rgba(29, 92, 73, 0.1);
}

.metric-chip {
    min-width: 0;
}

.metric-label {
    display: block;
    margin-bottom: 4px;
    color: var(--mw-color-text-secondary);
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.metric-value {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-mono);
    font-size: 1rem;
    line-height: 1.4;
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
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .preview-summary {
        white-space: normal;
    }
}

@media (max-width: 520px) {
    .preview-metrics {
        grid-template-columns: 1fr;
    }
}
</style>
