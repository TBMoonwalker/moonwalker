<script setup lang="ts">
import axios from 'axios'
import { useDialog } from 'naive-ui'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { AreaExtensions, AreaPlugin } from 'rete-area-plugin'
import { ClassicPreset, NodeEditor, type GetSchemes } from 'rete'
import { ConnectionPlugin, Presets as ConnectionPresets } from 'rete-connection-plugin'
import { Presets, VuePlugin, type VueArea2D } from 'rete-vue-plugin'

import { buildMoonwalkerApiUrl } from '../../helpers/configEditorDefaults'
import { extractApiErrorMessage } from '../../helpers/apiErrors'

type StrategyKind = 'builtin' | 'custom'

interface StrategySummary {
    slug: string
    name: string
    description: string
    kind: StrategyKind
    is_builtin: boolean
    duplicated_from: string | null
    active_version: number | null
    draft_version: number
    lock_version: number
    validation_status: string
    available: boolean
    missing_hooks: string[]
    required_history?: { label?: string; candles?: number }
}

interface StrategyNode {
    id: string
    type: string
    label?: string
    params?: Record<string, unknown>
    position?: { x?: number; y?: number }
}

interface StrategyIr {
    schema_version: number
    slug: string
    name: string
    description?: string
    kind: StrategyKind
    root: string
    nodes: StrategyNode[]
    connections: Array<Record<string, unknown>>
    metadata?: Record<string, unknown>
}

interface StrategyValidation {
    status: string
    blocking_errors?: Array<{ group: string; message: string }>
    warnings?: Array<{ group: string; message: string }>
    required_history?: { label?: string; candles?: number }
    hook_readiness?: Array<{ name: string; ready: boolean; message: string }>
}

interface StrategyDetail extends StrategySummary {
    ir: StrategyIr
    validation: StrategyValidation
    explanation: string
    palette: Array<{
        type: string
        label: string
        category: string
        description: string
        params: Record<string, unknown>
        documentation_url?: string
    }>
}

interface StrategyListPayload {
    strategies: StrategySummary[]
    palette: StrategyDetail['palette']
}

type ReteNode = ClassicPreset.Node
type ReteConnection = ClassicPreset.Connection<ReteNode, ReteNode>
type Schemes = GetSchemes<ReteNode, ReteConnection>
type AreaExtra = VueArea2D<Schemes>

const dialog = useDialog()
const strategies = ref<StrategySummary[]>([])
const palette = ref<StrategyDetail['palette']>([])
const selectedSlug = ref<string | null>(null)
const selectedDetail = ref<StrategyDetail | null>(null)
const selectedNodeId = ref<string | null>(null)
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const saveMessage = ref<string | null>(null)
const draftName = ref('')
const draftDescription = ref('')
const draftConflict = ref(false)
const reteHost = ref<HTMLElement | null>(null)
const reteReady = ref(false)
const reteError = ref<string | null>(null)
let reteTeardown: (() => void) | null = null
const RETE_FIT_SCALE = 0.98

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

const comparisonLabelByValue: Record<string, string> = {
    equals: 'equals',
    greater_or_equal: 'greater or equal',
    greater_than: 'greater than',
    less_or_equal: 'less or equal',
    less_than: 'less than',
    not_equals: 'not equals',
}

const builtinStrategies = computed(() =>
    strategies.value.filter((strategy) => strategy.is_builtin),
)
const customStrategies = computed(() =>
    strategies.value.filter((strategy) => !strategy.is_builtin),
)
const isReadOnly = computed(() => Boolean(selectedDetail.value?.is_builtin))
const selectedNode = computed(() => {
    const nodes = selectedDetail.value?.ir.nodes ?? []
    return nodes.find((node) => node.id === selectedNodeId.value) ?? nodes[0] ?? null
})
const selectedNodeDocumentation = computed(() => {
    const nodeType = selectedNode.value?.type
    if (!nodeType) {
        return null
    }
    return palette.value.find((item) => item.type === nodeType)?.documentation_url ?? null
})
const valueNodeOptions = computed(() => {
    const currentId = selectedNode.value?.id
    return (selectedDetail.value?.ir.nodes ?? [])
        .filter(
            (node) =>
                node.id !== currentId &&
                isValueNode(node),
        )
        .map((node) => ({
            label: nodeTitle(node),
            value: node.id,
        }))
})
const validation = computed(
    () => selectedDetail.value?.validation ?? ({ status: 'empty' } as StrategyValidation),
)
const canSave = computed(
    () =>
        Boolean(selectedDetail.value) &&
        !isReadOnly.value &&
        validation.value.status === 'valid' &&
        !saving.value,
)
const mobileReviewOnly = computed(() => false)

onMounted(async () => {
    await loadStrategies()
})

onUnmounted(() => {
    destroyRete()
})

