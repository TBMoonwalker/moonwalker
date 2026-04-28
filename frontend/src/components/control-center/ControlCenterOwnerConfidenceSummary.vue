<script setup lang="ts">
import { computed } from 'vue'

import type { AutopilotMemoryPayload } from '../../autopilot/types'
import type {
    ControlCenterConfigTrustState,
    ControlCenterReadiness,
} from '../../control-center/types'
import { useControlCenterMonitoringSummary } from '../../composables/useControlCenterMonitoringSummary'

interface ConfidenceEvidenceItem {
    detail: string
    label: string
    value: string
}

const props = defineProps<{
    autopilotMemory: AutopilotMemoryPayload | null
    autopilotMemoryError: string | null
    configTrustState: ControlCenterConfigTrustState
    formattedTrustTimestamp: string | null
    readiness: ControlCenterReadiness
}>()

const monitoring = useControlCenterMonitoringSummary()

const configValue = computed(() => {
    if (props.configTrustState.kind === 'checking') {
        return 'Checking'
    }
    if (props.configTrustState.kind === 'stale_with_draft_conflict') {
        return 'Draft conflict'
    }
    if (props.configTrustState.kind === 'stale_but_safe') {
        return 'Needs reload'
    }
    return 'Current'
})

const configDetail = computed(() => {
    if (
        props.formattedTrustTimestamp &&
        props.configTrustState.kind === 'trusted'
    ) {
        return `Latest saved ${props.formattedTrustTimestamp}.`
    }
    return props.configTrustState.summary
})

const modeValue = computed(() => {
    if (!props.readiness.complete) {
        return 'Incomplete'
    }
    return props.readiness.dryRun ? 'Dry run' : 'Live'
})

const modeDetail = computed(() => {
    if (!props.readiness.complete) {
        return `${props.readiness.blockers.length} setup item(s) still need attention.`
    }
    if (props.readiness.dryRun) {
        return 'Moonwalker is configured for safe operator review.'
    }
    return 'Moonwalker is configured for live trading.'
})

const autopilotValue = computed(() => {
    if (props.autopilotMemoryError) {
        return 'Unavailable'
    }
    if (!props.autopilotMemory) {
        return 'Loading'
    }
    if (props.autopilotMemory.stale) {
        return 'Baseline'
    }
    if (props.autopilotMemory.status === 'warming_up') {
        return 'Learning'
    }
    if (
        props.autopilotMemory.status === 'fresh' &&
        !props.autopilotMemory.enabled
    ) {
        return 'Ready but off'
    }
    if (props.autopilotMemory.status === 'fresh') {
        return 'Trust active'
    }
    return 'Idle'
})

const autopilotDetail = computed(() => {
    if (props.autopilotMemoryError) {
        return props.autopilotMemoryError
    }
    if (!props.autopilotMemory) {
        return 'Moonwalker is loading the latest Autopilot memory snapshot.'
    }
    if (props.autopilotMemory.stale) {
        return 'Last known trust board is visible while baseline behavior stays active.'
    }
    if (props.autopilotMemory.status === 'warming_up') {
        return `Learning from ${props.autopilotMemory.warmup.current_closes} of ${props.autopilotMemory.warmup.required_closes} closes.`
    }
    if (props.autopilotMemory.status === 'fresh') {
        const favoredCount = props.autopilotMemory.trust_board.favored.length
        const coolingCount = props.autopilotMemory.trust_board.cooling.length
        return `${favoredCount} favored / ${coolingCount} cooling symbols in the current board.`
    }
    return 'Closed-trade history is still too thin for symbol memory.'
})

const liveDataValue = computed(() => {
    if (monitoring.health.value === 'attention_needed') {
        return 'Needs attention'
    }
    if (monitoring.health.value === 'reconnecting') {
        return 'Reconnecting'
    }
    if (monitoring.health.value === 'warming_up') {
        return 'Warming up'
    }
    return 'Healthy'
})

const liveDataDetail = computed(() => {
    if (monitoring.health.value === 'healthy') {
        return `All ${monitoring.totalStreams.value} cockpit streams are open and receiving payloads.`
    }
    return monitoring.statusBody.value
})

const confidenceLevel = computed<'high' | 'guarded' | 'low'>(() => {
    if (
        !props.readiness.complete ||
        props.configTrustState.kind === 'stale_with_draft_conflict' ||
        monitoring.health.value === 'attention_needed'
    ) {
        return 'low'
    }

    if (
        props.configTrustState.kind !== 'trusted' ||
        monitoring.health.value !== 'healthy' ||
        props.autopilotMemoryError ||
        !props.autopilotMemory ||
        props.autopilotMemory.stale ||
        props.autopilotMemory.status !== 'fresh'
    ) {
        return 'guarded'
    }

    return 'high'
})

const confidenceLabel = computed(() => {
    if (confidenceLevel.value === 'low') {
        return 'Low confidence'
    }
    if (confidenceLevel.value === 'guarded') {
        return 'Guarded confidence'
    }
    return 'High confidence'
})

const confidenceTone = computed<'success' | 'info' | 'warning'>(() => {
    if (confidenceLevel.value === 'low') {
        return 'warning'
    }
    if (confidenceLevel.value === 'guarded') {
        return 'info'
    }
    return 'success'
})

const confidenceTitle = computed(() => {
    if (confidenceLevel.value === 'low') {
        return 'This setup needs a quick operator check'
    }
    if (confidenceLevel.value === 'guarded') {
        return 'This setup looks okay, with some caveats'
    }
    return 'This setup still looks steady'
})

