<script setup lang="ts">
import { computed } from 'vue'

import type { AutopilotMemoryPayload } from '../../autopilot/types'
import {
    formatAutopilotEntrySizingBody,
    formatAutopilotEntrySizingTitle,
    formatAutopilotFeaturedInsight,
    formatAutopilotStatusBody,
    formatAutopilotStatusTitle,
} from '../../autopilot/presentation'

const props = defineProps<{
    enabled: boolean
    error: string | null
    loading: boolean
    toggleLoading: boolean
    memory: AutopilotMemoryPayload | null
}>()

const emit = defineEmits<{
    'toggle-autopilot': []
    'tune-autopilot': []
}>()

const statusTitle = computed(() => formatAutopilotStatusTitle(props.memory))
const statusBody = computed(() => formatAutopilotStatusBody(props.memory))
const featuredInsight = computed(() =>
    formatAutopilotFeaturedInsight(props.memory?.featured),
)
const entrySizingTitle = computed(() =>
    formatAutopilotEntrySizingTitle(props.memory),
)
const entrySizingBody = computed(() =>
    formatAutopilotEntrySizingBody(props.memory),
)
const primaryActionLabel = computed(() =>
    props.enabled ? 'Deactivate Autopilot' : 'Activate Autopilot',
)
const trustSummary = computed(() => {
    if (!props.memory) {
        return ''
    }
    const favoredCount = props.memory.trust_board.favored.length
    const coolingCount = props.memory.trust_board.cooling.length
    return `${favoredCount} favored / ${coolingCount} cooling`
})
</script>

<template>
    <section class="autopilot-preview system-preview">
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
                        type="primary"
                        strong
                        :loading="toggleLoading"
                        @click="emit('toggle-autopilot')"
                    >
                        {{ primaryActionLabel }}
                    </n-button>
                    <n-button secondary @click="emit('tune-autopilot')">
                        Tune Autopilot
                    </n-button>
                </div>
            </div>

            <n-alert
                v-if="error"
                type="warning"
                title="Autopilot preview unavailable"
                :bordered="false"
            >
                {{ error }}
            </n-alert>

            <template v-else-if="loading && !memory">
                <n-skeleton text :repeat="3" />
            </template>

            <template v-else-if="memory">
                <n-alert
                    v-if="memory.stale || memory.status === 'warming_up'"
                    :type="memory.stale ? 'warning' : 'info'"
                    :bordered="false"
                    :title="
                        memory.stale
                            ? 'Baseline Autopilot active'
                            : 'Still learning'
                    "
                >
                    {{
                        memory.stale
                            ? 'Moonwalker kept the last known trust board visible while it falls back to baseline behavior.'
                            : `Learning from ${memory.warmup.current_closes} of ${memory.warmup.required_closes} closes.`
                    }}
                </n-alert>

                <div class="hero-insight">
                    <p class="hero-insight-copy">{{ featuredInsight }}</p>
                    <p class="hero-insight-meta">
                        {{ trustSummary }}
                    </p>
                </div>

                <p class="entry-sizing-note">
                    {{ entrySizingBody }}
                </p>

                <div class="preview-metrics">
                    <div class="metric-chip">
                        <span class="metric-label">Adaptive TP band</span>
                        <strong class="metric-value">
                            {{
                                memory.portfolio_effect.adaptive_tp_min !== null &&
                                memory.portfolio_effect.adaptive_tp_max !== null
                                    ? `${memory.portfolio_effect.adaptive_tp_min} - ${memory.portfolio_effect.adaptive_tp_max}%`
                                    : 'Pending'
                            }}
                        </strong>
                    </div>
                    <div class="metric-chip">
                        <span class="metric-label">Entry sizing</span>
                        <strong class="metric-value">
                            {{ entrySizingTitle }}
                        </strong>
                    </div>
                </div>
            </template>
        </n-flex>
    </section>
</template>

<style scoped>
.autopilot-preview {
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

.entry-sizing-note {
    margin: -4px 0 0;
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-body);
    font-size: 0.95rem;
    line-height: 1.55;
}

.preview-metrics {
    display: grid;
    gap: 10px 16px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
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