watch(selectedDetail, async () => {
    const detail = selectedDetail.value
    draftName.value = detail?.ir.name ?? ''
    draftDescription.value = detail?.ir.description ?? ''
    const currentNodeStillExists = detail?.ir.nodes?.some(
        (node) => node.id === selectedNodeId.value,
    )
    if (!currentNodeStillExists) {
        selectedNodeId.value = detail?.ir.root ?? detail?.ir.nodes?.[0]?.id ?? null
    }
    await renderReteGraph()
})

async function loadStrategies(selectSlug?: string): Promise<void> {
    loading.value = true
    errorMessage.value = null
    try {
        const response = await axios.get<StrategyListPayload>(
            buildMoonwalkerApiUrl('/strategies'),
        )
        strategies.value = response.data.strategies
        palette.value = response.data.palette
        const nextSlug =
            selectSlug ??
            selectedSlug.value ??
            response.data.strategies.find((strategy) => strategy.is_builtin)?.slug ??
            response.data.strategies[0]?.slug ??
            null
        if (nextSlug) {
            await selectStrategy(nextSlug)
        }
    } catch (error) {
        errorMessage.value = extractApiErrorMessage(
            error,
            'Strategy library could not be loaded.',
        )
    } finally {
        loading.value = false
    }
}

async function selectStrategy(slug: string): Promise<void> {
    selectedSlug.value = slug
    saveMessage.value = null
    draftConflict.value = false
    try {
        const response = await axios.get<StrategyDetail>(
            buildMoonwalkerApiUrl(`/strategies/${slug}`),
        )
        selectedDetail.value = response.data
        if (response.data.palette?.length) {
            palette.value = response.data.palette
        }
    } catch (error) {
        errorMessage.value = extractApiErrorMessage(
            error,
            'Strategy could not be opened.',
        )
    }
}

async function duplicateSelected(): Promise<void> {
    const detail = selectedDetail.value
    if (!detail || saving.value) {
        return
    }
    saving.value = true
    saveMessage.value = null
    try {
        const response = await axios.post<StrategyDetail>(
            buildMoonwalkerApiUrl('/strategies/duplicate'),
            {
                source_slug: detail.slug,
                name: `${detail.name} copy`,
            },
        )
        await loadStrategies(response.data.slug)
        saveMessage.value = 'Custom copy created. Edit the inspector, then save a new active version.'
    } catch (error) {
        errorMessage.value = extractApiErrorMessage(
            error,
            'Strategy could not be duplicated.',
        )
    } finally {
        saving.value = false
    }
}

async function createBlank(): Promise<void> {
    if (saving.value) {
        return
    }
    saving.value = true
    saveMessage.value = null
    try {
        const response = await axios.post<StrategyDetail>(
            buildMoonwalkerApiUrl('/strategies'),
            { name: 'Custom strategy' },
        )
        await loadStrategies(response.data.slug)
        saveMessage.value = 'Empty custom strategy created. Add graph nodes, then choose a decision node.'
    } catch (error) {
        errorMessage.value = extractApiErrorMessage(
            error,
            'Strategy could not be created.',
        )
    } finally {
        saving.value = false
    }
}

async function deleteSelected(): Promise<void> {
    const detail = selectedDetail.value
    if (!detail || detail.is_builtin || saving.value) {
        return
    }
    const confirmed = await new Promise<boolean>((resolve) => {
        dialog.warning({
            title: 'Delete Strategy',
            content: `Delete custom strategy "${detail.name}"? This cannot be undone.`,
            positiveText: 'Delete',
            negativeText: 'Cancel',
            onPositiveClick: () => resolve(true),
            onNegativeClick: () => resolve(false),
        })
    })
    if (!confirmed) {
        return
    }
    saving.value = true
    saveMessage.value = null
    try {
        await axios.delete(buildMoonwalkerApiUrl(`/strategies/${detail.slug}`))
        selectedSlug.value = null
        selectedDetail.value = null
        await loadStrategies()
        saveMessage.value = 'Custom strategy deleted.'
    } catch (error) {
        errorMessage.value = extractApiErrorMessage(
            error,
            'Strategy could not be deleted.',
        )
    } finally {
        saving.value = false
    }
}

async function validateDraft(): Promise<void> {
    const detail = selectedDetail.value
    if (!detail) {
        return
    }
    applyDraftText()
    try {
        const response = await axios.post<StrategyValidation>(
            buildMoonwalkerApiUrl('/strategies/validate'),
            { ir: detail.ir },
        )
        detail.validation = response.data
    } catch (error) {
        errorMessage.value = extractApiErrorMessage(
            error,
            'Strategy validation failed.',
        )
    }
}

async function saveActiveVersion(): Promise<void> {
    const detail = selectedDetail.value
    if (!detail || !canSave.value) {
        return
    }
    saving.value = true
    saveMessage.value = null
    draftConflict.value = false
    applyDraftText()
    try {
        const response = await axios.put<StrategyDetail>(
            buildMoonwalkerApiUrl(`/strategies/${detail.slug}`),
            {
                ir: detail.ir,
                base_lock_version: detail.lock_version,
            },
        )
        selectedDetail.value = response.data
        await loadStrategies(response.data.slug)
        saveMessage.value = `Saved active version v${response.data.active_version}.`
    } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 409) {
            draftConflict.value = true
        }
        errorMessage.value = extractApiErrorMessage(
            error,
            'Strategy could not be saved.',
        )
    } finally {
        saving.value = false
    }
}

