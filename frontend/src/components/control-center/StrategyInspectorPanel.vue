<script setup lang="ts">
import { computed } from 'vue'

import {
    formatStrategyParam,
    indicatorUsesSample,
    isPrimitiveStrategyParam,
    isStrategyValueNode,
    normalizeComparisonPort,
    strategyNodeTitle,
} from '../../helpers/strategyBuilderGraph'
import type {
    StrategyDetail,
    StrategyNode,
    StrategyValidation,
} from '../../types/strategyBuilder'

const props = defineProps<{
    detail: StrategyDetail | null
    selectedNode: StrategyNode | null
    validation: StrategyValidation
    readOnly: boolean
}>()

const emit = defineEmits<{
    validate: []
    'set-decision': [nodeId: string]
    'connect-decision': []
    'update-indicator': [value: string | number | null]
    'update-param': [key: string, value: string]
    'update-param-value': [key: string, value: unknown]
    'update-input': [port: string, sourceId: string | number | null]
}>()

const draftName = defineModel<string>('draftName', { required: true })
const draftDescription = defineModel<string>('draftDescription', {
    required: true,
})

const comparisonOperatorOptions = [
    { label: 'greater than', value: 'greater_than' },
    { label: 'less than', value: 'less_than' },
    { label: 'greater or equal', value: 'greater_or_equal' },
    { label: 'less or equal', value: 'less_or_equal' },
    { label: 'equals', value: 'equals' },
    { label: 'not equals', value: 'not_equals' },
]

const indicatorOptions = [
    { label: 'EMA', value: 'ema' },
    { label: 'RSI', value: 'rsi' },
    { label: 'Bollinger upper', value: 'bollinger_upper' },
    { label: 'Bollinger middle', value: 'bollinger_middle' },
    { label: 'Bollinger lower', value: 'bollinger_lower' },
    { label: 'Bollinger bandwidth %', value: 'bollinger_bandwidth' },
    { label: 'MACD line', value: 'macd_line' },
    { label: 'MACD signal', value: 'macd_signal' },
    { label: 'MACD histogram', value: 'macd_histogram' },
]

const indicatorLengthOptions = [
    { label: '9', value: 9 },
    { label: '14', value: 14 },
    { label: '20', value: 20 },
    { label: '21', value: 21 },
    { label: '50', value: 50 },
    { label: '100', value: 100 },
    { label: '200', value: 200 },
]

const indicatorSampleOptions = [
    { label: 'current', value: 'current' },
    { label: 'previous', value: 'previous' },
    { label: 'two back', value: 'two_back' },
]

const selectedNodeDocumentation = computed(() => {
    const nodeType = props.selectedNode?.type
    if (!nodeType) {
        return null
    }
    return (
        props.detail?.palette.find((item) => item.type === nodeType)
            ?.documentation_url ?? null
    )
})

const valueNodeOptions = computed(() => {
    const detail = props.detail
    const currentId = props.selectedNode?.id
    if (!detail) {
        return []
    }
    return detail.ir.nodes
        .filter(
            (node) =>
                node.id !== currentId &&
                isStrategyValueNode(node),
        )
        .map((node) => ({
            label: strategyNodeTitle(node, detail.ir),
            value: node.id,
        }))
})

function nodeTitle(node: StrategyNode): string {
    return props.detail
        ? strategyNodeTitle(node, props.detail.ir)
        : node.label || node.type
}

function isComparisonOperatorParam(key: string): boolean {
    return props.selectedNode?.type === 'comparison' && key === 'comparison'
}

function isGenericParamVisible(key: string, value: unknown): boolean {
    if (
        props.selectedNode?.type === 'indicator' &&
        ['indicator', 'length', 'sample'].includes(key)
    ) {
        return false
    }
    return isPrimitiveStrategyParam(value)
}

