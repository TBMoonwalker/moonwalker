export const BACKTEST_TIMEFRAME_OPTIONS = [
    { label: '5m', value: '5m' },
    { label: '15m', value: '15m' },
    { label: '30m', value: '30m' },
    { label: '1h', value: '1h' },
    { label: '4h', value: '4h' },
    { label: '1d', value: '1d' },
    { label: '1w', value: '1w' },
] as const

export const BACKTEST_TRADE_MODE_OPTIONS = [
    { label: 'Dynamic DCA', value: 'dynamic_dca' },
    { label: 'Sidestep', value: 'sidestep' },
] as const

export type BacktestTradeMode =
    (typeof BACKTEST_TRADE_MODE_OPTIONS)[number]['value']

export interface BacktestFormState {
    symbol: string
    strategySlug: string
    tradeMode: BacktestTradeMode
    sidestepBearishStrategySlug: string
    sidestepReentryStrategySlug: string
    timeframe: string
    baseOrderSize: number
    takeProfitPct: number
    stopLossPct: number
    maxSafetyOrders: number
    safetyOrderStepPct: number
    stepScale: number
    fee: number
}

export interface BacktestRunRequest {
    symbol: string
    strategy_slug: string
    trade_mode: BacktestTradeMode
    sidestep_bearish_strategy: string
    sidestep_reentry_strategy: string
    timeframe: string
    start_date: number
    end_date: number
    base_order_size: number
    take_profit_pct: number
    stop_loss_pct: number
    max_safety_orders: number
    safety_order_step_pct: number
    step_scale: number
    fee: number
}

export interface BacktestCandle {
    time: number
    open: number
    high: number
    low: number
    close: number
    volume?: number
}

export interface BacktestMarker {
    time: number
    position: 'aboveBar' | 'belowBar' | 'inBar'
    color: string
    shape: 'arrow_up' | 'arrow_down' | 'circle' | 'arrowUp' | 'arrowDown'
    text: string
}

export interface BacktestTrade {
    id: number | string
    symbol: string
    open_timestamp: number
    open_price: number
    close_timestamp: number
    close_price: number
    profit: number
    profit_percent: number
    safety_orders_count: number
    duration: string
    sell_reason?: string | null
}

export interface BacktestStats {
    summary?: {
        total_trades?: number
        win_rate?: number
        total_profit?: number
        avg_profit?: number
        avg_profit_percent?: number
        total_cost?: number
    }
    drawdown?: {
        max_drawdown?: number
        max_drawdown_percent?: number
    }
    candles_fetched?: number
    candles_evaluated?: number
    warmup_candles?: number
    timeframe?: string
    symbol?: string
    strategy?: string
    trade_mode?: BacktestTradeMode
    sidestep_bearish_strategy?: string
    sidestep_reentry_strategy?: string
    still_open_at_end?: boolean
    sidestep_waiting_at_end?: boolean
}

export interface BacktestResult {
    trades: BacktestTrade[]
    chart: {
        candles: BacktestCandle[]
        markers: BacktestMarker[]
    }
    stats: BacktestStats
}

export interface BacktestComparison {
    tradesDelta: number
    profitDelta: number
    winRateDelta: number
}

export function createDefaultBacktestForm(): BacktestFormState {
    return {
        symbol: 'BTC/USDT',
        strategySlug: 'ema20_swing',
        tradeMode: 'dynamic_dca',
        sidestepBearishStrategySlug: 'ema_down',
        sidestepReentryStrategySlug: 'ema20_swing_reverse',
        timeframe: '1h',
        baseOrderSize: 20,
        takeProfitPct: 2.5,
        stopLossPct: 5,
        maxSafetyOrders: 5,
        safetyOrderStepPct: 3,
        stepScale: 1,
        fee: 0.001,
    }
}

export function createDefaultBacktestRange(now = Date.now()): [number, number] {
    const dayMs = 24 * 60 * 60 * 1000
    return [now - 7 * dayMs, now]
}

export function buildBacktestRequest(
    form: BacktestFormState,
    dateRange: [number, number],
): BacktestRunRequest {
    return {
        symbol: form.symbol.trim(),
        strategy_slug:
            form.tradeMode === 'sidestep'
                ? form.sidestepReentryStrategySlug.trim()
                : form.strategySlug.trim(),
        trade_mode: form.tradeMode,
        sidestep_bearish_strategy: form.sidestepBearishStrategySlug.trim(),
        sidestep_reentry_strategy: form.sidestepReentryStrategySlug.trim(),
        timeframe: form.timeframe,
        start_date: dateRange[0],
        end_date: dateRange[1],
        base_order_size: form.baseOrderSize,
        take_profit_pct: form.takeProfitPct,
        stop_loss_pct: form.stopLossPct,
        max_safety_orders: form.maxSafetyOrders,
        safety_order_step_pct: form.safetyOrderStepPct,
        step_scale: form.stepScale,
        fee: form.fee,
    }
}

export function getBacktestSummary(result: BacktestResult | null) {
    return result?.stats?.summary ?? {}
}

export function computeBacktestComparison(
    current: BacktestResult | null,
    previous: BacktestResult | null,
): BacktestComparison | null {
    if (!current || !previous) {
        return null
    }

    const currentSummary = getBacktestSummary(current)
    const previousSummary = getBacktestSummary(previous)

    return {
        tradesDelta:
            Number(currentSummary.total_trades ?? 0) -
            Number(previousSummary.total_trades ?? 0),
        profitDelta:
            Number(currentSummary.total_profit ?? 0) -
            Number(previousSummary.total_profit ?? 0),
        winRateDelta:
            Number(currentSummary.win_rate ?? 0) -
            Number(previousSummary.win_rate ?? 0),
    }
}

export function formatBacktestNumber(value: number | undefined, digits = 2): string {
    const normalized = Number(value ?? 0)
    return normalized.toLocaleString(undefined, {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
    })
}

export function formatBacktestDelta(value: number, suffix = ''): string {
    const prefix = value > 0 ? '+' : ''
    return `${prefix}${formatBacktestNumber(value)}${suffix}`
}

export function getBacktestSymbolQuoteCurrency(symbol: string): string {
    const [, quote = ''] = String(symbol).split('/')
    return quote.trim().toUpperCase()
}

export function normalizeBacktestSymbolsForCurrency(
    symbols: string[],
    currency: string,
): string[] {
    const quoteCurrency = currency.trim().toUpperCase()
    const seen = new Set<string>()

    return symbols
        .map((symbol) => symbol.trim())
        .filter((symbol) => {
            if (!symbol || seen.has(symbol)) {
                return false
            }
            seen.add(symbol)
            return !quoteCurrency || getBacktestSymbolQuoteCurrency(symbol) === quoteCurrency
        })
        .sort((left, right) => left.localeCompare(right))
}

export function normalizeBacktestMarkerShape(
    shape: BacktestMarker['shape'],
): 'arrowUp' | 'arrowDown' | 'circle' {
    if (shape === 'arrow_up' || shape === 'arrowUp') {
        return 'arrowUp'
    }
    if (shape === 'arrow_down' || shape === 'arrowDown') {
        return 'arrowDown'
    }
    return 'circle'
}

export function normalizeBacktestTimestampSeconds(value: number): number {
    return Math.trunc(value > 10_000_000_000 ? value / 1000 : value)
}
