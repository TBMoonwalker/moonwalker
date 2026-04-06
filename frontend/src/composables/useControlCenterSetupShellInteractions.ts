import type { ControlCenterTarget } from '../control-center/types'

interface UseControlCenterSetupShellInteractionsOptions {
    handleSetupTaskSelect: (target: ControlCenterTarget) => Promise<void>
    isSetupTaskExpanded: (target: ControlCenterTarget) => boolean
    isInteractiveTarget?: (target: EventTarget | null) => boolean
}

function defaultIsInteractiveTarget(target: EventTarget | null): boolean {
    return (
        target instanceof Element &&
        target.closest('button, a, input, select, textarea, label, [role="button"]') !==
            null
    )
}

export function useControlCenterSetupShellInteractions(
    options: UseControlCenterSetupShellInteractionsOptions,
) {
    const isInteractiveTarget =
        options.isInteractiveTarget ?? defaultIsInteractiveTarget

    async function handleSetupSectionShellClick(
        target: ControlCenterTarget,
        event: MouseEvent,
    ): Promise<void> {
        if (
            options.isSetupTaskExpanded(target) ||
            isInteractiveTarget(event.target)
        ) {
            return
        }
        await options.handleSetupTaskSelect(target)
    }

    return {
        handleSetupSectionShellClick,
    }
}
