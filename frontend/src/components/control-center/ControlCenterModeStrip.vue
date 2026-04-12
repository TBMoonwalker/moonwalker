<script setup lang="ts">
import type { ControlCenterMode } from '../../control-center/types'

defineProps<{
    routeMode: ControlCenterMode
}>()

const emit = defineEmits<{
    'select-mode': [mode: ControlCenterMode]
}>()
</script>

<template>
    <n-card class="mode-strip-card mw-shell-card" content-style="padding: 12px 14px;">
        <div class="mode-strip-shell">
            <div class="mode-group">
                <n-text depth="3" class="mode-group-label">Operate</n-text>
                <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                    <n-button
                        :type="routeMode === 'overview' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'overview'"
                        :strong="routeMode === 'overview'"
                        @click="emit('select-mode', 'overview')"
                    >
                        Overview
                    </n-button>
                </n-flex>
            </div>

            <div class="mode-group">
                <n-text depth="3" class="mode-group-label">Configure</n-text>
                <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                    <n-button
                        :type="routeMode === 'setup' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'setup'"
                        :strong="routeMode === 'setup'"
                        @click="emit('select-mode', 'setup')"
                    >
                        Setup
                    </n-button>
                    <n-button
                        :type="routeMode === 'advanced' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'advanced'"
                        :strong="routeMode === 'advanced'"
                        @click="emit('select-mode', 'advanced')"
                    >
                        Advanced
                    </n-button>
                </n-flex>
            </div>

            <div class="mode-group">
                <n-text depth="3" class="mode-group-label">Utilities</n-text>
                <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                    <n-button
                        :type="routeMode === 'utilities' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'utilities'"
                        :strong="routeMode === 'utilities'"
                        @click="emit('select-mode', 'utilities')"
                    >
                        Utilities
                    </n-button>
                </n-flex>
            </div>
        </div>
    </n-card>
</template>

<style scoped>
.mode-strip-card {
    border: 1px solid var(--color-border-hover);
}

.mode-strip-shell {
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    justify-content: space-between;
}

.mode-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.mode-group-label {
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.mode-strip {
    align-items: center;
}

.mode-strip :deep(.n-button--primary-type .n-button__content) {
    color: #f7f8f6;
    font-weight: 700;
    letter-spacing: 0.01em;
}

@media (max-width: 768px) {
    .mode-strip-shell {
        gap: 12px;
    }
}
</style>