function applyDraftText(): void {
    const detail = selectedDetail.value
    if (!detail || isReadOnly.value) {
        return
    }
    detail.ir.name = draftName.value.trim() || detail.name
    detail.ir.description = draftDescription.value.trim()
}

function updateNodeParam(key: string, value: string): void {
    const detail = selectedDetail.value
    const node = selectedNode.value
    if (!detail || !node || isReadOnly.value) {
        return
    }
    node.params = {
        ...(node.params ?? {}),
        [key]: coerceParamValue(value),
    }
    void validateDraft()
    void renderReteGraph()
}

function updateNodeParamValue(key: string, value: unknown): void {
    const detail = selectedDetail.value
    const node = selectedNode.value
    if (!detail || !node || isReadOnly.value || value === null) {
        return
    }
    node.params = {
        ...(node.params ?? {}),
        [key]: value,
    }
    void validateDraft()
    void renderReteGraph()
}

function coerceParamValue(value: string): unknown {
    const trimmed = value.trim()
    if (/^-?\d+(\.\d+)?$/.test(trimmed)) {
        return Number(trimmed)
    }
    if (trimmed === 'true') {
        return true
    }
    if (trimmed === 'false') {
        return false
    }
    return value
}

function formatParamValue(value: unknown): string {
    if (Array.isArray(value) || (value && typeof value === 'object')) {
        return 'Configured by graph connections'
    }
    return String(value)
}

function isPrimitiveParam(value: unknown): boolean {
    return !Array.isArray(value) && (!value || typeof value !== 'object')
}

function isComparisonOperatorParam(key: string): boolean {
    return selectedNode.value?.type === 'comparison' && key === 'comparison'
}

function isGenericParamVisible(key: string, value: unknown): boolean {
    if (selectedNode.value?.type === 'indicator' && ['indicator', 'length', 'sample'].includes(key)) {
        return false
    }
    return isPrimitiveParam(value)
}

function indicatorUsesLength(node: StrategyNode | null): boolean {
    const indicator = String(node?.params?.indicator ?? '')
    return indicator === 'ema' || indicator === 'rsi' || indicator.startsWith('bollinger_')
}

function indicatorUsesSample(node: StrategyNode | null): boolean {
    return ['ema', 'rsi'].includes(String(node?.params?.indicator ?? '')) ||
        String(node?.params?.indicator ?? '').startsWith('bollinger_') ||
        String(node?.params?.indicator ?? '').startsWith('macd_')
}

function updateIndicatorSelection(value: string | number | null): void {
    const detail = selectedDetail.value
    const node = selectedNode.value
    if (!detail || !node || isReadOnly.value || value === null) {
        return
    }
    const indicator = String(value)
    const nextParams: Record<string, unknown> = {
        ...(node.params ?? {}),
        indicator,
    }
    if (indicator === 'ema' || indicator === 'rsi' || indicator.startsWith('bollinger_')) {
        delete nextParams.fast_period
        delete nextParams.slow_period
        delete nextParams.signal_period
        nextParams.length = Number(nextParams.length || (indicator === 'rsi' ? 14 : 20))
        nextParams.sample = String(nextParams.sample || 'current')
        if (indicator.startsWith('bollinger_')) {
            nextParams.standard_deviations = Number(nextParams.standard_deviations || 2)
        } else {
            delete nextParams.standard_deviations
        }
    } else if (indicator.startsWith('macd_')) {
        delete nextParams.length
        delete nextParams.standard_deviations
        nextParams.sample = String(nextParams.sample || 'current')
        nextParams.fast_period = Number(nextParams.fast_period || 12)
        nextParams.slow_period = Number(nextParams.slow_period || 26)
        nextParams.signal_period = Number(nextParams.signal_period || 9)
    } else {
        delete nextParams.length
        delete nextParams.sample
        delete nextParams.standard_deviations
        delete nextParams.fast_period
        delete nextParams.slow_period
        delete nextParams.signal_period
    }
    node.params = nextParams
    void validateDraft()
    void renderReteGraph()
}

function isValueNode(node: StrategyNode): boolean {
    return [
        'close_price',
        'low_price',
        'high_price',
        'constant_value',
        'indicator',
    ].includes(node.type)
}

