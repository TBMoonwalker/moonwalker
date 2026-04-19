<script setup lang="ts">
import { useControlCenterMonitoringSummary } from '../../composables/useControlCenterMonitoringSummary'

const emit = defineEmits<{
    'open-monitoring': []
}>()

const monitoring = useControlCenterMonitoringSummary()
</script>

<template>
    <n-card
        class="monitoring-preview"
        content-style="padding: 18px 20px;"
    >
        <n-flex vertical :size="14" class="preview-stack">
            <div class="preview-header">
                <div class="preview-copy">
                    <h2 class="preview-title">{{ monitoring.statusTitle }}</h2>
                    <n-text depth="3" class="preview-summary">
                        {{ monitoring.statusBody }}
                    </n-text>
                </div>
                <div class="preview-actions">
                    <n-button secondary @click="emit('open-monitoring')">
                        Open Monitoring
                    </n-button>
                </div>
            </div>

            <n-alert
                v-if="monitoring.alertTitle"
                :type="monitoring.alertType"
                :bordered="false"
                :title="monitoring.alertTitle"
            >
                {{ monitoring.statusBody }}
            </n-alert>

            <div class="hero-insight">
                <p class="hero-insight-copy">{{ monitoring.featuredInsight }}</p>
                <p class="hero-insight-meta">
                    {{ monitoring.receivingCount }} of
                    {{ monitoring.totalStreams }} streams receiving payloads
                </p>
            </div>

            <div class="preview-metrics">
                <div class="metric-chip">
                    <span class="metric-label">Open streams</span>
                    <strong class="metric-value">
                        {{ monitoring.openCount }}/{{ monitoring.totalStreams }}
                    </strong>
                </div>
                <div class="metric-chip">
                    <span class="metric-label">Receiving payloads</span>
                    <strong class="metric-value">
                        {{ monitoring.receivingCount }}/{{ monitoring.totalStreams }}
                    </strong>
                </div>
                <div class="metric-chip">
                    <span class="metric-label">Reconnects</span>
                    <strong class="metric-value">
                        {{ monitoring.totalReconnects }}
                    </strong>
                </div>
            </div>
        </n-flex>
    </n-card>
</template>

<style scoped>
.monitoring-preview {
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
