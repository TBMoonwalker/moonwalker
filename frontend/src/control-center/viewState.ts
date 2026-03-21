import type {
    ControlCenterReadiness,
    ControlCenterTransitionIntent,
    ControlCenterViewState,
} from './types'

interface DeriveControlCenterViewStateOptions {
    loadError: string | null
    readiness: ControlCenterReadiness
    transition: ControlCenterTransitionIntent | null
    now?: number
}

const SUCCESS_LANDING_WINDOW_MS = 8000

function isRecentSuccess(
    transition: ControlCenterTransitionIntent | null,
    now: number,
): boolean {
    if (!transition || transition.status !== 'success') {
        return false
    }
    return now - transition.at <= SUCCESS_LANDING_WINDOW_MS
}

export function deriveControlCenterViewState(
    options: DeriveControlCenterViewStateOptions,
): ControlCenterViewState {
    const now = options.now ?? Date.now()
    if (options.loadError) {
        return {
            kind: 'rescue',
            badge: 'Recovery',
            title: 'Control Center needs a fresh config load',
            summary:
                'Moonwalker could not load the latest configuration. Retry the shared snapshot before editing or activating anything.',
            defaultMode: 'overview',
        }
    }

    if (isRecentSuccess(options.transition, now)) {
        return {
            kind: 'post_action_success',
            badge: 'Updated',
            title: options.transition?.message || 'Control Center updated',
            summary:
                'The shared workspace is refreshed. Review the current status before making the next operator action.',
            defaultMode: options.transition?.mode ?? 'overview',
        }
    }

    if (options.readiness.firstRun) {
        return {
            kind: 'first_run',
            badge: 'Setup',
            title: 'Finish a safe dry-run setup',
            summary:
                'Start with the essentials needed to run Moonwalker safely in dry run before exposing advanced tuning.',
            defaultMode: 'setup',
        }
    }

    if (options.readiness.attentionNeeded) {
        return {
            kind: 'attention_needed',
            badge: 'Attention',
            title: 'Setup still needs attention',
            summary:
                'Moonwalker has partial configuration, but the current setup is not yet safe enough to trust end to end.',
            defaultMode: 'overview',
        }
    }

    if (options.readiness.dryRun) {
        return {
            kind: 'healthy',
            badge: 'Ready',
            title: 'Safe dry-run setup is ready',
            summary:
                'The essential runtime is configured. Review the calm overview or activate live trading through the guarded action when you are ready.',
            defaultMode: 'overview',
        }
    }

    return {
        kind: 'healthy',
        badge: 'Live',
        title: 'Live trading is active',
        summary:
            'Moonwalker is operating live. Use the Control Center to review readiness, recover from issues, or adjust operator settings carefully.',
        defaultMode: 'overview',
    }
}