function nodeTitle(node: StrategyNode): string {
    if (node.type === 'comparison') {
        const value1 = comparisonInputTitle(node.id, 'value1')
        const value2 = comparisonInputTitle(node.id, 'value2')
        const comparison = String(node.params?.comparison ?? 'greater_than')
        const operator = comparisonLabelByValue[comparison] ?? comparison
        if (value1 && value2) {
            return `${value1} ${operator} ${value2}`
        }
    }
    if (node.type === 'indicator') {
        const indicator = String(node.params?.indicator ?? 'indicator')
        const length = node.params?.length ? ` ${node.params.length}` : ''
        const sample = indicatorUsesSample(node) ? ` ${sampleLabel(node.params?.sample)}` : ''
        return `${indicatorLabel(indicator)}${length}${sample}`
    }
    if (node.type === 'close_price') {
        return `Close ${sampleLabel(node.params?.sample)}`
    }
    if (node.type === 'low_price') {
        return `Low ${sampleLabel(node.params?.sample)}`
    }
    if (node.type === 'high_price') {
        return `High ${sampleLabel(node.params?.sample)}`
    }
    if (node.type === 'constant_value') {
        return String(node.params?.value ?? 'Constant value')
    }
    if (node.type === 'swing_low_state') {
        return 'Current swing low greater than stored swing low'
    }
    return node.label || node.type
}

function comparisonInputTitle(nodeId: string, port: string): string | null {
    const detail = selectedDetail.value
    if (!detail) {
        return null
    }
    const canonicalPort = normalizeComparisonPort(port)
    const connection = detail.ir.connections.find((item) => {
        const target = String(item.target ?? item.targetNode ?? '')
        const targetInput = normalizeComparisonPort(
            String(item.target_input ?? item.targetInput ?? item.input ?? ''),
        )
        return target === nodeId && targetInput === canonicalPort
    })
    const sourceId = connection ? String(connection.source ?? connection.sourceNode ?? '') : ''
    const source = detail.ir.nodes.find((item) => item.id === sourceId)
    return source ? nodeTitle(source) : null
}

function sampleLabel(value: unknown): string {
    const sample = String(value ?? 'current')
    if (sample === 'previous') {
        return 'previous'
    }
    if (sample === 'two_back') {
        return 'two back'
    }
    return 'current'
}

function indicatorLabel(value: string): string {
    const labels: Record<string, string> = {
        ema: 'EMA',
        rsi: 'RSI',
        bollinger_upper: 'Bollinger upper',
        bollinger_middle: 'Bollinger middle',
        bollinger_lower: 'Bollinger lower',
        bollinger_bandwidth: 'Bollinger bandwidth %',
        macd_line: 'MACD line',
        macd_signal: 'MACD signal',
        macd_histogram: 'MACD histogram',
    }
    return labels[value] ?? value
}

function addNodeFromPalette(type: string): void {
    const detail = selectedDetail.value
    const paletteNode = palette.value.find((item) => item.type === type)
    if (!detail || !paletteNode || isReadOnly.value) {
        return
    }
    const nextIndex = detail.ir.nodes.length + 1
    const node: StrategyNode = {
        id: `${type}_${nextIndex}`,
        type,
        label: paletteNode.label,
        params: { ...paletteNode.params },
        position: { x: 220 + nextIndex * 32, y: 90 + nextIndex * 38 },
    }
    detail.ir.nodes.push(node)
    if (!detail.ir.root) {
        detail.ir.root = node.id
    }
    selectedNodeId.value = node.id
    void validateDraft()
    void renderReteGraph()
}

function autoAlignGraph(): void {
    const detail = selectedDetail.value
    if (!detail || !detail.ir.nodes.length) {
        return
    }
    const nodes = detail.ir.nodes
    const nodeById = new Map(nodes.map((node) => [node.id, node]))
    const incomingByTarget = new Map<string, string[]>()
    for (const connection of detail.ir.connections ?? []) {
        const source = String(connection.source ?? connection.sourceNode ?? '')
        const target = String(connection.target ?? connection.targetNode ?? '')
        if (!nodeById.has(source) || !nodeById.has(target)) {
            continue
        }
        const incoming = incomingByTarget.get(target) ?? []
        incoming.push(source)
        incomingByTarget.set(target, incoming)
    }

    const depthById = new Map<string, number>()
    const visiting = new Set<string>()
    const depthFor = (nodeId: string): number => {
        const cached = depthById.get(nodeId)
        if (cached !== undefined) {
            return cached
        }
        if (visiting.has(nodeId)) {
            return 0
        }
        visiting.add(nodeId)
        const sources = incomingByTarget.get(nodeId) ?? []
        const depth = sources.length
            ? Math.max(...sources.map((sourceId) => depthFor(sourceId))) + 1
            : 0
        visiting.delete(nodeId)
        depthById.set(nodeId, depth)
        return depth
    }

    for (const node of nodes) {
        depthFor(node.id)
    }

    const columns = new Map<number, StrategyNode[]>()
    for (const node of nodes) {
        const depth = depthById.get(node.id) ?? 0
        const column = columns.get(depth) ?? []
        column.push(node)
        columns.set(depth, column)
    }

    const typeWeight = (node: StrategyNode): number => {
        if (isValueNode(node)) {
            return 0
        }
        if (node.type === 'comparison') {
            return 1
        }
        if (node.type.endsWith('_state')) {
            return 2
        }
        if (['all', 'any'].includes(node.type)) {
            return 3
        }
        return 4
    }
    const sortedDepths = [...columns.keys()].sort((first, second) => first - second)
    const maxColumnSize = Math.max(...[...columns.values()].map((column) => column.length))
    const startX = 80
    const startY = 72
    const columnGap = 300
    const rowGap = 128

    for (const depth of sortedDepths) {
        const column = columns.get(depth) ?? []
        column.sort((first, second) => {
            const weightDelta = typeWeight(first) - typeWeight(second)
            if (weightDelta !== 0) {
                return weightDelta
            }
            return nodeTitle(first).localeCompare(nodeTitle(second))
        })
        const yOffset = ((maxColumnSize - column.length) * rowGap) / 2
        column.forEach((node, index) => {
            node.position = {
                x: startX + depth * columnGap,
                y: startY + yOffset + index * rowGap,
            }
        })
    }

    void renderReteGraph()
}

