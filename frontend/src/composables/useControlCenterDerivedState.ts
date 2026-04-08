import { computed, type Ref } from 'vue'

import { deriveControlCenterConfigTrustState } from '../control-center/configTrust'
import { deriveControlCenterReadiness } from '../control-center/readiness'
import { normalizeControlCenterRouteState } from '../control-center/routeState'
import type {
    ControlCenterTransitionIntent,
    SharedConfigPayload,
} from '../control-center/types'
import { deriveControlCenterViewState } from '../control-center/viewState'

type SnapshotLoadState = 'idle' | 'loading' | 'ready' | 'error'

interface SnapshotStoreLike {
    hasKnownNewerSnapshot: { value: boolean }
    isHydrated: { value: boolean }
    latestKnownUpdatedAt: { value: string | null }
    loadError: { value: string | null }
    loadState: { value: SnapshotLoadState }
    snapshot: Ref<SharedConfigPayload | null>
}

interface UseControlCenterDerivedStateOptions {
    hasUnsavedChanges: () => boolean
    loadRescueMessage: Ref<string | null>
    requestedMode: () => unknown
    requestedTarget: () => unknown
    snapshotStore: SnapshotStoreLike
    transitionIntent: Ref<ControlCenterTransitionIntent | null>
}

export function useControlCenterDerivedState(
    options: UseControlCenterDerivedStateOptions,
) {
    const effectiveLoadError = computed(
        () => options.loadRescueMessage.value ?? options.snapshotStore.loadError.value,
    )
    const readiness = computed(() =>
        deriveControlCenterReadiness(options.snapshotStore.snapshot.value),
    )
    const visibleBlockers = computed(() => {
        if (
            options.transitionIntent.value?.status === 'blocked' &&
            options.transitionIntent.value.blockers &&
            options.transitionIntent.value.blockers.length > 0
        ) {
            return options.transitionIntent.value.blockers
        }
        return readiness.value.blockers
    })
    const viewState = computed(() =>
        deriveControlCenterViewState({
            loadError: effectiveLoadError.value,
            readiness: readiness.value,
            transition: options.transitionIntent.value,
        }),
    )
    const routeState = computed(() =>
        normalizeControlCenterRouteState({
            requestedMode: options.requestedMode(),
            requestedTarget: options.requestedTarget(),
            fallbackMode: viewState.value.defaultMode,
        }),
    )
    const configTrustState = computed(() =>
        deriveControlCenterConfigTrustState({
            hasKnownNewerSnapshot:
                options.snapshotStore.hasKnownNewerSnapshot.value,
            hasUnsavedChanges: options.hasUnsavedChanges(),
            isHydrated: options.snapshotStore.isHydrated.value,
            latestKnownUpdatedAt: options.snapshotStore.latestKnownUpdatedAt.value,
            loadState: options.snapshotStore.loadState.value,
        }),
    )

    return {
        configTrustState,
        effectiveLoadError,
        readiness,
        routeState,
        viewState,
        visibleBlockers,
    }
}
