import type { ControlCenterConfigTrustState } from './types'

type SnapshotLoadState = 'idle' | 'loading' | 'ready' | 'error'

interface DeriveControlCenterConfigTrustStateOptions {
    hasKnownNewerSnapshot: boolean
    hasUnsavedChanges: boolean
    isHydrated: boolean
    latestKnownUpdatedAt: string | null
    loadState: SnapshotLoadState
}

export function deriveControlCenterConfigTrustState(
    options: DeriveControlCenterConfigTrustStateOptions,
): ControlCenterConfigTrustState {
    if (options.loadState === 'loading' || !options.isHydrated) {
        return {
            kind: 'checking',
            summary: 'Checking whether this page is using the latest saved configuration.',
            tone: 'info',
            updatedAt: options.latestKnownUpdatedAt,
        }
    }

    if (options.hasKnownNewerSnapshot && options.hasUnsavedChanges) {
        return {
            kind: 'stale_with_draft_conflict',
            summary:
                'Another tab or client saved a newer configuration. Reload before trusting this draft, or keep editing until you are ready to discard local changes.',
            tone: 'warning',
            updatedAt: options.latestKnownUpdatedAt,
        }
    }

    if (options.hasKnownNewerSnapshot) {
        return {
            kind: 'stale_but_safe',
            summary:
                'A newer configuration is available. This tab can reload safely because it has no pending draft changes.',
            tone: 'warning',
            updatedAt: options.latestKnownUpdatedAt,
        }
    }

    return {
        kind: 'trusted',
        summary: 'This page is using the latest saved configuration.',
        tone: 'success',
        updatedAt: options.latestKnownUpdatedAt,
    }
}