function connectSelectedToDecision(): void {
    const detail = selectedDetail.value
    const node = selectedNode.value
    if (!detail || !node || isReadOnly.value || !detail.ir.root) {
        return
    }
    if (node.id === detail.ir.root) {
        return
    }
    const exists = detail.ir.connections.some(
        (connection) =>
            String(connection.source ?? '') === node.id &&
            String(connection.target ?? '') === detail.ir.root,
    )
    if (!exists) {
        detail.ir.connections.push({ source: node.id, target: detail.ir.root })
    }
    void validateDraft()
    void renderReteGraph()
}

function normalizeComparisonPort(port: string): string {
    if (port === 'left') {
        return 'value1'
    }
    if (port === 'right') {
        return 'value2'
    }
    return port
}

function selectedInputSource(port: string): string | null {
    const detail = selectedDetail.value
    const node = selectedNode.value
    if (!detail || !node) {
        return null
    }
    const canonicalPort = normalizeComparisonPort(port)
    const connection = detail.ir.connections.find((item) => {
        const target = String(item.target ?? item.targetNode ?? '')
        const targetInput = normalizeComparisonPort(
            String(item.target_input ?? item.targetInput ?? item.input ?? ''),
        )
        return target === node.id && targetInput === canonicalPort
    })
    return connection ? String(connection.source ?? connection.sourceNode ?? '') : null
}

function updateSelectedInput(port: string, sourceId: string | number | null): void {
    const detail = selectedDetail.value
    const node = selectedNode.value
    if (!detail || !node || isReadOnly.value) {
        return
    }
    const canonicalPort = normalizeComparisonPort(port)
    detail.ir.connections = detail.ir.connections.filter((item) => {
        const target = String(item.target ?? item.targetNode ?? '')
        const targetInput = normalizeComparisonPort(
            String(item.target_input ?? item.targetInput ?? item.input ?? ''),
        )
        return !(target === node.id && targetInput === canonicalPort)
    })
    if (sourceId) {
        detail.ir.connections.push({
            source: String(sourceId),
            target: node.id,
            target_input: canonicalPort,
        })
    }
    void validateDraft()
    void renderReteGraph()
}

function setDecisionNode(nodeId: string): void {
    const detail = selectedDetail.value
    if (!detail || isReadOnly.value) {
        return
    }
    detail.ir.root = nodeId
    selectedNodeId.value = nodeId
    saveMessage.value = 'Decision node set.'
    void validateDraft()
    void renderReteGraph()
}

async function renderReteGraph(): Promise<void> {
    destroyRete()
    reteReady.value = false
    reteError.value = null
    const detail = selectedDetail.value
    if (!detail) {
        return
    }
    await nextTick()
    const host = reteHost.value
    if (!host) {
        return
    }
    try {
        const editor = new NodeEditor<Schemes>()
        const area = new AreaPlugin<Schemes, AreaExtra>(host)
        const connection = new ConnectionPlugin<Schemes, AreaExtra>()
        const render = new VuePlugin<Schemes, AreaExtra>()
        const socket = new ClassicPreset.Socket('signal')
        const graphIdByReteId = new Map<string, string>()
        area.addPipe((context) => {
            if (context.type === 'nodepicked') {
                const graphId = graphIdByReteId.get(String(context.data.id))
                if (graphId) {
                    selectedNodeId.value = graphId
                }
            }
            return context
        })
        render.addPreset(Presets.classic.setup())
        connection.addPreset(ConnectionPresets.classic.setup())
        editor.use(area)
        area.use(connection)
        area.use(render)

        const nodeMap = new Map<string, ReteNode>()
        const graphNodeById = new Map<string, StrategyNode>()
        for (const graphNode of detail.ir.nodes) {
            const reteNode = new ClassicPreset.Node(nodeTitle(graphNode))
            graphNodeById.set(graphNode.id, graphNode)
            if (graphNode.type === 'comparison') {
                reteNode.addInput('value1', new ClassicPreset.Input(socket, 'value1'))
                reteNode.addInput('value2', new ClassicPreset.Input(socket, 'value2'))
            } else if (!isValueNode(graphNode)) {
                reteNode.addInput('in', new ClassicPreset.Input(socket))
            }
            reteNode.addOutput('out', new ClassicPreset.Output(socket))
            reteNode.addControl(
                'type',
                new ClassicPreset.InputControl('text', {
                    initial: graphNode.type,
                    readonly: true,
                }),
            )
            await editor.addNode(reteNode)
            await area.translate(reteNode.id, {
                x: Number(graphNode.position?.x ?? 80),
                y: Number(graphNode.position?.y ?? 80),
            })
            nodeMap.set(graphNode.id, reteNode)
            graphIdByReteId.set(reteNode.id, graphNode.id)
        }

        for (const graphConnection of detail.ir.connections ?? []) {
            const source = nodeMap.get(String(graphConnection.source ?? ''))
            const target = nodeMap.get(String(graphConnection.target ?? ''))
            const targetGraphNode = graphNodeById.get(String(graphConnection.target ?? ''))
            const requestedTargetPort = normalizeComparisonPort(
                String(graphConnection.target_input ?? ''),
            )
            const targetPort =
                targetGraphNode?.type === 'comparison'
                    ? requestedTargetPort === 'value2'
                        ? 'value2'
                        : 'value1'
                    : 'in'
            if (source && target) {
                await editor.addConnection(
                    new ClassicPreset.Connection(source, 'out', target, targetPort),
                )
            }
        }

        AreaExtensions.simpleNodesOrder(area)
        const reteNodes = editor.getNodes()
        if (reteNodes.length) {
            await AreaExtensions.zoomAt(area, reteNodes, { scale: RETE_FIT_SCALE })
        }
        reteTeardown = () => {
            area.destroy()
            editor.clear()
        }
        reteReady.value = true
    } catch (error) {
        reteError.value =
            error instanceof Error ? error.message : 'Rete canvas could not render.'
    }
}