function indicatorUsesLength(node: StrategyNode | null): boolean {
    const indicator = String(node?.params?.indicator ?? '')
    return (
        indicator === 'ema' ||
        indicator === 'rsi' ||
        indicator.startsWith('bollinger_')
    )
}

function selectedInputSource(port: string): string | null {
    const detail = props.detail
    const node = props.selectedNode
    if (!detail || !node) {
        return null
    }
    const canonicalPort = normalizeComparisonPort(port)
    const connection = detail.ir.connections.find((item) => {
        const target = String(item.target ?? item.targetNode ?? '')
        const targetInput = normalizeComparisonPort(
            String(
                item.target_input ??
                    item.targetInput ??
                    item.input ??
                    '',
            ),
        )
        return target === node.id && targetInput === canonicalPort
    })
    return connection
        ? String(connection.source ?? connection.sourceNode ?? '')
        : null
}
</script>

<template>
    <aside class="strategy-right-rail" aria-label="Strategy inspector">
        <section class="inspector-panel">
            <h4>Inspector</h4>
            <template v-if="detail">
                <label>
                    Strategy name
                    <n-input
                        v-model:value="draftName"
                        :disabled="readOnly"
                        @blur="emit('validate')"
                    />
                </label>
                <label>
                    Description
                    <n-input
                        v-model:value="draftDescription"
                        type="textarea"
                        :autosize="{ minRows: 2, maxRows: 4 }"
                        :disabled="readOnly"
                        @blur="emit('validate')"
                    />
                </label>

                <div v-if="selectedNode" class="node-inspector">
                    <div class="node-inspector-header">
                        <strong>{{ nodeTitle(selectedNode) }}</strong>
                        <n-button
                            size="small"
                            tertiary
                            :disabled="readOnly"
                            @click="emit('set-decision', selectedNode.id)"
                        >
                            Use as decision
                        </n-button>
                        <n-button
                            size="small"
                            tertiary
                            :disabled="
                                readOnly ||
                                !detail.ir.root ||
                                selectedNode.id === detail.ir.root
                            "
                            @click="emit('connect-decision')"
                        >
                            Connect to decision
                        </n-button>
                    </div>
                    <a
                        v-if="selectedNodeDocumentation"
                        class="node-doc-link"
                        :href="selectedNodeDocumentation"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        Open node documentation
                    </a>
                    <div
                        v-if="selectedNode.type === 'indicator'"
                        class="connection-editor"
                    >
                        <strong>Indicator attributes</strong>
                        <label>
                            Indicator
                            <n-select
                                :value="String(selectedNode.params?.indicator ?? 'ema')"
                                :options="indicatorOptions"
                                :disabled="readOnly"
                                @update:value="emit('update-indicator', $event)"
                            />
                        </label>
                        <label v-if="indicatorUsesLength(selectedNode)">
                            Length
                            <n-select
                                :value="Number(selectedNode.params?.length ?? 20)"
                                :options="indicatorLengthOptions"
                                :disabled="readOnly"
                                @update:value="
                                    emit('update-param-value', 'length', $event)
                                "
                            />
                        </label>
                        <label v-if="indicatorUsesSample(selectedNode)">
                            Sample
                            <n-select
                                :value="String(selectedNode.params?.sample ?? 'current')"
                                :options="indicatorSampleOptions"
                                :disabled="readOnly"
                                @update:value="
                                    emit('update-param-value', 'sample', $event)
                                "
                            />
                        </label>
                    </div>
                    <label
                        v-for="(value, key) in selectedNode.params"
                        v-show="isGenericParamVisible(String(key), value)"
                        :key="key"
                    >
                        {{ key }}
                        <n-select
                            v-if="isComparisonOperatorParam(String(key))"
                            :value="String(value)"
                            :options="comparisonOperatorOptions"
                            :disabled="readOnly"
                            @update:value="
                                emit('update-param-value', String(key), $event)
                            "
                        />
                        <n-input
                            v-else
                            :value="formatStrategyParam(value)"
                            type="text"
                            :disabled="readOnly"
                            @update:value="
                                emit('update-param', String(key), $event)
                            "
                        />
                    </label>
                    <div
                        v-if="selectedNode.type === 'comparison'"
                        class="connection-editor"
                    >
                        <strong>Comparison inputs</strong>
                        <label>
                            value1
                            <n-select
                                :value="selectedInputSource('value1')"
                                :options="valueNodeOptions"
                                clearable
                                :disabled="readOnly"
                                @update:value="
                                    emit('update-input', 'value1', $event)
                                "
                            />
                        </label>
                        <label>
                            value2
                            <n-select
                                :value="selectedInputSource('value2')"
                                :options="valueNodeOptions"
                                clearable
                                :disabled="readOnly"
                                @update:value="
                                    emit('update-input', 'value2', $event)
                                "
                            />
                        </label>
                    </div>
                    <div
                        v-if="selectedNode.type === 'fresh_signal_state'"
                        class="connection-editor"
                    >
                        <strong>Tracked signal values</strong>
                        <p class="empty-copy">
                            Connect one close price node and one indicator
                            configured to EMA. Freshness is checked only after
                            upstream conditions pass.
                        </p>
                    </div>
                </div>
            </template>
            <p v-else class="empty-copy">No graph selected.</p>
        </section>

        <section class="validation-panel" aria-live="polite">
            <h4>Validation</h4>
            <p class="explanation">
                {{
                    detail?.explanation ||
                    'Select a graph to review history, hooks, and blocking errors.'
                }}
            </p>
            <div class="validation-item">
                <strong>Required history</strong>
                <span>
                    {{
                        validation.required_history?.label ||
                        'No graph selected'
                    }}
                </span>
            </div>
            <div class="validation-list">
                <strong>Blocking errors</strong>
                <p
                    v-if="!validation.blocking_errors?.length"
                    class="empty-copy"
                >
                    None
                </p>
                <p
                    v-for="error in validation.blocking_errors"
                    :key="`${error.group}-${error.message}`"
                    class="validation-error"
                >
                    {{ error.group }}: {{ error.message }}
                </p>
            </div>
            <div class="validation-list">
                <strong>Hook readiness</strong>
                <p
                    v-for="hook in validation.hook_readiness ?? []"
                    :key="hook.name"
                    :class="hook.ready ? 'hook-ready' : 'validation-error'"
                >
                    {{ hook.name }} · {{ hook.message }}
                </p>
            </div>
        </section>
    </aside>
