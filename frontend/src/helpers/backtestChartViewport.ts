export interface MeasuredBacktestMarker {
    time: number
    textWidthPx: number
}

export interface BoundaryMarkerSelectionInput {
    firstCandleTime: number
    lastCandleTime: number
    markers: readonly MeasuredBacktestMarker[]
}

export interface BoundaryMarkerTextWidths {
    leftTextWidthPx: number | null
    rightTextWidthPx: number | null
}

export interface LogicalRange {
    from: number
    to: number
}

export interface BoundaryRangeInput {
    fittedRange: LogicalRange | null
    firstLogicalIndex: number
    lastLogicalIndex: number
    plotWidthPx: number
    requiredLeftPx: number
    requiredRightPx: number
}

interface PaddingCandidate {
    left: number
    right: number
}

const CONSTRAINT_EPSILON = 1e-9

export function selectBoundaryMarkerTextWidths(
    input: BoundaryMarkerSelectionInput,
): BoundaryMarkerTextWidths | null {
    const { firstCandleTime, lastCandleTime } = input
    if (![firstCandleTime, lastCandleTime].every(Number.isFinite)) {
        return null
    }
    if (firstCandleTime > lastCandleTime) {
        return null
    }

    let leftTextWidthPx: number | null = null
    let rightTextWidthPx: number | null = null

    for (const marker of input.markers) {
        if (![marker.time, marker.textWidthPx].every(Number.isFinite)) {
            continue
        }
        if (marker.textWidthPx < 0) {
            continue
        }
        if (marker.time < firstCandleTime || marker.time > lastCandleTime) {
            continue
        }
        if (marker.time === firstCandleTime) {
            leftTextWidthPx = Math.max(leftTextWidthPx ?? 0, marker.textWidthPx)
        }
        if (marker.time === lastCandleTime) {
            rightTextWidthPx = Math.max(rightTextWidthPx ?? 0, marker.textWidthPx)
        }
    }

    return { leftTextWidthPx, rightTextWidthPx }
}

function candidateSatisfiesConstraints(
    candidate: PaddingCandidate,
    dataSpan: number,
    minimumLeft: number,
    minimumRight: number,
    leftFraction: number,
    rightFraction: number,
): boolean {
    const span = dataSpan + candidate.left + candidate.right
    if (![candidate.left, candidate.right, span].every(Number.isFinite)) {
        return false
    }

    const minimumSlack = Math.min(
        candidate.left - minimumLeft,
        candidate.right - minimumRight,
        candidate.left - leftFraction * span,
        candidate.right - rightFraction * span,
    )
    return minimumSlack >= -CONSTRAINT_EPSILON
}

export function expandBoundaryLogicalRange(
    input: BoundaryRangeInput,
): LogicalRange | null {
    const { fittedRange } = input
    if (!fittedRange) {
        return null
    }

    const numericInputs = [
        fittedRange.from,
        fittedRange.to,
        input.firstLogicalIndex,
        input.lastLogicalIndex,
        input.plotWidthPx,
        input.requiredLeftPx,
        input.requiredRightPx,
    ]
    if (!numericInputs.every(Number.isFinite)) {
        return null
    }
    if (input.plotWidthPx <= 0) {
        return null
    }
    if (input.firstLogicalIndex > input.lastLogicalIndex) {
        return null
    }
    if (fittedRange.from > fittedRange.to) {
        return null
    }
    if (fittedRange.from > input.firstLogicalIndex) {
        return null
    }
    if (fittedRange.to < input.lastLogicalIndex) {
        return null
    }

    const requiredLeftPx = Math.max(0, input.requiredLeftPx)
    const requiredRightPx = Math.max(0, input.requiredRightPx)
    if (requiredLeftPx === 0 && requiredRightPx === 0) {
        return { ...fittedRange }
    }

    const leftFraction = requiredLeftPx / input.plotWidthPx
    const rightFraction = requiredRightPx / input.plotWidthPx
    if (leftFraction + rightFraction >= 1) {
        return null
    }

    const dataSpan = input.lastLogicalIndex - input.firstLogicalIndex
    let minimumLeft = Math.max(0, input.firstLogicalIndex - fittedRange.from)
    let minimumRight = Math.max(0, fittedRange.to - input.lastLogicalIndex)
    if (dataSpan === 0) {
        minimumLeft = Math.max(minimumLeft, 0.5)
        minimumRight = Math.max(minimumRight, 0.5)
    }

    const candidates: PaddingCandidate[] = [
        { left: minimumLeft, right: minimumRight },
        {
            left:
                (leftFraction * (dataSpan + minimumRight)) /
                (1 - leftFraction),
            right: minimumRight,
        },
        {
            left: minimumLeft,
            right:
                (rightFraction * (dataSpan + minimumLeft)) /
                (1 - rightFraction),
        },
        {
            left:
                (leftFraction * dataSpan) /
                (1 - leftFraction - rightFraction),
            right:
                (rightFraction * dataSpan) /
                (1 - leftFraction - rightFraction),
        },
    ]

    let bestCandidate: PaddingCandidate | null = null
    let bestSpan = Number.POSITIVE_INFINITY
    for (const candidate of candidates) {
        if (
            !candidateSatisfiesConstraints(
                candidate,
                dataSpan,
                minimumLeft,
                minimumRight,
                leftFraction,
                rightFraction,
            )
        ) {
            continue
        }
        const candidateSpan = dataSpan + candidate.left + candidate.right
        if (candidateSpan < bestSpan) {
            bestCandidate = candidate
            bestSpan = candidateSpan
        }
    }

    if (!bestCandidate) {
        return null
    }
    return {
        from: input.firstLogicalIndex - bestCandidate.left,
        to: input.lastLogicalIndex + bestCandidate.right,
    }
}