function destroyRete(): void {
    if (reteTeardown) {
        reteTeardown()
        reteTeardown = null
    }
}
</script>

<template>
    <section class="strategy-builder" aria-labelledby="strategy-builder-title">
        <div class="strategy-status-bar">
            <div>
                <h3 id="strategy-builder-title">Strategy Builder</h3>
                <p>
                    {{ selectedDetail?.name || 'Select a strategy' }}
                    <span v-if="selectedDetail?.active_version" class="mono">
                        v{{ selectedDetail.active_version }}
                    </span>
                </p>
            </div>
            <div class="status-actions">
                <n-tag
                    v-if="selectedDetail"
                    :type="isReadOnly ? 'default' : 'success'"
                    size="small"
                >
                    {{ isReadOnly ? 'Built-in' : 'Custom' }}
                </n-tag>
                <n-tag
                    v-if="validation.status"
                    :type="validation.status === 'valid' ? 'success' : 'error'"
                    size="small"
                >
                    {{ validation.status }}
                </n-tag>
                <n-button
                    secondary
                    :disabled="!selectedDetail || saving"
                    @click="validateDraft"
                >
                    Validate
                </n-button>
                <n-button
                    type="primary"
                    :loading="saving"
                    :disabled="!canSave"
                    @click="saveActiveVersion"
                >
                    Save active version
                </n-button>
                <n-button
                    type="error"
                    secondary
                    :disabled="!selectedDetail || isReadOnly || saving"
                    @click="deleteSelected"
                >
                    Delete
                </n-button>
            </div>
        </div>

        <n-alert v-if="errorMessage" type="error" closable @close="errorMessage = null">
            {{ errorMessage }}
        </n-alert>
        <n-alert v-if="saveMessage" type="success" closable @close="saveMessage = null">
            {{ saveMessage }}
        </n-alert>
        <n-alert v-if="draftConflict" type="warning">
            This draft is stale. Reload the strategy before saving another active version.
        </n-alert>

        <div class="mobile-review-note">
            Graph editing is available on tablet and desktop. This screen keeps strategy
            review and selection readable on phones.
        </div>

        <n-spin :show="loading">
            <div class="strategy-layout" :class="{ 'review-only': mobileReviewOnly }">
                <aside class="strategy-left-rail" aria-label="Strategy library">
                    <div class="rail-header">
                        <strong>Library</strong>
                        <n-button size="small" tertiary @click="createBlank">
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
                            @click="selectStrategy(strategy.slug)"
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
                            @click="selectStrategy(strategy.slug)"
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
                        :disabled="!selectedDetail || saving"
                        @click="duplicateSelected"
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
                            :disabled="isReadOnly"
                            @click="addNodeFromPalette(node.type)"
                        >
                            <span>{{ node.label }}</span>
                            <small>{{ node.category }}</small>
                        </button>
                    </div>
                </aside>

                <div class="strategy-workbench">
                    <main class="strategy-canvas-shell" aria-label="Strategy graph">
                        <div v-if="!selectedDetail" class="canvas-empty">
                            Select a built-in strategy to preview its graph.
                        </div>
                        <template v-else>
                            <div class="canvas-toolbar">
                                <div>
                                    <span>
                                        {{ isReadOnly ? 'Read-only built-in preview' : 'Editable custom graph' }}
                                    </span>
                                    <span v-if="selectedDetail.duplicated_from" class="mono">
                                        from {{ selectedDetail.duplicated_from }}
                                    </span>
                                </div>
                                <n-button
                                    size="small"
                                    secondary
                                    :disabled="!selectedDetail.ir.nodes.length"
                                    @click="autoAlignGraph"
                                >
                                    Auto align
                                </n-button>
                            </div>
                            <div ref="reteHost" class="rete-host" aria-label="Rete graph canvas" />
                            <div
                                v-if="selectedDetail && !selectedDetail.ir.nodes.length"
                                class="canvas-fallback"
                                role="status"
                            >
                                This custom graph is empty. Add an indicator, logic, or
                                state node from the palette.
                            </div>
                            <div v-if="reteError" class="canvas-fallback" role="status">
                                {{ reteError }}
                            </div>
                            <div v-else-if="!reteReady" class="canvas-fallback" role="status">
                                Preparing graph canvas...
                            </div>
                            <div class="node-strip" aria-label="Graph nodes">
                                <button
                                    v-for="node in selectedDetail.ir.nodes"
                                    :key="node.id"
                                    type="button"
                                    class="node-chip"
                                    :class="{ active: node.id === selectedNodeId }"
                                    @click="selectedNodeId = node.id"
                                >
                                    {{ nodeTitle(node) }}
                                </button>
                            </div>
                        </template>
                    </main>

                    <aside class="strategy-right-rail" aria-label="Strategy inspector">
                        <section class="inspector-panel">
                            <h4>Inspector</h4>
                            <template v-if="selectedDetail">
                                <label>
                                    Strategy name
                                    <n-input
                                        v-model:value="draftName"
                                        :disabled="isReadOnly"
                                        @blur="validateDraft"
                                    />
                                </label>
                                <label>
                                    Description
                                    <n-input
                                        v-model:value="draftDescription"
                                        type="textarea"
                                        :autosize="{ minRows: 2, maxRows: 4 }"
                                        :disabled="isReadOnly"
                                        @blur="validateDraft"
                                    />
                                </label>

                                <div v-if="selectedNode" class="node-inspector">
                                    <div class="node-inspector-header">
                                        <strong>{{ nodeTitle(selectedNode) }}</strong>
                                        <n-button
                                            size="small"
                                            tertiary
                                            :disabled="isReadOnly"
                                            @click="setDecisionNode(selectedNode.id)"
                                        >
                                            Use as decision
                                        </n-button>
                                        <n-button
                                            size="small"
                                            tertiary
                                            :disabled="
                                                isReadOnly ||
                                                !selectedDetail.ir.root ||
                                                selectedNode.id === selectedDetail.ir.root
                                            "
                                            @click="connectSelectedToDecision"
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
                                                :disabled="isReadOnly"
                                                @update:value="updateIndicatorSelection"
                                            />
                                        </label>
                                        <label v-if="indicatorUsesLength(selectedNode)">
                                            Length
                                            <n-select
                                                :value="Number(selectedNode.params?.length ?? 20)"
                                                :options="indicatorLengthOptions"
                                                :disabled="isReadOnly"
                                                @update:value="updateNodeParamValue('length', $event)"
                                            />
                                        </label>
                                        <label v-if="indicatorUsesSample(selectedNode)">
                                            Sample
                                            <n-select
                                                :value="String(selectedNode.params?.sample ?? 'current')"
                                                :options="indicatorSampleOptions"
                                                :disabled="isReadOnly"
                                                @update:value="updateNodeParamValue('sample', $event)"
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
                                            :disabled="isReadOnly"
                                            @update:value="updateNodeParamValue(String(key), $event)"
                                        />
                                        <n-input
                                            v-else
                                            :value="formatParamValue(value)"
                                            type="text"
                                            :disabled="isReadOnly"
                                            @update:value="updateNodeParam(String(key), $event)"
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
                                                :disabled="isReadOnly"
                                                @update:value="updateSelectedInput('value1', $event)"
                                            />
                                        </label>
                                        <label>
                                            value2
                                            <n-select
                                                :value="selectedInputSource('value2')"
                                                :options="valueNodeOptions"
                                                clearable
                                                :disabled="isReadOnly"
                                                @update:value="updateSelectedInput('value2', $event)"
                                            />
                                        </label>
                                    </div>
                                    <div
                                        v-if="selectedNode.type === 'fresh_signal_state'"
                                        class="connection-editor"
                                    >
                                        <strong>Tracked signal values</strong>
                                        <p class="empty-copy">
                                            Connect one close price node and one indicator configured to EMA.
                                            Freshness is checked only after upstream conditions pass.
                                        </p>
                                    </div>
                                </div>
                            </template>
                            <p v-else class="empty-copy">No graph selected.</p>
                        </section>

                        <section class="validation-panel" aria-live="polite">
                            <h4>Validation</h4>
                            <p class="explanation">
                                {{ selectedDetail?.explanation || 'Select a graph to review history, hooks, and blocking errors.' }}
                            </p>
                            <div class="validation-item">
                                <strong>Required history</strong>
                                <span>{{ validation.required_history?.label || 'No graph selected' }}</span>
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
                                    v-for="hook in validation.hook_readiness"
                                    :key="hook.name"
                                    :class="hook.ready ? 'hook-ready' : 'validation-error'"
                                >
                                    {{ hook.name }} · {{ hook.message }}
                                </p>
                            </div>
                        </section>
                    </aside>
                </div>
            </div>
        </n-spin>
    </section>
