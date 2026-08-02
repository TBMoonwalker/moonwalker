import { describe, expect, it } from 'vitest'

import {
    mergeReplayCandleRows,
    replayNeedsHistoryFallback,
    type ReplayCandleRow,
} from '../src/helpers/tradeReplayCandles'

function candle(time: number, close = time): ReplayCandleRow {
    return {
        time,
        open: close,
        high: close,
        low: close,
        close,
    }
}

describe('trade replay candle coverage', () => {
    it('requests shared history for a nonempty but sparse archive', () => {
        expect(
            replayNeedsHistoryFallback(
                [candle(0), candle(300), candle(600)],
                0,
                600_000,
                60,
            ),
        ).toBe(true)
    })

    it('keeps a dense archive that covers the requested window', () => {
        const rows = Array.from({ length: 11 }, (_, index) =>
            candle(index * 60),
        )

        expect(
            replayNeedsHistoryFallback(rows, 0, 600_000, 60),
        ).toBe(false)
    })

    it('keeps nonempty live replay data when the window has no end', () => {
        expect(
            replayNeedsHistoryFallback([candle(60)], 0, null, 60),
        ).toBe(false)
    })

    it('merges shared history chronologically and prefers archive overlaps', () => {
        const rows = mergeReplayCandleRows(
            [candle(120, 12), candle(0, 2)],
            [candle(0, 1), candle(60, 6), candle(120, 11)],
        )

        expect(rows.map((row) => row.time)).toEqual([0, 60, 120])
        expect(rows.map((row) => row.close)).toEqual([2, 6, 12])
    })
})
