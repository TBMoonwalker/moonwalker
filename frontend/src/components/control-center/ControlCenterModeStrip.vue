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
const ORDER = CONTROL_CENTER_MODES.filter((mode) => mode === 'setup' || mode === 'advanced') as ControlCenterMode[]
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
    <div
        ref="tablistRef"
        role="tablist"
        aria-label="Configuration sections"
        class="mode-strip-shell"
        @keydown="onKeydown"
    >
        <n-button
            role="tab"
            :id="tabId('setup')"
            :aria-selected="routeMode === 'setup'"
            :aria-controls="PANEL_ID"
            :tabindex="routeMode === 'setup' ? 0 : -1"
            :class="{ 'is-selected': routeMode === 'setup' }"
            @click="selectMode('setup')"
        >
            <span class="mode-title">Setup</span>
            <span class="mode-description">Exchange, signals, and trade rules</span>
        </n-button>
        <n-button
            role="tab"
            :id="tabId('advanced')"
            :aria-selected="routeMode === 'advanced'"
            :aria-controls="PANEL_ID"
            :tabindex="routeMode === 'advanced' ? 0 : -1"
            :class="{ 'is-selected': routeMode === 'advanced' }"
            @click="selectMode('advanced')"
        >
            <span class="mode-title">Advanced</span>
            <span class="mode-description">Safeguards, filters, and Autopilot</span>
        </n-button>
    </div>
</template>

<style scoped>
.mode-strip-shell {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px;
    padding: 4px;
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-md);
    background: var(--mw-color-surface-panel);
}
.mode-strip-shell :deep(.n-button) {
    width: 100%;
    min-height: 62px;
    height: auto;
    padding: 10px 14px;
    border: 0;
    border-radius: var(--mw-radius-sm);
    background: transparent;
    text-align: left;
}
.mode-strip-shell :deep(.n-button .n-button__content) {
    display: grid;
    justify-items: start;
    gap: 2px;
    white-space: normal;
}
.mode-strip-shell :deep(.n-button.is-selected) {
    background: var(--mw-color-primary-soft);
}
.mode-title { color: var(--mw-color-text-primary); font-size: 14px; font-weight: 600; }
.is-selected .mode-title { color: var(--mw-color-primary-strong); }
.mode-description { color: var(--mw-color-text-muted); font-size: 12px; font-weight: 400; }
</style>
