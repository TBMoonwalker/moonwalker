export const CONTROL_CENTER_MODES = [
    'overview',
    'setup',
    'advanced',
    'utilities',
] as const

export type ControlCenterMode = (typeof CONTROL_CENTER_MODES)[number]

export const CONTROL_CENTER_TARGETS = [
    'general',
    'exchange',
    'signal',
    'filter',
    'dca',
    'autopilot',
    'monitoring',
    'indicator',
    'backup-restore',
    'live-activation',
] as const

export type ControlCenterTarget = (typeof CONTROL_CENTER_TARGETS)[number]

export type ControlCenterViewKind =
    | 'first_run'
    | 'healthy'
    | 'attention_needed'
    | 'rescue'
    | 'post_action_success'

export type SharedConfigPayload = Record<string, unknown>

export interface ControlCenterRouteState {
    mode: ControlCenterMode
    target: ControlCenterTarget | null
}

export interface ControlCenterTaskPresentation {
    target: ControlCenterTarget
    title: string
    summary: string
    defaultMode: ControlCenterMode
    modes: ControlCenterMode[]
    sectionId: string
    emphasis: 'primary' | 'secondary'
}

export interface ControlCenterBlocker {
    key: string
    title: string
    description: string
    mode: ControlCenterMode
    target: ControlCenterTarget
}

export interface ControlCenterReadiness {
    complete: boolean
    firstRun: boolean
    attentionNeeded: boolean
    blockers: ControlCenterBlocker[]
    nextMode: ControlCenterMode
    nextTarget: ControlCenterTarget | null
    dryRun: boolean
    configuredEssentials: number
}

export interface ControlCenterTransitionIntent {
    kind: 'save' | 'activate_live' | 'restore' | 'retry' | 'fix_this'
    status: 'success' | 'error' | 'blocked' | 'pending'
    message: string
    at: number
    mode?: ControlCenterMode
    target?: ControlCenterTarget | null
    blockers?: ControlCenterBlocker[]
}

export interface ControlCenterViewState {
    kind: ControlCenterViewKind
    badge: string
    title: string
    summary: string
    defaultMode: ControlCenterMode
}

export interface ConfigFreshnessPayload {
    updated_at: string | null
}
