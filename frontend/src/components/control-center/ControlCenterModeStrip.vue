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
    <n-card class="mode-strip-card dashboard-panel" content-style="padding: 10px 14px;">
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
                        :type="routeMode === 'strategy-builder' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'strategy-builder'"
                        :strong="routeMode === 'strategy-builder'"
                        @click="emit('select-mode', 'strategy-builder')"
                    >
                        Strategy Builder
                    </n-button>
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
.mode-strip-shell {
    display: flex;
    flex-wrap: wrap;
    gap: 16px 28px;
    justify-content: space-between;
}

.mode-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.mode-group-label {
    font-size: 0.78rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}

.mode-strip {
    align-items: center;
}

.mode-strip :deep(.n-button) {
    --n-border: 0 !important;
    --n-border-hover: 0 !important;
    --n-border-pressed: 0 !important;
    --n-border-focus: 0 !important;
    min-height: 36px;
    padding-inline: 6px;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
}

.mode-strip :deep(.n-button::before),
.mode-strip :deep(.n-button::after) {
    display: none;
}

.mode-strip :deep(.n-button .n-button__content) {
    color: var(--mw-color-text-secondary);
    font-weight: 450;
}

.mode-strip :deep(.n-button--primary-type) {
    position: relative;
    background: transparent;
}

.mode-strip :deep(.n-button--primary-type::after) {
    display: block;
    position: absolute;
    right: 6px;
    bottom: 0;
    left: 6px;
    height: 2px;
    border-radius: 999px;
    background: var(--mw-color-primary);
    content: "";
}

.mode-strip :deep(.n-button--primary-type .n-button__content) {
    color: var(--mw-color-primary);
    font-weight: 450;
    letter-spacing: 0;
}

@media (max-width: 768px) {
    .mode-strip-shell {
        gap: 12px;
    }
}
</style>
