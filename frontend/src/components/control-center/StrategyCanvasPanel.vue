<script setup lang="ts">
import { onUnmounted, type ComponentPublicInstance } from 'vue'

import type {
    StrategyDetail,
    StrategyNode,
} from '../../types/strategyBuilder'

defineProps<{
    detail: StrategyDetail | null
    readOnly: boolean
    selectedNodeId: string | null
    reteError: string | null
    reteReady: boolean
    titleForNode: (node: StrategyNode) => string
}>()

const emit = defineEmits<{
    'host-ready': [host: HTMLElement | null]
    'update:selectedNodeId': [nodeId: string]
    'auto-align': []
}>()

function bindHost(
    element: Element | ComponentPublicInstance | null,
): void {
    emit('host-ready', element instanceof HTMLElement ? element : null)
}

onUnmounted(() => {
    emit('host-ready', null)
})
</script>

<template>
    <main class="strategy-canvas-shell" aria-label="Strategy graph">
        <div v-if="!detail" class="canvas-empty">
            Select a built-in strategy to preview its graph.
        </div>
        <template v-else>
            <div class="canvas-toolbar">
                <div>
                    <span>
                        {{
                            readOnly
                                ? 'Read-only built-in preview'
                                : 'Editable custom graph'
                        }}
                    </span>
                    <span v-if="detail.duplicated_from" class="mono">
                        from {{ detail.duplicated_from }}
                    </span>
                </div>
                <n-button
                    size="small"
                    secondary
                    :disabled="!detail.ir.nodes.length"
                    @click="emit('auto-align')"
                >
                    Auto align
                </n-button>
            </div>
            <div
                :ref="bindHost"
                class="rete-host"
                aria-label="Rete graph canvas"
            />
            <div
                v-if="!detail.ir.nodes.length"
                class="canvas-fallback"
                role="status"
            >
                This custom graph is empty. Add an indicator, logic, or state
                node from the palette.
            </div>
            <div v-if="reteError" class="canvas-fallback" role="status">
                {{ reteError }}
            </div>
            <div v-else-if="!reteReady" class="canvas-fallback" role="status">
                Preparing graph canvas...
            </div>
            <div class="node-strip" aria-label="Graph nodes">
                <button
                    v-for="node in detail.ir.nodes"
                    :key="node.id"
                    type="button"
                    class="node-chip"
                    :class="{ active: node.id === selectedNodeId }"
                    @click="emit('update:selectedNodeId', node.id)"
                >
                    {{ titleForNode(node) }}
                </button>
            </div>
        </template>
    </main>
</template>

<style scoped>
.strategy-canvas-shell {
    min-width: 0;
    overflow: hidden;
    position: relative;
}

.canvas-toolbar {
    border-bottom: 1px solid var(--mw-color-border);
    color: var(--mw-color-text-secondary);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    min-height: 44px;
    padding: 0 12px;
}

.mono {
    font-family: var(--mw-font-mono);
}

.rete-host {
    height: 680px;
    background:
        linear-gradient(rgba(29, 92, 73, 0.08) 1px, transparent 1px),
        linear-gradient(90deg, rgba(29, 92, 73, 0.08) 1px, transparent 1px);
    background-color: var(--mw-color-surface-panel);
    background-size: 32px 32px;
}

/* Rete injects a classic theme; keep Moonwalker overrides scoped to this canvas. */
.rete-host :deep(.node) {
    width: 292px;
    min-height: 86px;
    border: 1px solid var(--mw-color-border);
    border-radius: 6px;
    background: var(--mw-color-surface-raised);
    box-shadow: 0 1px 2px rgba(24, 33, 29, 0.08);
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-body);
    line-height: 1.25;
    padding-bottom: 6px;
}

.rete-host :deep(.node:hover) {
    border-color: var(--mw-color-primary);
    background: var(--mw-color-primary-soft);
}

.rete-host :deep(.node.selected) {
    border-color: var(--mw-color-primary);
    box-shadow:
        0 0 0 2px rgba(29, 92, 73, 0.16),
        0 1px 2px rgba(24, 33, 29, 0.08);
}

