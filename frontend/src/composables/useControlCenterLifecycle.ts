import {
    onMounted,
    onUnmounted,
    watch,
    type ComputedRef,
    type Ref,
} from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

import type { OperationResult } from '../control-center/operationResults'
import type {
    ControlCenterReadiness,
    ControlCenterRouteState,
    ControlCenterTarget,
} from '../control-center/types'

type DiscardReason = 'route_leave'

interface LifecycleDocumentLike {
    hidden: boolean
}

interface LifecycleWindowLike {
    addEventListener: (name: string, listener: EventListener) => void
    removeEventListener: (name: string, listener: EventListener) => void
    setInterval: (handler: () => void, timeout: number) => number
    clearInterval: (id: number) => void
}

interface LifecycleSnapshotStoreLike {
    externalInvalidationToken: Ref<number>
}

interface LifecycleHookOptions {
    flush?: 'pre' | 'post' | 'sync'
}

interface LifecycleHooks {
    onBeforeRouteLeave: (guard: () => boolean | void) => void
    onMounted: (handler: () => void | Promise<void>) => void
    onUnmounted: (handler: () => void) => void
    watch: <T>(
        source: () => T,
        callback: (value: T, previousValue: T | undefined) => void | Promise<void>,
        options?: LifecycleHookOptions,
    ) => void
}

interface UseControlCenterLifecycleOptions {
    checkForExternalConfigChanges: () => Promise<void>
    confirmDiscardUnsavedChanges: (reason: DiscardReason) => boolean
    disposeFeedback: () => void
    focusTarget: (target: ControlCenterTarget) => Promise<boolean>
    handleBeforeUnload: EventListener
    handleDetectedExternalConfigChange: (shouldAnnounce: boolean) => Promise<void>
    handleGlobalKeydown: EventListener
    handleSetupEntryChoicePopState: EventListener
    initializeClientTimezoneOptions: () => void
    initializeSetupFlow: () => void
    readiness: ComputedRef<ControlCenterReadiness>
    refreshWorkspaceFromSnapshot: (force?: boolean) => Promise<OperationResult>
    routeState: ComputedRef<ControlCenterRouteState>
    snapshotStore: LifecycleSnapshotStoreLike
    staleCheckIntervalMs: number
    syncSetupChoiceForReadiness: (firstRun: boolean) => void
    documentObject?: LifecycleDocumentLike | null
    hooks?: Partial<LifecycleHooks>
    windowObject?: LifecycleWindowLike | null
}

interface ControlCenterLifecycleHandlers {
    handleBeforeRouteLeave: () => boolean
    handleExternalInvalidationTokenChange: (
        nextToken: number,
        previousToken: number | undefined,
    ) => Promise<void>
    handleMounted: () => Promise<void>
    handleReadinessChange: (firstRun: boolean) => void
    handleRouteStateChange: () => Promise<void>
    handleUnmounted: () => void
}

function resolveDocumentObject(
    documentObject?: LifecycleDocumentLike | null,
): LifecycleDocumentLike | null {
    if (documentObject !== undefined) {
        return documentObject
    }
    return typeof document === 'undefined' ? null : document
}

function resolveWindowObject(
    windowObject?: LifecycleWindowLike | null,
): LifecycleWindowLike | null {
    if (windowObject !== undefined) {
        return windowObject
    }
    return typeof window === 'undefined' ? null : window
}

function defaultHooks(): LifecycleHooks {
    return {
        onBeforeRouteLeave,
        onMounted,
        onUnmounted,
        watch,
    }
}

export function createControlCenterLifecycleHandlers(
    options: UseControlCenterLifecycleOptions,
): ControlCenterLifecycleHandlers {
    const documentObject = resolveDocumentObject(options.documentObject)
    const windowObject = resolveWindowObject(options.windowObject)
    let staleCheckIntervalId: number | null = null

    async function handleRouteStateChange(): Promise<void> {
        const target = options.routeState.value.target
        if (!target) {
            return
        }
        await options.focusTarget(target)
    }

    function handleReadinessChange(firstRun: boolean): void {
        options.syncSetupChoiceForReadiness(firstRun)
    }

    async function handleExternalInvalidationTokenChange(
        nextToken: number,
        previousToken: number | undefined,
    ): Promise<void> {
        if (nextToken === 0 || nextToken === previousToken) {
            return
        }
        await options.handleDetectedExternalConfigChange(
            documentObject ? !documentObject.hidden : true,
        )
    }

    function handleBeforeRouteLeave(): boolean {
        return options.confirmDiscardUnsavedChanges('route_leave')
    }

    async function handleMounted(): Promise<void> {
        options.initializeClientTimezoneOptions()
        options.initializeSetupFlow()

        if (windowObject) {
            windowObject.addEventListener(
                'beforeunload',
                options.handleBeforeUnload,
            )
            windowObject.addEventListener('keydown', options.handleGlobalKeydown)
            windowObject.addEventListener(
                'focus',
                options.checkForExternalConfigChanges as EventListener,
            )
            windowObject.addEventListener(
                'popstate',
                options.handleSetupEntryChoicePopState,
            )
            staleCheckIntervalId = windowObject.setInterval(() => {
                void options.checkForExternalConfigChanges()
            }, options.staleCheckIntervalMs)
        }

        await options.refreshWorkspaceFromSnapshot(false)
        const target = options.routeState.value.target
        if (target) {
            await options.focusTarget(target)
        }
    }

    function handleUnmounted(): void {
        if (windowObject) {
            windowObject.removeEventListener(
                'beforeunload',
                options.handleBeforeUnload,
            )
            windowObject.removeEventListener(
                'keydown',
                options.handleGlobalKeydown,
            )
            windowObject.removeEventListener(
                'focus',
                options.checkForExternalConfigChanges as EventListener,
            )
            windowObject.removeEventListener(
                'popstate',
                options.handleSetupEntryChoicePopState,
            )
            if (staleCheckIntervalId !== null) {
                windowObject.clearInterval(staleCheckIntervalId)
                staleCheckIntervalId = null
            }
        }
        options.disposeFeedback()
    }

    return {
        handleBeforeRouteLeave,
        handleExternalInvalidationTokenChange,
        handleMounted,
        handleReadinessChange,
        handleRouteStateChange,
        handleUnmounted,
    }
}

export function useControlCenterLifecycle(
    options: UseControlCenterLifecycleOptions,
): void {
    const hooks = {
        ...defaultHooks(),
        ...options.hooks,
    }
    const handlers = createControlCenterLifecycleHandlers(options)

    hooks.watch(
        () => `${options.routeState.value.mode}:${options.routeState.value.target ?? ''}`,
        () => handlers.handleRouteStateChange(),
        { flush: 'post' },
    )

    hooks.watch(
        () => options.readiness.value.firstRun,
        (firstRun) => {
            handlers.handleReadinessChange(firstRun)
        },
    )

    hooks.watch(
        () => options.snapshotStore.externalInvalidationToken.value,
        (nextToken, previousToken) =>
            handlers.handleExternalInvalidationTokenChange(
                nextToken,
                previousToken,
            ),
    )

    hooks.onBeforeRouteLeave(handlers.handleBeforeRouteLeave)
    hooks.onMounted(handlers.handleMounted)
    hooks.onUnmounted(handlers.handleUnmounted)
}