</template>

<style scoped>
.strategy-builder {
    border: 1px solid var(--mw-color-border);
    border-radius: 8px;
    background: var(--mw-color-surface-raised);
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
}

.strategy-status-bar,
.status-actions,
.canvas-toolbar,
.rail-header,
.node-inspector-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
}

.status-actions {
    flex-wrap: wrap;
}

.strategy-status-bar h3 {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1rem;
    font-weight: 700;
    margin: 0;
}

.strategy-status-bar p {
    color: var(--mw-color-text-secondary);
    margin: 2px 0 0;
}

.mono {
    font-family: var(--mw-font-mono);
}

.mobile-review-note {
    display: none;
    border: 1px solid var(--mw-color-border);
    border-radius: 6px;
    color: var(--mw-color-text-secondary);
    padding: 10px;
}

.strategy-layout {
    display: grid;
    grid-template-areas: "library workbench";
    grid-template-columns: minmax(230px, 280px) minmax(0, 1fr);
    gap: 12px;
    align-items: start;
    min-height: 0;
}

.strategy-left-rail,
.strategy-workbench {
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-sm, 6px);
    background: var(--mw-color-surface-panel);
}

.strategy-left-rail {
    grid-area: library;
    align-self: stretch;
}

.strategy-workbench {
    grid-area: workbench;
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
}

