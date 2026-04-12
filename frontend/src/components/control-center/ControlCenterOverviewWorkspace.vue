<script setup lang="ts">
import type { AutopilotMemoryPayload } from '../../autopilot/types'
import type {
    ControlCenterConfigTrustState,
    ControlCenterBlocker,
    ControlCenterTarget,
    ControlCenterReadiness,
} from '../../control-center/types'
import ControlCenterAutopilotPreview from './ControlCenterAutopilotPreview.vue'
import ControlCenterConfigPreview from './ControlCenterConfigPreview.vue'
import ControlCenterMonitoringPreview from './ControlCenterMonitoringPreview.vue'

defineProps<{
    activationLoading: boolean
    autopilotEnabled: boolean
    autopilotMemory: AutopilotMemoryPayload | null
    autopilotMemoryError: string | null
    autopilotMemoryLoading: boolean
    autopilotToggleLoading: boolean
    configTrustState: ControlCenterConfigTrustState
    formattedTrustTimestamp: string | null
    liveActivationRef?: (element: Element | null) => void
    readiness: ControlCenterReadiness
    visibleBlockers: ControlCenterBlocker[]
}>()

const emit = defineEmits<{
    'activate-live': []
    'open-config': []
    'open-monitoring': []
    'select-target': [target: ControlCenterTarget]
    'toggle-autopilot': []
    'tune-autopilot': []
}>()
</script>

<template>
    <n-card
        :ref="visibleBlockers.length === 0 ? liveActivationRef : undefined"
        class="workspace-card mw-shell-card"
        content-style="padding: 18px 20px;"
        id="control-center-live-activation"
    >
        <n-flex vertical :size="14">
            <n-text depth="3">
                {{
                    visibleBlockers.length > 0
                        ? 'Recovery priorities'
                        : 'Operator overview'
                }}
            </n-text>

            <n-flex v-if="visibleBlockers.length > 0" :wrap="true" :size="[14, 14]">
                <n-card
                    v-for="blocker in visibleBlockers"
                    :key="blocker.key"
                    size="small"
                    class="status-card mw-muted-card"
                >
                    <n-flex vertical :size="10">
                        <div>
                            <h2 class="status-card-title">
                                {{ blocker.title }}
                            </h2>
                            <n-text depth="3">
                                {{ blocker.description }}
                            </n-text>
                        </div>
                        <n-button
                            type="primary"
                            secondary
                            @click="emit('select-target', blocker.target)"
                        >
                            Fix this
                        </n-button>
                    </n-flex>
                </n-card>
            </n-flex>

            <template v-else>
                <div class="overview-section">
                    <div class="section-copy">
                        <h2 class="section-title">Operator systems</h2>
                        <n-text depth="3">
                            Configuration status, Autopilot, and Monitoring surfaces that explain what Moonwalker is doing right now.
                        </n-text>
                    </div>

                    <div class="systems-grid">
                        <ControlCenterConfigPreview
                            :activation-loading="activationLoading"
                            :config-trust-state="configTrustState"
                            :formatted-trust-timestamp="formattedTrustTimestamp"
                            :readiness="readiness"
                            @activate-live="emit('activate-live')"
                            @open-config="emit('open-config')"
                        />
                        <ControlCenterAutopilotPreview
                            :enabled="autopilotEnabled"
                            :error="autopilotMemoryError"
                            :loading="autopilotMemoryLoading"
                            :memory="autopilotMemory"
                            :toggle-loading="autopilotToggleLoading"
                            @toggle-autopilot="emit('toggle-autopilot')"
                            @tune-autopilot="emit('tune-autopilot')"
                        />
                        <ControlCenterMonitoringPreview
                            @open-monitoring="emit('open-monitoring')"
                        />
                    </div>
                </div>
            </template>
        </n-flex>
    </n-card>
</template>

<style scoped>
.workspace-card {
    width: 100%;
}

.overview-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.section-copy {
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-width: 60ch;
}

.section-title {
    margin: 0;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.12rem;
    font-weight: 700;
    letter-spacing: -0.015em;
}
.systems-grid {
    display: grid;
    gap: 14px;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    align-items: start;
}

.status-card {
    min-width: 0;
}

.status-card-title {
    margin: 0;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
}

.status-card :deep(.n-button--primary-type .n-button__content) {
    color: #f7f8f6;
    font-weight: 700;
    letter-spacing: 0.01em;
}

@media (max-width: 768px) {
    .systems-grid {
        grid-template-columns: 1fr;
    }
}
</style>
