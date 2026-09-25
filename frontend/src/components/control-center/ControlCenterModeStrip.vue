<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { CONTROL_CENTER_MODES } from '../../control-center/types'
import type { ControlCenterMode } from '../../control-center/types'

const props = defineProps<{
    routeMode: ControlCenterMode
}>()

const emit = defineEmits<{
    'select-mode': [mode: ControlCenterMode]
}>()

// Logical order for roving-tabindex + arrow-key navigation, independent of the
// visual grouping below (a screen reader user traverses the flat tablist).
const ORDER = [...CONTROL_CENTER_MODES] as ControlCenterMode[]
const PANEL_ID = 'cc-workspace-panel'
const tablistRef = ref<HTMLElement | null>(null)

const tabId = (mode: ControlCenterMode) => `cc-mode-tab-${mode}`

function selectMode(mode: ControlCenterMode) {
    emit('select-mode', mode)
}

function focusTab(mode: ControlCenterMode) {
    tablistRef.value
        ?.querySelector<HTMLElement>(`[id="${tabId(mode)}"]`)
        ?.focus()
}

// Roving tabindex: only the active tab is in the tab order. Arrow keys move
// focus AND select (automatic-activation pattern, matching that a mode switch
// is also a route change), with wrap + Home/End.
function onKeydown(event: KeyboardEvent) {
    const i = ORDER.indexOf(props.routeMode)
    if (i === -1) return
    let next: number
    switch (event.key) {
        case 'ArrowRight':
        case 'ArrowDown':
            next = (i + 1) % ORDER.length
            break
        case 'ArrowLeft':
        case 'ArrowUp':
            next = (i - 1 + ORDER.length) % ORDER.length
            break
        case 'Home':
            next = 0
            break
        case 'End':
            next = ORDER.length - 1
            break
        default:
            return
    }
    event.preventDefault()
    const mode = ORDER[next]
    selectMode(mode)
    // Selection (routeMode) updates on the parent side; focus after the DOM
    // re-renders so the roving tabindex has moved to `mode` first.
    void nextTick(() => focusTab(mode))
}
</script>

<template>
    <n-card class="mode-strip-card dashboard-panel" content-style="padding: 10px 14px;">
        <div
            ref="tablistRef"
            role="tablist"
            aria-label="Control center workspaces"
            class="mode-strip-shell"
            @keydown="onKeydown"
        >
            <div class="mode-group">
                <span class="mode-group-label" aria-hidden="true">Operate</span>
                <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                    <n-button
                        role="tab"
                        :id="tabId('overview')"
                        :aria-selected="routeMode === 'overview'"
                        :aria-controls="PANEL_ID"
                        :tabindex="routeMode === 'overview' ? 0 : -1"
                        :type="routeMode === 'overview' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'overview'"
                        :strong="routeMode === 'overview'"
                        @click="selectMode('overview')"
                    >
                        Overview
                    </n-button>
                </n-flex>
            </div>

            <div class="mode-group">
                <span class="mode-group-label" aria-hidden="true">Configure</span>
                <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                    <n-button
                        role="tab"
                        :id="tabId('setup')"
                        :aria-selected="routeMode === 'setup'"
                        :aria-controls="PANEL_ID"
                        :tabindex="routeMode === 'setup' ? 0 : -1"
                        :type="routeMode === 'setup' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'setup'"
                        :strong="routeMode === 'setup'"
                        @click="selectMode('setup')"
                    >
                        Setup
                    </n-button>
                    <n-button
                        role="tab"
                        :id="tabId('advanced')"
                        :aria-selected="routeMode === 'advanced'"
                        :aria-controls="PANEL_ID"
                        :tabindex="routeMode === 'advanced' ? 0 : -1"
                        :type="routeMode === 'advanced' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'advanced'"
                        :strong="routeMode === 'advanced'"
                        @click="selectMode('advanced')"
                    >
                        Advanced
                    </n-button>
                </n-flex>
            </div>

            <div class="mode-group">
                <span class="mode-group-label" aria-hidden="true">Build</span>
                <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                    <n-button
                        role="tab"
                        :id="tabId('strategy-builder')"
                        :aria-selected="routeMode === 'strategy-builder'"
                        :aria-controls="PANEL_ID"
                        :tabindex="routeMode === 'strategy-builder' ? 0 : -1"
                        :type="routeMode === 'strategy-builder' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'strategy-builder'"
                        :strong="routeMode === 'strategy-builder'"
                        @click="selectMode('strategy-builder')"
                    >
                        Strategy Builder
                    </n-button>
                </n-flex>
            </div>

            <div class="mode-group">
                <span class="mode-group-label" aria-hidden="true">Utilities</span>
                <n-flex class="mode-strip" :wrap="true" :size="[10, 10]">
                    <n-button
                        role="tab"
                        :id="tabId('utilities')"
                        :aria-selected="routeMode === 'utilities'"
                        :aria-controls="PANEL_ID"
                        :tabindex="routeMode === 'utilities' ? 0 : -1"
                        :type="routeMode === 'utilities' ? 'primary' : 'default'"
                        :secondary="routeMode !== 'utilities'"
                        :strong="routeMode === 'utilities'"
                        @click="selectMode('utilities')"
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

@media (max-width: 767px) {
    .mode-strip-shell {
        gap: 12px;
    }
}
</style>
