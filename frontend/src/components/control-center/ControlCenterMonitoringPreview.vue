<script setup lang="ts">
import { useControlCenterMonitoringSummary } from '../../composables/useControlCenterMonitoringSummary'

const emit = defineEmits<{
    'open-monitoring': []
}>()

const monitoring = useControlCenterMonitoringSummary()
</script>

<template>
    <!-- Naive wrappers here triggered a production-only console error on overview load. -->
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
                    <button
                        type="button"
                        class="preview-action-button"
                        @click="emit('open-monitoring')"
                    >
                        Open Monitoring
                    </button>
                </div>
            </div>

            <div
                v-if="monitoring.alertTitle"
                class="preview-alert"
                :data-tone="
                    monitoring.health === 'attention_needed'
                        ? 'warning'
                        : 'info'
                "
            >
                <strong class="preview-alert-title">
                    {{ monitoring.alertTitle }}
                </strong>
                <p class="preview-alert-body">
                    {{ monitoring.statusBody }}
                </p>
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
    padding: 18px 20px;
    border-radius: 12px;
    border-color: rgba(29, 92, 73, 0.14);
    border: 1px solid rgba(29, 92, 73, 0.14);
    background: var(--mw-surface-shell);
    box-shadow: var(--mw-shadow-card);
    color: var(--mw-color-text-primary);
}

.preview-stack {
    display: flex;
    flex-direction: column;
    gap: 14px;
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
    margin: 0;
    min-width: 0;
    color: var(--mw-color-text-secondary);
    line-height: 1.55;
    text-wrap: pretty;
}

.preview-action-button {
    border: 1px solid rgba(29, 92, 73, 0.18);
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.7);
    color: var(--mw-color-text-primary);
    cursor: pointer;
    font: inherit;
    font-weight: 600;
    line-height: 1;
    padding: 0.72rem 1rem;
    transition:
        background-color 120ms ease,
        border-color 120ms ease,
        transform 120ms ease;
}

.preview-action-button:hover {
    background: rgba(29, 92, 73, 0.08);
    border-color: rgba(29, 92, 73, 0.28);
}

.preview-action-button:focus-visible {
    outline: 2px solid rgba(29, 92, 73, 0.35);
    outline-offset: 2px;
}

.preview-alert {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid rgba(53, 109, 134, 0.16);
    background: rgba(53, 109, 134, 0.08);
}

.preview-alert[data-tone='warning'] {
    border-color: rgba(183, 121, 31, 0.18);
    background: rgba(183, 121, 31, 0.1);
}

.preview-alert-title {
    color: var(--mw-color-text-primary);
    font-size: 0.95rem;
    font-weight: 700;
}

.preview-alert-body {
    margin: 0;
    color: var(--mw-color-text-secondary);
    font-size: 0.95rem;
    line-height: 1.55;
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

    .preview-metrics {
        grid-template-columns: 1fr;
    }

    .preview-summary {
        white-space: normal;
    }

    .preview-action-button {
        width: 100%;
    }
}
</style>
