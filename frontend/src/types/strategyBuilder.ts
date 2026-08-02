export type StrategyKind = 'builtin' | 'custom'

export interface StrategySummary {
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

export interface StrategyNode {
    id: string
    type: string
    label?: string
    params?: Record<string, unknown>
    position?: { x?: number; y?: number }
}

export interface StrategyIr {
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

export interface StrategyValidation {
    status: string
    blocking_errors?: Array<{ group: string; message: string }>
    warnings?: Array<{ group: string; message: string }>
    required_history?: { label?: string; candles?: number }
    hook_readiness?: Array<{ name: string; ready: boolean; message: string }>
}

export interface StrategyPaletteNode {
    type: string
    label: string
    category: string
    description: string
    params: Record<string, unknown>
    documentation_url?: string
}

export interface StrategyDetail extends StrategySummary {
    ir: StrategyIr
    validation: StrategyValidation
    explanation: string
    palette: StrategyPaletteNode[]
}

export interface StrategyListPayload {
    strategies: StrategySummary[]
    palette: StrategyPaletteNode[]
}
