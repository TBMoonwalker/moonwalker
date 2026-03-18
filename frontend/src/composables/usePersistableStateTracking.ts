import { computed, ref } from 'vue'

export type PersistableState = Record<string, Record<string, unknown>>

interface UsePersistableStateTrackingOptions {
    buildState: () => PersistableState
    sectionLabels: Record<string, string>
}

function clonePersistableState(state: PersistableState): PersistableState {
    return JSON.parse(JSON.stringify(state)) as PersistableState
}

export function usePersistableStateTracking(
    options: UsePersistableStateTrackingOptions,
) {
    const baselineState = ref<PersistableState | null>(null)

    function syncBaselineState(): void {
        baselineState.value = clonePersistableState(options.buildState())
    }

    const changedSections = computed(() => {
        if (!baselineState.value) {
            return [] as string[]
        }

        const currentState = options.buildState()
        return Object.keys(currentState).filter(
            (section) =>
                JSON.stringify(currentState[section]) !==
                JSON.stringify(baselineState.value?.[section]),
        )
    })

    const changedSectionLabels = computed(() =>
        changedSections.value.map(
            (section) => options.sectionLabels[section] || section,
        ),
    )

    const isDirty = computed(() => changedSections.value.length > 0)

    return {
        baselineState,
        changedSectionLabels,
        changedSections,
        isDirty,
        syncBaselineState,
    }
}
