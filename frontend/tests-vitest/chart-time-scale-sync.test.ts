import { describe, expect, it, vi } from 'vitest'
import type { IRange, Time, TimeRangeChangeEventHandler } from 'lightweight-charts'
import { synchronizeTimeScales } from '../src/helpers/tradingViewIndicators'

function pane() {
    const handlers = new Set<TimeRangeChangeEventHandler<Time>>()
    const emit = (range: IRange<Time> | null) => {
        for (const handler of handlers) handler(range)
    }
    const scale = {
        subscribeVisibleTimeRangeChange: vi.fn((handler: TimeRangeChangeEventHandler<Time>) => handlers.add(handler)),
        unsubscribeVisibleTimeRangeChange: vi.fn((handler: TimeRangeChangeEventHandler<Time>) => handlers.delete(handler)),
        setVisibleRange: vi.fn((range: IRange<Time>) => emit(range)),
    }
    return { timeScale: () => scale, scale, emit }
}
const range = { from: '2026-10-24', to: '2026-10-25' }

describe('chart time-scale synchronization', () => {
    it('updates every sibling in either direction without recursive propagation', () => {
        const charts = [pane(), pane(), pane()]
        const dispose = synchronizeTimeScales(charts)
        charts[0].emit(range)
        expect(charts.map(chart => chart.scale.setVisibleRange.mock.calls.length)).toEqual([0, 1, 1])
        charts[1].emit(range)
        expect(charts.map(chart => chart.scale.setVisibleRange.mock.calls.length)).toEqual([1, 1, 2])
        charts[0].emit(null)
        expect(charts.map(chart => chart.scale.setVisibleRange.mock.calls.length)).toEqual([1, 1, 2])
        dispose()
    })

    it('isolates groups, removes exact handlers, and ignores queued callbacks after cleanup', () => {
        const first = [pane(), pane()]
        const second = [pane(), pane()]
        const stopFirst = synchronizeTimeScales(first)
        const stopSecond = synchronizeTimeScales(second)
        const callback = first[0].scale.subscribeVisibleTimeRangeChange.mock.calls[0][0]
        first[0].emit(range)
        expect(second[1].scale.setVisibleRange).not.toHaveBeenCalled()
        stopFirst()
        stopFirst()
        first[1].scale.setVisibleRange.mockClear()
        callback(range)
        first[0].emit(range)
        expect(first[1].scale.setVisibleRange).not.toHaveBeenCalled()
        expect(first[0].scale.unsubscribeVisibleTimeRangeChange).toHaveBeenCalledExactlyOnceWith(callback)
        second[0].emit(range)
        expect(second[1].scale.setVisibleRange).toHaveBeenCalledOnce()
        stopSecond()
    })

    it('releases the recursion guard after a target throws and supports a rebuilt group', () => {
        const charts = [pane(), pane()]
        const dispose = synchronizeTimeScales(charts)
        charts[1].scale.setVisibleRange.mockImplementationOnce(() => { throw new Error('removed pane') })
        expect(() => charts[0].emit(range)).toThrow('removed pane')
        charts[0].emit(range)
        expect(charts[1].scale.setVisibleRange).toHaveBeenCalledTimes(2)
        dispose()
        const stopRebuilt = synchronizeTimeScales(charts)
        charts[1].emit(range)
        expect(charts[0].scale.setVisibleRange).toHaveBeenCalledOnce()
        stopRebuilt()
    })
})