.rete-host :deep(.node .title) {
    border-bottom: 1px solid rgba(29, 92, 73, 0.14);
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-body);
    font-size: 0.96rem;
    font-weight: 700;
    line-height: 1.25;
    min-height: 48px;
    padding: 9px 12px 8px;
    white-space: normal;
    overflow-wrap: anywhere;
}

.rete-host :deep(.node .input),
.rete-host :deep(.node .output) {
    min-height: 28px;
    padding: 2px 0;
}

.rete-host :deep(.node .input-title),
.rete-host :deep(.node .output-title) {
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-body);
    font-size: 0.78rem;
    font-weight: 700;
    line-height: 1.2;
    padding-top: 5px;
}

.rete-host :deep(.node .input-title) {
    padding-left: 4px;
}

.rete-host :deep(.node .output-title) {
    padding-right: 4px;
}

.rete-host :deep(.socket) {
    width: 14px;
    height: 14px;
    border: 2px solid var(--mw-color-border-strong);
    background: var(--mw-color-surface-panel);
    box-shadow: none;
    margin: 6px;
}

.rete-host :deep(.socket.input) {
    border-color: rgba(183, 138, 46, 0.82);
}

.rete-host :deep(.socket.output) {
    border-color: var(--mw-color-primary);
}

.rete-host :deep(.socket:hover) {
    background: var(--mw-color-surface-base);
    border-color: var(--mw-color-primary-strong);
}

.rete-host :deep(.control) {
    padding: 5px 10px 2px;
}

.rete-host :deep(.input-control) {
    width: 100%;
}

.rete-host :deep(.input-control input) {
    min-height: 32px;
    border: 1px solid var(--mw-color-border);
    border-radius: 4px;
    background: var(--mw-color-surface-panel);
    color: var(--mw-color-text-secondary);
    font-family: var(--mw-font-mono);
    font-size: 0.8rem;
    padding: 5px 8px;
}

.rete-host :deep(.node .control input[readonly]) {
    box-sizing: border-box;
    width: 100%;
    min-height: 32px;
    border: 1px solid rgba(29, 92, 73, 0.22);
    border-radius: 4px;
    background: var(--mw-color-primary-soft);
    color: var(--mw-color-primary-strong);
    cursor: default;
    font-family: var(--mw-font-mono);
    font-size: 0.8rem;
    font-weight: 700;
    padding: 4px 7px;
}

@media (prefers-color-scheme: dark) {
    .rete-host :deep(.node .control input[readonly]) {
        border-color: var(--mw-color-border-strong);
        background: rgba(36, 95, 78, 0.34);
        color: var(--mw-color-text-primary);
    }
}

.rete-host :deep(svg path) {
    stroke: rgba(29, 92, 73, 0.64);
    stroke-width: 3px;
}

.rete-host :deep(svg path:hover) {
    stroke: var(--mw-color-primary-strong);
}

@media (prefers-reduced-motion: no-preference) {
    .rete-host :deep(.node),
    .rete-host :deep(.socket),
    .rete-host :deep(svg path) {
        transition:
            background-color 120ms ease,
            border-color 120ms ease,
            box-shadow 120ms ease,
            stroke 120ms ease;
    }
}

.canvas-fallback,
.canvas-empty {
    align-items: center;
    color: var(--mw-color-text-secondary);
    display: flex;
    justify-content: center;
    min-height: 160px;
    padding: 16px;
}

.node-strip {
    border-top: 1px solid var(--mw-color-border);
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 10px;
}

.node-chip {
    min-height: 44px;
    border: 1px solid var(--mw-color-border);
    border-radius: 6px;
    background: transparent;
    color: var(--mw-color-text-primary);
    cursor: pointer;
    font: inherit;
    padding: 0 10px;
    text-align: left;
}

.node-chip.active {
    border-color: var(--mw-color-primary);
    background: rgba(29, 92, 73, 0.08);
}

@media (prefers-color-scheme: dark) {
    .node-chip.active {
        background: rgba(36, 95, 78, 0.3);
    }
}

@media (max-width: 900px) {
    .rete-host,
    .node-strip,
    .canvas-toolbar {
        display: none;
    }
}
</style>