</template>

<style scoped>
.strategy-right-rail {
    border-top: 1px solid var(--mw-color-border);
    display: grid;
    grid-template-columns: repeat(2, minmax(280px, 1fr));
    align-items: start;
    gap: 12px;
    padding: 12px;
}

.inspector-panel,
.validation-panel,
.node-inspector,
.connection-editor,
.validation-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.connection-editor {
    border-top: 1px solid var(--mw-color-border);
    margin-top: 4px;
    padding-top: 8px;
}

.node-inspector-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
}

.node-doc-link {
    color: var(--mw-color-primary);
    font-size: 0.82rem;
    font-weight: 700;
    text-decoration: none;
}

.node-doc-link:hover,
.node-doc-link:focus-visible {
    text-decoration: underline;
}

.inspector-panel h4,
.validation-panel h4 {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    margin: 0;
}

label {
    color: var(--mw-color-text-secondary);
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 0.82rem;
    font-weight: 700;
}

.validation-item {
    border: 1px solid var(--mw-color-border);
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px;
}

.empty-copy,
.explanation {
    color: var(--mw-color-text-secondary);
    font-size: 0.82rem;
}

.validation-error {
    color: var(--mw-color-error);
}

.hook-ready {
    color: var(--mw-color-success);
}

@media (max-width: 900px) {
    .strategy-right-rail {
        grid-template-columns: 1fr;
    }

    .inspector-panel {
        display: none;
    }
}
</style>
