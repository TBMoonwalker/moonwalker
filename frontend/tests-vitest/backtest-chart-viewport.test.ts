import { describe, expect, it } from 'vitest'

import {
    expandBoundaryLogicalRange,
    selectBoundaryMarkerTextWidths,
} from '../src/helpers/backtestChartViewport'

describe('Backtest chart boundary marker selection', () => {
    it('rejects invalid or reversed candle boundaries', () => {
        expect(
            selectBoundaryMarkerTextWidths({
                firstCandleTime: Number.NaN,
                lastCandleTime: 2,
                markers: [],
            }),
        ).toBeNull()
        expect(
            selectBoundaryMarkerTextWidths({
                firstCandleTime: 2,
                lastCandleTime: 1,
                markers: [],
            }),
        ).toBeNull()
    })

    it('selects the widest unsorted marker at each boundary', () => {
        expect(
            selectBoundaryMarkerTextWidths({
                firstCandleTime: 10,
                lastCandleTime: 30,
                markers: [
                    { time: 30, textWidthPx: 20 },
                    { time: 10, textWidthPx: 12 },
                    { time: 20, textWidthPx: 100 },
                    { time: 10, textWidthPx: 48 },
                    { time: 30, textWidthPx: 36 },
                ],
            }),
        ).toEqual({ leftTextWidthPx: 48, rightTextWidthPx: 36 })
    })

    it('ignores invalid, negative-width, and outside-range markers', () => {
        expect(
            selectBoundaryMarkerTextWidths({
                firstCandleTime: 10,
                lastCandleTime: 30,
                markers: [
                    { time: Number.NaN, textWidthPx: 10 },
                    { time: 10, textWidthPx: Number.POSITIVE_INFINITY },
                    { time: 10, textWidthPx: -1 },
                    { time: 9, textWidthPx: 50 },
                    { time: 31, textWidthPx: 50 },
                ],
            }),
        ).toEqual({ leftTextWidthPx: null, rightTextWidthPx: null })
    })

    it('uses the same widest marker for both edges of one candle', () => {
        expect(
            selectBoundaryMarkerTextWidths({
                firstCandleTime: 10,
                lastCandleTime: 10,
                markers: [
                    { time: 10, textWidthPx: 0 },
                    { time: 10, textWidthPx: 42 },
                ],
            }),
        ).toEqual({ leftTextWidthPx: 42, rightTextWidthPx: 42 })
    })
})

describe('Backtest chart exact logical range solver', () => {
    const baseInput = {
        fittedRange: { from: 0, to: 9 },
        firstLogicalIndex: 0,
        lastLogicalIndex: 9,
        plotWidthPx: 100,
        requiredLeftPx: 0,
        requiredRightPx: 0,
    }

    it('rejects null, non-finite, non-positive, and reversed inputs', () => {
        expect(
            expandBoundaryLogicalRange({ ...baseInput, fittedRange: null }),
        ).toBeNull()
        expect(
            expandBoundaryLogicalRange({ ...baseInput, requiredLeftPx: Number.NaN }),
        ).toBeNull()
        expect(
            expandBoundaryLogicalRange({ ...baseInput, plotWidthPx: 0 }),
        ).toBeNull()
        expect(
            expandBoundaryLogicalRange({
                ...baseInput,
                firstLogicalIndex: 10,
                lastLogicalIndex: 9,
            }),
        ).toBeNull()
        expect(
            expandBoundaryLogicalRange({
                ...baseInput,
                fittedRange: { from: 10, to: 0 },
            }),
        ).toBeNull()
        expect(
            expandBoundaryLogicalRange({
                ...baseInput,
                fittedRange: { from: 1, to: 9 },
            }),
        ).toBeNull()
        expect(
            expandBoundaryLogicalRange({
                ...baseInput,
                fittedRange: { from: 0, to: 8 },
            }),
        ).toBeNull()
    })

    it('returns a new unchanged range when no edge requires padding', () => {
        const fittedRange = { from: -1, to: 10 }
        const result = expandBoundaryLogicalRange({
            ...baseInput,
            fittedRange,
            requiredLeftPx: -5,
            requiredRightPx: -2,
        })

        expect(result).toEqual(fittedRange)
        expect(result).not.toBe(fittedRange)
    })

    it('keeps baseline padding when it already supplies both clearances', () => {
        expect(
            expandBoundaryLogicalRange({
                ...baseInput,
                fittedRange: { from: -2, to: 11 },
                requiredLeftPx: 10,
                requiredRightPx: 10,
            }),
        ).toEqual({ from: -2, to: 11 })
    })

    it('keeps the first equally small valid candidate', () => {
        expect(
            expandBoundaryLogicalRange({
                ...baseInput,
                fittedRange: { from: -2, to: 11 },
                plotWidthPx: 130,
                requiredLeftPx: 20,
                requiredRightPx: 20,
            }),
        ).toEqual({ from: -2, to: 11 })
    })

    it('solves the left-target and right-baseline candidate exactly', () => {
        expect(
            expandBoundaryLogicalRange({
                ...baseInput,
                fittedRange: { from: 0, to: 11 },
                requiredLeftPx: 20,
            }),
        ).toEqual({ from: -2.75, to: 11 })
    })

    it('solves the left-baseline and right-target candidate exactly', () => {
        expect(
            expandBoundaryLogicalRange({
                ...baseInput,
                fittedRange: { from: -2, to: 9 },
                requiredRightPx: 20,
            }),
        ).toEqual({ from: -2, to: 11.75 })
    })

    it('solves the both-target candidate exactly', () => {
        const result = expandBoundaryLogicalRange({
            ...baseInput,
            requiredLeftPx: 20,
            requiredRightPx: 20,
        })

        expect(result?.from).toBeCloseTo(-3)
        expect(result?.to).toBeCloseTo(12)
    })

    it('preserves a non-zero symmetric span for one candle', () => {
        expect(
            expandBoundaryLogicalRange({
                fittedRange: { from: 4.5, to: 5.5 },
                firstLogicalIndex: 5,
                lastLogicalIndex: 5,
                plotWidthPx: 100,
                requiredLeftPx: 20,
                requiredRightPx: 20,
            }),
        ).toEqual({ from: 4.5, to: 5.5 })
    })

    it('rejects physically impossible combined edge requirements', () => {
        expect(
            expandBoundaryLogicalRange({
                ...baseInput,
                requiredLeftPx: 50,
                requiredRightPx: 50,
            }),
        ).toBeNull()
    })

    it('returns null when finite input overflows every valid candidate', () => {
        expect(
            expandBoundaryLogicalRange({
                fittedRange: { from: 0, to: Number.MAX_VALUE },
                firstLogicalIndex: 0,
                lastLogicalIndex: Number.MAX_VALUE,
                plotWidthPx: 100,
                requiredLeftPx: 40,
                requiredRightPx: 40,
            }),
        ).toBeNull()
    })
})
