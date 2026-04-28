<script setup lang="ts">
import { useControlCenterMonitoringSummary } from '../../composables/useControlCenterMonitoringSummary'

const emit = defineEmits<{
    'open-monitoring': []
}>()

const monitoring = useControlCenterMonitoringSummary()
</script>

<template>
    <!-- Naive card/alert wrappers here triggered a production-only console error on overview load. -->
    <section class="monitoring-preview">
        <div class="preview-stack">
            <div class="preview-header">
                <div class="preview-copy">
                    <h2 class="preview-title">{{ monitoring.statusTitle }}</h2>
                    <p class="preview-summary">
                        {{ monitoring.statusBody }}
                    </p>
                </div>
                <div class="preview-actions">
                    <n-button secondary @click="emit('open-monitoring')">
                        Open Monitoring
                    </n-button>
                </div>
            </div>

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
        </div>
    </section>
</template>

<style scoped>
.monitoring-preview {
    width: 100%;
    color: var(--mw-color-text-primary);
}

.preview-stack {
    display: flex;
    flex-direction: column;
    gap: 14px;
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
    margin: 0;
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
        grid-template-columns: 1fr;
    }

    .preview-summary {
        white-space: normal;
    }
}
</style>
