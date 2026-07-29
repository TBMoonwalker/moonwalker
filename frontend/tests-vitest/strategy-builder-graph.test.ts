import { describe, expect, it } from 'vitest'

import {
    autoAlignStrategyGraph,
    coerceStrategyParam,
    formatStrategyParam,
    indicatorUsesSample,
    isPrimitiveStrategyParam,
    isStrategyValueNode,
    normalizeComparisonPort,
    strategyNodeTitle,
} from '../src/helpers/strategyBuilderGraph'
import type { StrategyIr } from '../src/types/strategyBuilder'

function graph(): StrategyIr {
    return {
        schema_version: 1,
        slug: 'custom_test',
        name: 'Test',
        kind: 'custom',
        root: 'decision',
        nodes: [
            {
                id: 'ema20',
                type: 'indicator',
                params: { indicator: 'ema', length: 20, sample: 'current' },
            },
            {
                id: 'close',
                type: 'close_price',
                params: { sample: 'previous' },
            },
            {
                id: 'decision',
                type: 'comparison',
                params: { comparison: 'greater_than' },
            },
        ],
        connections: [
            { source: 'ema20', target: 'decision', target_input: 'left' },
            { source: 'close', target: 'decision', target_input: 'right' },
        ],
    }
}

describe('strategyBuilderGraph', () => {
    it('coerces primitive inspector values', () => {
        expect(coerceStrategyParam(' 12.5 ')).toBe(12.5)
        expect(coerceStrategyParam('true')).toBe(true)
        expect(coerceStrategyParam('false')).toBe(false)
        expect(coerceStrategyParam('bullish')).toBe('bullish')
        expect(formatStrategyParam({ nested: true })).toBe(
            'Configured by graph connections',
        )
        expect(formatStrategyParam(['connected'])).toBe(
            'Configured by graph connections',
        )
        expect(formatStrategyParam(null)).toBe('null')
        expect(isPrimitiveStrategyParam('text')).toBe(true)
        expect(isPrimitiveStrategyParam(null)).toBe(true)
        expect(isPrimitiveStrategyParam([])).toBe(false)
        expect(isPrimitiveStrategyParam({})).toBe(false)
    })

    it('builds readable titles across legacy comparison ports', () => {
        const ir = graph()
        expect(strategyNodeTitle(ir.nodes[2]!, ir)).toBe(
            'EMA 20 current greater than Close previous',
        )
        expect(normalizeComparisonPort('left')).toBe('value1')
        expect(normalizeComparisonPort('right')).toBe('value2')
        expect(normalizeComparisonPort('in')).toBe('in')
    })

    it('describes every supported node family and safe fallbacks', () => {
        const ir = graph()
        const title = (node: (typeof ir.nodes)[number]) =>
            strategyNodeTitle(node, ir)

        expect(title({ id: 'low', type: 'low_price', params: {} })).toBe(
            'Low current',
        )
        expect(
            title({
                id: 'high',
                type: 'high_price',
                params: { sample: 'two_back' },
            }),
        ).toBe('High two back')
        expect(title({ id: 'constant', type: 'constant_value' })).toBe(
            'Constant value',
        )
        expect(title({ id: 'state', type: 'swing_low_state' })).toContain(
            'stored swing low',
        )
        expect(title({ id: 'logic', type: 'all', label: 'All ready' })).toBe(
            'All ready',
        )
        expect(title({ id: 'unknown', type: 'custom_node' })).toBe('custom_node')
        expect(
            title({
                id: 'custom_indicator',
                type: 'indicator',
                params: { indicator: 'custom', sample: 'current' },
            }),
        ).toBe('custom')
        expect(
            title({
                id: 'rsi',
                type: 'indicator',
                params: { indicator: 'rsi', length: 14, sample: 'previous' },
            }),
        ).toBe('RSI 14 previous')
        expect(
            indicatorUsesSample({
                id: 'macd',
                type: 'indicator',
                params: { indicator: 'macd_line' },
            }),
        ).toBe(true)
        expect(indicatorUsesSample(null)).toBe(false)
        expect(isStrategyValueNode({ id: 'value', type: 'indicator' })).toBe(true)
        expect(isStrategyValueNode({ id: 'logic', type: 'all' })).toBe(false)
    })

    it('aligns graph columns without looping on cyclic input', () => {
        const ir = graph()
        ir.connections.push({
            source: 'decision',
            target: 'decision',
            target_input: 'value1',
        })

        expect(() => strategyNodeTitle(ir.nodes[2]!, ir)).not.toThrow()
        autoAlignStrategyGraph(ir, (node) => strategyNodeTitle(node, ir))

        const sourceX = ir.nodes.find((node) => node.id === 'ema20')?.position?.x
        const decisionX = ir.nodes.find(
            (node) => node.id === 'decision',
        )?.position?.x
        expect(sourceX).toBeTypeOf('number')
        expect(decisionX).toBeTypeOf('number')
    })

    it('leaves an empty graph unchanged', () => {
        const ir = graph()
        ir.nodes = []
        expect(() => autoAlignStrategyGraph(ir, () => '')).not.toThrow()
    })

    it('orders mixed node types and ignores invalid edges', () => {
        const ir = graph()
        ir.nodes.push(
            { id: 'state', type: 'fresh_signal_state', label: 'State' },
            { id: 'all', type: 'all', label: 'All' },
            { id: 'other', type: 'other', label: 'Other' },
        )
        ir.connections.push(
            { source: 'missing', target: 'decision' },
            { source: 'ema20', target: 'missing' },
        )

        autoAlignStrategyGraph(ir, (node) => node.label ?? node.id)

        expect(ir.nodes.every((node) => node.position !== undefined)).toBe(true)
    })
})