const confidenceBody = computed(() => {
    if (!props.readiness.complete) {
        return `Moonwalker still has ${props.readiness.blockers.length} setup item(s) to finish before the overview is trustworthy enough for live decisions.`
    }
    if (props.configTrustState.kind === 'stale_with_draft_conflict') {
        return 'This browser has fallen behind a newer saved configuration and still has local draft changes, so reload before trusting the overview.'
    }
    if (monitoring.health.value === 'attention_needed') {
        return 'Configuration and Autopilot may still be fine, but a realtime stream is offline, so confidence stays low until Monitoring recovers.'
    }
    if (confidenceLevel.value === 'guarded') {
        const caveats: string[] = []
        if (props.configTrustState.kind === 'checking') {
            caveats.push('config freshness is still being verified')
        } else if (props.configTrustState.kind === 'stale_but_safe') {
            caveats.push('this browser is behind a newer saved config')
        }
        if (monitoring.health.value === 'reconnecting') {
            caveats.push('one live-data stream is reconnecting')
        } else if (monitoring.health.value === 'warming_up') {
            caveats.push('one live-data stream is still warming up')
        }
        if (props.autopilotMemoryError) {
            caveats.push('Autopilot memory is temporarily unavailable')
        } else if (!props.autopilotMemory) {
            caveats.push('Autopilot memory is still loading')
        } else if (props.autopilotMemory.stale) {
            caveats.push('Autopilot is holding baseline mode while memory refreshes')
        } else if (props.autopilotMemory.status === 'warming_up') {
            caveats.push('Autopilot is still learning from recent closes')
        } else if (props.autopilotMemory.status !== 'fresh') {
            caveats.push('Autopilot has not built a usable trust board yet')
        }

        return `Core setup looks okay, but confidence stays guarded while ${caveats.join(', ')}.`
    }
    if (props.readiness.dryRun) {
        return 'Moonwalker is configured for safe dry-run review, this browser is on the latest saved config, and live data is flowing.'
    }
    return 'Moonwalker is live on the latest saved config, Autopilot trust is available, and live data is flowing through the cockpit.'
})

const evidenceItems = computed<ConfidenceEvidenceItem[]>(() => [
    {
        label: 'Operating mode',
        value: modeValue.value,
        detail: modeDetail.value,
    },
    {
        label: 'Configuration',
        value: configValue.value,
        detail: configDetail.value,
    },
    {
        label: 'Autopilot',
        value: autopilotValue.value,
        detail: autopilotDetail.value,
    },
    {
        label: 'Live data',
        value: liveDataValue.value,
        detail: liveDataDetail.value,
    },
])
</script>

<template>
    <section class="owner-confidence-summary">
        <div class="confidence-shell">
            <div class="confidence-copy">
                <div class="confidence-kicker-row">
                    <span class="confidence-kicker">Owner confidence</span>
                    <n-tag class="confidence-tag" :type="confidenceTone">
                        {{ confidenceLabel }}
                    </n-tag>
                </div>
                <h2 class="confidence-title">{{ confidenceTitle }}</h2>
                <p class="confidence-summary">
                    {{ confidenceBody }}
                </p>
            </div>

            <div class="confidence-evidence-grid">
                <div
                    v-for="item in evidenceItems"
                    :key="item.label"
                    class="evidence-chip"
                >
                    <span class="evidence-label">{{ item.label }}</span>
                    <strong class="evidence-value">{{ item.value }}</strong>
                    <p class="evidence-detail">{{ item.detail }}</p>
                </div>
            </div>
        </div>
    </section>
</template>

<style scoped>
.owner-confidence-summary {
    width: 100%;
    border: 1px solid var(--mw-color-border-strong);
    border-radius: 12px;
    background: var(--mw-surface-card);
    color: var(--mw-color-text-primary);
    padding: 18px 20px;
}

.confidence-shell {
    display: grid;
    gap: 16px;
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
    align-items: start;
}

.confidence-copy {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
}

.confidence-kicker-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
}

.confidence-kicker {
    font-size: 0.82rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--mw-color-text-muted);
    font-family: var(--mw-font-body);
    font-weight: 600;
}

.confidence-title {
    margin: 0;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: clamp(1.2rem, 2.5vw, 1.55rem);
    font-weight: 700;
    letter-spacing: -0.02em;
    line-height: 1.15;
}

.confidence-summary {
    margin: 0;
    color: var(--mw-color-text-secondary);
    line-height: 1.6;
    text-wrap: pretty;
}

.confidence-evidence-grid {
    display: grid;
    gap: 12px 16px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.evidence-chip {
    padding-top: 10px;
    border-top: 1px solid var(--color-border);
    min-width: 0;
}

.evidence-label {
    display: block;
    color: var(--mw-color-text-muted);
    font-size: 0.82rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 600;
}

.evidence-value {
    display: block;
    margin-top: 6px;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
}

.evidence-detail {
    margin: 6px 0 0;
    color: var(--mw-color-text-secondary);
    font-size: 0.92rem;
    line-height: 1.5;
    text-wrap: pretty;
}

.confidence-kicker-row :deep(.confidence-tag .n-tag__content) {
    font-weight: 600;
}

@media (max-width: 900px) {
    .confidence-shell {
        grid-template-columns: 1fr;
    }
}

@media (max-width: 640px) {
    .confidence-evidence-grid {
        grid-template-columns: 1fr;
    }
}
</style>
