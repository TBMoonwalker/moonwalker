import { computed, ref, type ComputedRef } from 'vue'

import {
    buildSetupEntryChoiceHistoryState,
    getSetupEntryChoiceFromHistoryState,
    parseSetupEntryChoice,
    type SetupEntryChoice,
} from '../control-center/setupEntryHistory'
import {
    getTaskPresentation,
    getTasksForMode,
} from '../control-center/taskRegistry'
import type {
    ControlCenterBlocker,
    ControlCenterMode,
    ControlCenterReadiness,
    ControlCenterRouteState,
    ControlCenterTarget,
} from '../control-center/types'
import { trackUiEvent } from '../utils/uiTelemetry'

type UiTelemetryPayload = Record<
    string,
    string | number | boolean | null | undefined
>

export type SetupStyle = 'guided' | 'full'

interface LocalStorageLike {
    getItem: (key: string) => string | null
    removeItem: (key: string) => void
    setItem: (key: string, value: string) => void
}

interface HistoryLike {
    state: unknown
    pushState: (data: unknown, unused: string, url?: string | URL | null) => void
    replaceState: (data: unknown, unused: string, url?: string | URL | null) => void
}

interface LocationLike {
    href: string
}

interface WindowLike {
    history: HistoryLike
    localStorage: LocalStorageLike
    location: LocationLike
}

interface UseControlCenterSetupFlowOptions {
    focusTarget: (target: ControlCenterTarget) => Promise<boolean>
    guideToTarget: (target: ControlCenterTarget) => Promise<void>
    handleActivateLiveTrading: () => Promise<void>
    navigateToControlCenter: (
        mode: ControlCenterMode,
        target?: ControlCenterTarget | null,
    ) => Promise<void>
    readiness: ComputedRef<ControlCenterReadiness>
    routeState: ComputedRef<ControlCenterRouteState>
    visibleBlockers: ComputedRef<ControlCenterBlocker[]>
    trackEvent?: (eventName: string, payload?: UiTelemetryPayload) => void
    window?: WindowLike | null
}

const CONTROL_CENTER_ENTRY_CHOICE_KEY = 'moonwalker.controlCenter.entryChoice'
const CONTROL_CENTER_SETUP_STYLE_KEY = 'moonwalker.controlCenter.setupStyle'

function getWindowLike(windowOverride?: WindowLike | null): WindowLike | null {
    if (windowOverride) {
        return windowOverride
    }
    return typeof window === 'undefined' ? null : window
}

function getStoredSetupEntryChoice(
    windowRef: WindowLike | null,
    preferenceKey: string,
): SetupEntryChoice | null {
    if (!windowRef) {
        return null
    }
    return parseSetupEntryChoice(windowRef.localStorage.getItem(preferenceKey))
}

function storeSetupEntryChoice(
    windowRef: WindowLike | null,
    preferenceKey: string,
    choice: SetupEntryChoice | null,
): void {
    if (!windowRef) {
        return
    }
    if (!choice) {
        windowRef.localStorage.removeItem(preferenceKey)
        return
    }
    windowRef.localStorage.setItem(preferenceKey, choice)
}

function getStoredSetupStyle(
    windowRef: WindowLike | null,
    preferenceKey: string,
): SetupStyle {
    if (!windowRef) {
        return 'guided'
    }
    return windowRef.localStorage.getItem(preferenceKey) === 'full'
        ? 'full'
        : 'guided'
}

function storeSetupStyle(
    windowRef: WindowLike | null,
    preferenceKey: string,
    style: SetupStyle,
): void {
    if (!windowRef) {
        return
    }
    windowRef.localStorage.setItem(preferenceKey, style)
}

function defaultTrackEvent(
    eventName: string,
    payload?: UiTelemetryPayload,
): void {
    trackUiEvent(eventName, payload)
}

