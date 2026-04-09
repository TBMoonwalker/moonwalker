export interface AutopilotMemorySnapshot {
    confidence_bucket: string
    confidence_progress: number
    last_closed_at: string | null
    loss_count: number
    primary_reason_code: string | null
    primary_reason_value: number | null
    profitable_closes: number
    sample_size: number
    secondary_reason_code: string | null
    secondary_reason_value: number | null
    slow_close_count: number
    suggested_base_order: number
    symbol: string
    tp_delta_ratio: number
    trust_direction: string
    trust_score: number
    weighted_close_hours: number
    weighted_profit_percent: number
}

export interface AutopilotMemoryEvent {
    created_at: string | null
    event_type: string
    reason_code: string | null
    reason_value: number | null
    symbol: string | null
    tone: string
    trust_score: number | null
}

export interface AutopilotMemoryPayload {
    baseline_mode_active: boolean
    enabled: boolean
    events: AutopilotMemoryEvent[]
    featured: AutopilotMemorySnapshot | null
    last_success_at: string | null
    portfolio_effect: {
        adaptive_tp_max: number | null
        adaptive_tp_min: number | null
        suggested_base_order_max: number | null
        suggested_base_order_min: number | null
    }
    stale: boolean
    stale_reason: string | null
    status: string
    trust_board: {
        cooling: AutopilotMemorySnapshot[]
        favored: AutopilotMemorySnapshot[]
    }
    updated_at: string | null
    warmup: {
        current_closes: number
        progress_percent: number | null
        required_closes: number
    }
}
