<script setup lang="ts">
import { computed } from 'vue'

import type {
    StrategyPaletteNode,
    StrategySummary,
} from '../../types/strategyBuilder'

const props = defineProps<{
    strategies: StrategySummary[]
    palette: StrategyPaletteNode[]
    selectedSlug: string | null
    readOnly: boolean
    saving: boolean
    hasSelection: boolean
}>()

const emit = defineEmits<{
    select: [slug: string]
    create: []
    duplicate: []
    'add-node': [type: string]
}>()

const builtinStrategies = computed(() =>
    props.strategies.filter((strategy) => strategy.is_builtin),
)
const customStrategies = computed(() =>
    props.strategies.filter((strategy) => !strategy.is_builtin),
)
</script>

<template>
    <aside class="strategy-left-rail" aria-label="Strategy library">
        <div class="rail-header">
            <strong>Library</strong>
            <n-button size="small" tertiary @click="emit('create')">
                Blank
            </n-button>
        </div>

        <div class="strategy-group">
            <span class="rail-label">Built-ins</span>
            <button
                v-for="strategy in builtinStrategies"
                :key="strategy.slug"
                type="button"
                class="strategy-row"
                :class="{ active: strategy.slug === selectedSlug }"
                @click="emit('select', strategy.slug)"
            >
                <span>{{ strategy.name }}</span>
                <span class="strategy-row-meta">
                    Built-in · v{{ strategy.active_version || 1 }}
                </span>
            </button>
        </div>

        <div class="strategy-group">
            <span class="rail-label">Custom</span>
            <button
                v-for="strategy in customStrategies"
                :key="strategy.slug"
                type="button"
                class="strategy-row"
                :class="{ active: strategy.slug === selectedSlug }"
                @click="emit('select', strategy.slug)"
            >
                <span>{{ strategy.name }}</span>
                <span class="strategy-row-meta">
                    Custom · v{{ strategy.active_version || 1 }}
                </span>
            </button>
            <p v-if="!customStrategies.length" class="empty-copy">
                Duplicate a built-in or start with an empty strategy.
            </p>
        </div>

        <n-button
            type="primary"
            secondary
            block
            :disabled="!hasSelection || saving"
            @click="emit('duplicate')"
        >
            Duplicate selected
        </n-button>

        <div class="strategy-group palette-group">
            <span class="rail-label">Node palette</span>
            <button
                v-for="node in palette"
                :key="node.type"
                type="button"
                class="palette-row"
                :disabled="readOnly"
                @click="emit('add-node', node.type)"
            >
                <span>{{ node.label }}</span>
                <small>{{ node.category }}</small>
            </button>
        </div>
    </aside>
</template>

<style scoped>
.strategy-left-rail {
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-sm, 6px);
    background: var(--mw-color-surface-panel);
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
}

.rail-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
}

.strategy-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.rail-label {
    color: var(--mw-color-text-secondary);
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
}

.strategy-row,
.palette-row {
    min-height: 44px;
    border: 1px solid var(--mw-color-border);
    border-radius: 6px;
    background: transparent;
    color: var(--mw-color-text-primary);
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 2px;
    font: inherit;
    padding: 8px 10px;
    text-align: left;
}

.strategy-row.active {
    border-color: var(--mw-color-primary);
    background: rgba(29, 92, 73, 0.08);
}

.strategy-row-meta,
.palette-row small,
.empty-copy {
    color: var(--mw-color-text-secondary);
    font-size: 0.82rem;
}

@media (prefers-color-scheme: dark) {
    .strategy-row.active {
        background: rgba(36, 95, 78, 0.3);
    }
}

@media (max-width: 900px) {
    .palette-group {
        display: none;
    }
}
</style>