export function useControlCenterSetupFlow(
    options: UseControlCenterSetupFlowOptions,
) {
    const setupEntryChoice = ref<SetupEntryChoice | null>(null)
    const setupStyle = ref<SetupStyle>('guided')
    const trackEvent = options.trackEvent ?? defaultTrackEvent

    const isPreReadiness = computed(() => !options.readiness.value.complete)
    const setupShowsAdvancedFields = computed(
        () => isPreReadiness.value && setupStyle.value === 'full',
    )
    const showSetupEntryGate = computed(
        () => options.readiness.value.firstRun && setupEntryChoice.value === null,
    )
    const showRestoreSetupFlow = computed(
        () =>
            options.readiness.value.firstRun &&
            setupEntryChoice.value === 'restore',
    )
    const showSetupStyleSelector = computed(
        () =>
            isPreReadiness.value &&
            !showSetupEntryGate.value &&
            !showRestoreSetupFlow.value,
    )
    const setupTasks = computed(() => getTasksForMode('setup'))
    const activeSetupTarget = computed<ControlCenterTarget>(() => {
        const requestedTarget = options.routeState.value.target
        if (
            requestedTarget &&
            getTaskPresentation(requestedTarget).modes.includes('setup')
        ) {
            return requestedTarget
        }
        const nextTarget = options.readiness.value.nextTarget
        if (nextTarget && getTaskPresentation(nextTarget).modes.includes('setup')) {
            return nextTarget
        }
        return 'general'
    })

    function rememberSetupEntryChoice(choice: SetupEntryChoice | null): void {
        setupEntryChoice.value = choice
        storeSetupEntryChoice(
            getWindowLike(options.window),
            CONTROL_CENTER_ENTRY_CHOICE_KEY,
            choice,
        )
    }

    function syncSetupEntryChoiceHistory(
        choice: SetupEntryChoice | null,
        replace = false,
    ): void {
        const windowRef = getWindowLike(options.window)
        if (!windowRef) {
            return
        }
        const nextState = buildSetupEntryChoiceHistoryState(
            windowRef.history.state,
            choice,
        )
        if (replace) {
            windowRef.history.replaceState(nextState, '', windowRef.location.href)
            return
        }
        windowRef.history.pushState(nextState, '', windowRef.location.href)
    }

    function rememberSetupStyle(style: SetupStyle): void {
        setupStyle.value = style
        storeSetupStyle(
            getWindowLike(options.window),
            CONTROL_CENTER_SETUP_STYLE_KEY,
            style,
        )
    }

    function initializeSetupFlow(): void {
        const windowRef = getWindowLike(options.window)
        if (!windowRef) {
            return
        }
        const historySetupEntryChoice = getSetupEntryChoiceFromHistoryState(
            windowRef.history.state,
        )
        rememberSetupEntryChoice(
            historySetupEntryChoice ??
                getStoredSetupEntryChoice(
                    windowRef,
                    CONTROL_CENTER_ENTRY_CHOICE_KEY,
                ),
        )
        syncSetupEntryChoiceHistory(setupEntryChoice.value, true)
        rememberSetupStyle(
            getStoredSetupStyle(windowRef, CONTROL_CENTER_SETUP_STYLE_KEY),
        )
    }

    function syncSetupChoiceForReadiness(firstRun: boolean): void {
        if (!firstRun && setupEntryChoice.value === 'restore') {
            rememberSetupEntryChoice('new')
            syncSetupEntryChoiceHistory('new', true)
        }
    }

    function handleSetupEntryChoicePopState(): void {
        const windowRef = getWindowLike(options.window)
        if (!windowRef) {
            return
        }
        rememberSetupEntryChoice(
            getSetupEntryChoiceFromHistoryState(windowRef.history.state),
        )
    }

    function findSetupBlocker(
        target: ControlCenterTarget,
    ): ControlCenterBlocker | undefined {
        return options.visibleBlockers.value.find(
            (blocker) => blocker.target === target,
        )
    }

    function isSetupTaskExpanded(target: ControlCenterTarget): boolean {
        return setupStyle.value === 'full' || activeSetupTarget.value === target
    }

    function getSetupTaskStatus(target: ControlCenterTarget): {
        label: string
        type: 'default' | 'info' | 'warning' | 'success'
    } {
        if (activeSetupTarget.value === target) {
            return {
                label: 'Current',
                type: 'info',
            }
        }

        if (findSetupBlocker(target)) {
            return {
                label: 'Needs attention',
                type: 'warning',
            }
        }

        return {
            label: 'Ready',
            type: 'success',
        }
    }

    function getSetupTaskSummary(target: ControlCenterTarget): string {
        const blocker = findSetupBlocker(target)
        if (blocker) {
            return blocker.description
        }
        if (activeSetupTarget.value === target) {
            return 'Current setup step.'
        }
        return 'Saved and ready to review.'
    }

    async function handleSetupEntryChoice(
        choice: SetupEntryChoice,
    ): Promise<void> {
        if (setupEntryChoice.value === choice) {
            return
        }
        rememberSetupEntryChoice(choice)
        syncSetupEntryChoiceHistory(choice)
        trackEvent('control_center_setup_entry_selected', { choice })
        if (choice === 'new') {
            await options.focusTarget(activeSetupTarget.value)
        }
    }

    function handleSetupStyleChange(style: SetupStyle): void {
        rememberSetupStyle(style)
        trackEvent('control_center_setup_style_selected', { style })
    }

    async function handleSetupTaskSelect(
        target: ControlCenterTarget,
    ): Promise<void> {
        await options.navigateToControlCenter('setup', target)
    }

    async function handleMissionPrimaryAction(): Promise<void> {
        if (!options.readiness.value.complete) {
            await options.guideToTarget(
                options.readiness.value.nextTarget ?? 'exchange',
            )
            return
        }
        if (options.readiness.value.dryRun) {
            await options.handleActivateLiveTrading()
            return
        }
        await options.navigateToControlCenter('overview')
    }

    return {
        activeSetupTarget,
        findSetupBlocker,
        getSetupTaskStatus,
        getSetupTaskSummary,
        handleMissionPrimaryAction,
        handleSetupEntryChoice,
        handleSetupEntryChoicePopState,
        handleSetupStyleChange,
        handleSetupTaskSelect,
        initializeSetupFlow,
        isSetupTaskExpanded,
        setupEntryChoice,
        setupShowsAdvancedFields,
        setupStyle,
        setupTasks,
        showRestoreSetupFlow,
        showSetupEntryGate,
        showSetupStyleSelector,
        syncSetupChoiceForReadiness,
    }
}
