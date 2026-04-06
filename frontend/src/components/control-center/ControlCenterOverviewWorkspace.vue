<script setup lang="ts">
import type {
    ControlCenterBlocker,
    ControlCenterReadiness,
    ControlCenterTarget,
} from '../../control-center/types'

defineProps<{
    activationLoading: boolean
    exchangeCurrency: string | null | undefined
    exchangeName: string | null | undefined
    liveActivationRef?: (element: Element | null) => void
    readiness: ControlCenterReadiness
    signalSource: string | null | undefined
    visibleBlockers: ControlCenterBlocker[]
}>()

const emit = defineEmits<{
    'activate-live': []
    'select-target': [target: ControlCenterTarget]
}>()
</script>

<template>
    <n-card class="workspace-card" content-style="padding: 18px 20px;">
        <n-flex vertical :size="14">
            <n-text depth="3">
                {{
                    visibleBlockers.length > 0
                        ? 'Targeted recovery cards'
                        : 'Calm operator overview'
                }}
            </n-text>
            <n-flex :wrap="true" :size="[14, 14]">
                <n-card
                    v-for="blocker in visibleBlockers"
                    :key="blocker.key"
                    size="small"
                    class="status-card"
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

                <template v-if="visibleBlockers.length === 0">
                    <n-card size="small" class="status-card">
                        <n-flex vertical :size="10">
                            <h2 class="status-card-title">Exchange connection</h2>
                            <n-text depth="3">
                                {{ exchangeName || 'Not configured' }} /
                                {{ exchangeCurrency || 'No quote currency' }}
                            </n-text>
                            <n-button secondary @click="emit('select-target', 'exchange')">
                                Review exchange
                            </n-button>
                        </n-flex>
                    </n-card>

                    <n-card size="small" class="status-card">
                        <n-flex vertical :size="10">
                            <h2 class="status-card-title">Signal source</h2>
                            <n-text depth="3">
                                {{ signalSource || 'Not configured' }}
                            </n-text>
                            <n-button secondary @click="emit('select-target', 'signal')">
                                Review signal source
                            </n-button>
                        </n-flex>
                    </n-card>

                    <div
                        :ref="liveActivationRef"
                        class="status-card"
                        id="control-center-live-activation"
                    >
                        <n-card size="small">
                            <n-flex vertical :size="10">
                                <div tabindex="-1" data-control-center-anchor>
                                    <h2 class="status-card-title">
                                        {{ readiness.dryRun ? 'Trading mode: Dry run' : 'Trading mode: Live' }}
                                    </h2>
                                    <n-text depth="3">
                                        {{
                                            readiness.dryRun
                                                ? 'Moonwalker is simulating orders. Use the guarded activation action to go live.'
                                                : 'Moonwalker is submitting live orders to the configured exchange.'
                                        }}
                                    </n-text>
                                </div>
                                <n-button
                                    v-if="readiness.dryRun"
                                    type="primary"
                                    strong
                                    :loading="activationLoading"
                                    @click="emit('activate-live')"
                                >
                                    Activate live trading
                                </n-button>
                                <n-button
                                    v-else
                                    secondary
                                    @click="emit('select-target', 'exchange')"
                                >
                                    Review safeguards
                                </n-button>
                            </n-flex>
                        </n-card>
                    </div>
                </template>
            </n-flex>
        </n-flex>
    </n-card>
</template>

<style scoped>
.workspace-card {
    width: 100%;
}

.status-card {
    min-width: min(320px, 100%);
    flex: 1 1 280px;
}

.status-card-title {
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
</style>
