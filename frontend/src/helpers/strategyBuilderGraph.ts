import type { StrategyIr, StrategyNode } from '../types/strategyBuilder'

const COMPARISON_LABELS: Record<string, string> = {
    equals: 'equals',
    greater_or_equal: 'greater or equal',
    greater_than: 'greater than',
    less_or_equal: 'less or equal',
    less_than: 'less than',
    not_equals: 'not equals',
}

const INDICATOR_LABELS: Record<string, string> = {
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

export function coerceStrategyParam(value: string): unknown {
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

export function formatStrategyParam(value: unknown): string {
    if (Array.isArray(value) || (value && typeof value === 'object')) {
        return 'Configured by graph connections'
    }
    return String(value)
}

export function isPrimitiveStrategyParam(value: unknown): boolean {
    return !Array.isArray(value) && (!value || typeof value !== 'object')
}

export function isStrategyValueNode(node: StrategyNode): boolean {
    return [
        'close_price',
        'low_price',
        'high_price',
        'constant_value',
        'indicator',
    ].includes(node.type)
}

export function normalizeComparisonPort(port: string): string {
    if (port === 'left') {
        return 'value1'
    }
    if (port === 'right') {
        return 'value2'
    }
    return port
}

export function indicatorUsesSample(node: StrategyNode | null): boolean {
    const indicator = String(node?.params?.indicator ?? '')
    return (
        ['ema', 'rsi'].includes(indicator) ||
        indicator.startsWith('bollinger_') ||
        indicator.startsWith('macd_')
    )
}

export function strategyNodeTitle(node: StrategyNode, ir: StrategyIr): string {
    return _strategyNodeTitle(node, ir, new Set())
}

function _strategyNodeTitle(
    node: StrategyNode,
    ir: StrategyIr,
    visiting: Set<string>,
): string {
    if (visiting.has(node.id)) {
        return node.label || node.type
    }
    const nextVisiting = new Set(visiting)
    nextVisiting.add(node.id)

    if (node.type === 'comparison') {
        const value1 = comparisonInputTitle(node.id, 'value1', ir, nextVisiting)
        const value2 = comparisonInputTitle(node.id, 'value2', ir, nextVisiting)
        const comparison = String(node.params?.comparison ?? 'greater_than')
        const operator = COMPARISON_LABELS[comparison] ?? comparison
        if (value1 && value2) {
            return `${value1} ${operator} ${value2}`
        }
    }
    if (node.type === 'indicator') {
        const indicator = String(node.params?.indicator ?? 'indicator')
        const length = node.params?.length ? ` ${node.params.length}` : ''
        const sample = indicatorUsesSample(node)
            ? ` ${sampleLabel(node.params?.sample)}`
            : ''
        return `${INDICATOR_LABELS[indicator] ?? indicator}${length}${sample}`
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

function comparisonInputTitle(
    nodeId: string,
    port: string,
    ir: StrategyIr,
    visiting: Set<string>,
): string | null {
    const canonicalPort = normalizeComparisonPort(port)
    const connection = ir.connections.find((item) => {
        const target = String(item.target ?? item.targetNode ?? '')
        const targetInput = normalizeComparisonPort(
            String(item.target_input ?? item.targetInput ?? item.input ?? ''),
        )
        return target === nodeId && targetInput === canonicalPort
    })
    const sourceId = connection
        ? String(connection.source ?? connection.sourceNode ?? '')
        : ''
    const source = ir.nodes.find((item) => item.id === sourceId)
    return source ? _strategyNodeTitle(source, ir, visiting) : null
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

export function autoAlignStrategyGraph(
    ir: StrategyIr,
    titleForNode: (node: StrategyNode) => string,
): void {
    const nodes = ir.nodes
    if (!nodes.length) {
        return
    }
    const nodeById = new Map(nodes.map((node) => [node.id, node]))
    const incomingByTarget = new Map<string, string[]>()
    for (const connection of ir.connections ?? []) {
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
        if (isStrategyValueNode(node)) {
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
    const maxColumnSize = Math.max(
        ...[...columns.values()].map((column) => column.length),
    )
    for (const depth of [...columns.keys()].sort((first, second) => first - second)) {
        const column = columns.get(depth) ?? []
        column.sort((first, second) => {
            const weightDelta = typeWeight(first) - typeWeight(second)
            return weightDelta || titleForNode(first).localeCompare(titleForNode(second))
        })
        const yOffset = ((maxColumnSize - column.length) * 128) / 2
        column.forEach((node, index) => {
            node.position = {
                x: 80 + depth * 300,
                y: 72 + yOffset + index * 128,
            }
        })
    }
}
