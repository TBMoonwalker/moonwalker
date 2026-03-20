import type {
    ControlCenterMode,
    ControlCenterTarget,
    ControlCenterTaskPresentation,
} from './types'

const TASKS: readonly ControlCenterTaskPresentation[] = [
    {
        target: 'general',
        title: 'General runtime',
        summary: 'Timezone, diagnostics, and platform-level runtime controls.',
        defaultMode: 'setup',
        modes: ['setup', 'advanced'],
        sectionId: 'control-center-general',
        emphasis: 'primary',
    },
    {
        target: 'exchange',
        title: 'Exchange connection',
        summary: 'Credentials, market selection, and safe dry-run exchange behavior.',
        defaultMode: 'setup',
        modes: ['setup', 'advanced'],
        sectionId: 'control-center-exchange',
        emphasis: 'primary',
    },
    {
        target: 'signal',
        title: 'Signal source',
        summary: 'Choose how Moonwalker receives trade opportunities and symbols.',
        defaultMode: 'setup',
        modes: ['setup'],
        sectionId: 'control-center-signal',
        emphasis: 'primary',
    },
    {
        target: 'dca',
        title: 'Trade safety',
        summary: 'Base order, take profit, and safety-order behavior for dry run.',
        defaultMode: 'setup',
        modes: ['setup', 'advanced'],
        sectionId: 'control-center-dca',
        emphasis: 'primary',
    },
    {
        target: 'monitoring',
        title: 'Operator alerts',
        summary: 'Configure Telegram delivery so the operator can verify notifications.',
        defaultMode: 'setup',
        modes: ['setup', 'advanced'],
        sectionId: 'control-center-monitoring',
        emphasis: 'primary',
    },
    {
        target: 'filter',
        title: 'Signal filtering',
        summary: 'Advanced filtering rules for pair selection and market screening.',
        defaultMode: 'advanced',
        modes: ['advanced'],
        sectionId: 'control-center-filter',
        emphasis: 'secondary',
    },
    {
        target: 'autopilot',
        title: 'Autopilot tuning',
        summary: 'Thresholds and green-phase controls for dynamic operator behavior.',
        defaultMode: 'advanced',
        modes: ['advanced'],
        sectionId: 'control-center-autopilot',
        emphasis: 'secondary',
    },
    {
        target: 'indicator',
        title: 'History and indicators',
        summary: 'History retention and indicator-related background configuration.',
        defaultMode: 'advanced',
        modes: ['advanced'],
        sectionId: 'control-center-indicator',
        emphasis: 'secondary',
    },
    {
        target: 'backup-restore',
        title: 'Backup and restore',
        summary: 'Download portable backups or restore a known-good configuration.',
        defaultMode: 'utilities',
        modes: ['utilities'],
        sectionId: 'control-center-backup-restore',
        emphasis: 'secondary',
    },
    {
        target: 'live-activation',
        title: 'Live activation',
        summary: 'Move from dry run to live trading through an explicit guarded action.',
        defaultMode: 'overview',
        modes: ['overview'],
        sectionId: 'control-center-live-activation',
        emphasis: 'secondary',
    },
] as const

const TASKS_BY_TARGET = new Map(
    TASKS.map((task) => [task.target, task] satisfies [ControlCenterTarget, ControlCenterTaskPresentation]),
)

const KEY_TARGET_PREFIXES: ReadonlyArray<[string, ControlCenterTarget]> = [
    ['signal_settings.', 'signal'],
    ['monitoring_', 'monitoring'],
    ['autopilot_', 'autopilot'],
    ['ws_', 'general'],
]

const KEY_TARGETS: Record<string, ControlCenterTarget> = {
    timezone: 'general',
    debug: 'general',
    exchange: 'exchange',
    key: 'exchange',
    secret: 'exchange',
    timeframe: 'exchange',
    dry_run: 'exchange',
    currency: 'exchange',
    market: 'exchange',
    exchange_hostname: 'exchange',
    watcher_ohlcv: 'exchange',
    signal: 'signal',
    symbol_list: 'signal',
    rsi_max: 'filter',
    marketcap_cmc_api_key: 'filter',
    pair_denylist: 'filter',
    topcoin_limit: 'filter',
    volume: 'filter',
    btc_pulse: 'filter',
    dca: 'dca',
    dynamic_dca: 'dca',
    dca_strategy: 'dca',
    max_bots: 'dca',
    bo: 'dca',
    sell_order_type: 'dca',
    limit_sell_timeout_sec: 'dca',
    limit_sell_fallback_to_market: 'dca',
    tp_spike_confirm_enabled: 'dca',
    tp_spike_confirm_seconds: 'dca',
    tp_spike_confirm_ticks: 'dca',
    so: 'dca',
    mstc: 'dca',
    sos: 'dca',
    ss: 'dca',
    os: 'dca',
    trade_safety_order_budget_ratio: 'dca',
    tp: 'dca',
    sl: 'dca',
    monitoring_enabled: 'monitoring',
    history_lookback_time: 'indicator',
    upnl_housekeeping_interval: 'indicator',
}

export const CONTROL_CENTER_TASKS = TASKS

export function getTaskPresentation(
    target: ControlCenterTarget,
): ControlCenterTaskPresentation {
    return TASKS_BY_TARGET.get(target) ?? TASKS_BY_TARGET.get('general')!
}

export function getTasksForMode(
    mode: ControlCenterMode,
): ControlCenterTaskPresentation[] {
    return TASKS.filter((task) => task.modes.includes(mode))
}

export function isKnownControlCenterTarget(
    value: unknown,
): value is ControlCenterTarget {
    return (
        typeof value === 'string' &&
        TASKS_BY_TARGET.has(value as ControlCenterTarget)
    )
}

export function resolveTargetForConfigKey(key: string): ControlCenterTarget {
    const normalizedKey = key.trim()
    for (const [prefix, target] of KEY_TARGET_PREFIXES) {
        if (normalizedKey.startsWith(prefix)) {
            return target
        }
    }
    return KEY_TARGETS[normalizedKey] ?? 'general'
}