.strategy-canvas-shell {
    min-width: 0;
    overflow: hidden;
    position: relative;
}

.strategy-right-rail {
    border-top: 1px solid var(--mw-color-border);
}

.strategy-left-rail,
.strategy-right-rail {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
}

.strategy-right-rail {
    display: grid;
    grid-template-columns: repeat(2, minmax(280px, 1fr));
    align-items: start;
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
.palette-row,
.node-chip {
    min-height: 44px;
    border: 1px solid var(--mw-color-border);
    border-radius: 6px;
    background: transparent;
    color: var(--mw-color-text-primary);
    cursor: pointer;
    font: inherit;
    text-align: left;
}

.strategy-row,
.palette-row {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 10px;
}

.strategy-row.active,
.node-chip.active {
    border-color: var(--mw-color-primary);
    background: rgba(29, 92, 73, 0.08);
}

.strategy-builder :deep(.n-button:not(.n-button--disabled) .n-button__content) {
    font-weight: 700;
    letter-spacing: 0.01em;
}

.strategy-builder
    :deep(.n-button.n-button--primary-type:not(.n-button--disabled) .n-button__content) {
    color: #f7f8f6;
}

.strategy-builder
    :deep(
        .n-button.n-button--secondary:not(.n-button--error-type):not(.n-button--disabled)
            .n-button__content
    ) {
    color: var(--mw-color-text-primary);
}

.strategy-row-meta,
.palette-row small,
.empty-copy,
.explanation {
    color: var(--mw-color-text-secondary);
    font-size: 0.82rem;
}

.strategy-canvas-shell {
    overflow: hidden;
    position: relative;
}

.canvas-toolbar {
    border-bottom: 1px solid var(--mw-color-border);
    color: var(--mw-color-text-secondary);
    min-height: 44px;
    padding: 0 12px;
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
    .strategy-row.active,
    .node-chip.active {
        background: rgba(36, 95, 78, 0.3);
    }

    .rete-host :deep(.node .control input[readonly]) {
        border-color: var(--mw-color-border-strong);
        background: rgba(36, 95, 78, 0.34);
        color: var(--mw-color-text-primary);
    }
}

.rete-host :deep(svg path) {
    stroke: rgba(29, 92, 73, 0.64) !important;
    stroke-width: 3px !important;
}

.rete-host :deep(svg path:hover) {
    stroke: var(--mw-color-primary-strong) !important;
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
    padding: 0 10px;
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

.validation-error {
    color: var(--mw-color-error);
}

.hook-ready {
    color: var(--mw-color-success);
}

@media (max-width: 900px) {
    .mobile-review-note {
        display: block;
    }

    .strategy-layout {
        grid-template-areas:
            "library"
            "workbench";
        grid-template-columns: 1fr;
    }

    .strategy-right-rail {
        grid-template-columns: 1fr;
    }

    .palette-group,
    .rete-host,
    .node-strip,
    .canvas-toolbar,
    .inspector-panel {
        display: none;
    }
}

@media (max-width: 560px) {
    .strategy-status-bar {
        align-items: flex-start;
        flex-direction: column;
    }

    .status-actions {
        justify-content: flex-start;
        width: 100%;
    }

    .status-actions :deep(.n-button) {
        flex: 1 1 132px;
        min-width: 0;
    }
}
</style>
