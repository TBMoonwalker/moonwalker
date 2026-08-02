import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import {
    createBlankStrategy,
    deleteStrategy,
    duplicateStrategy,
    fetchStrategyDetail,
    fetchStrategyLibrary,
    isStrategyConflict,
    saveStrategyVersion,
    validateStrategy,
} from '../api/strategyBuilder'
import { extractApiErrorMessage } from '../helpers/apiErrors'
import {
    autoAlignStrategyGraph,
    coerceStrategyParam,
    normalizeComparisonPort,
    strategyNodeTitle,
} from '../helpers/strategyBuilderGraph'
import type {
    StrategyDetail,
    StrategyNode,
    StrategySummary,
    StrategyValidation,
} from '../types/strategyBuilder'
import { useStrategyRete } from './useStrategyRete'

interface StrategyBuilderWorkspaceOptions {
    confirmDelete: (strategyName: string) => Promise<boolean>
}

const VALIDATION_DEBOUNCE_MS = 200

export function useStrategyBuilderWorkspace(
    options: StrategyBuilderWorkspaceOptions,
) {
    const strategies = ref<StrategySummary[]>([])
    const palette = ref<StrategyDetail['palette']>([])
    const selectedSlug = ref<string | null>(null)
    const selectedDetail = ref<StrategyDetail | null>(null)
    const selectedNodeId = ref<string | null>(null)
    const loading = ref(false)
    const saving = ref(false)
    const errorMessage = ref<string | null>(null)
    const saveMessage = ref<string | null>(null)
    const draftName = ref('')
    const draftDescription = ref('')
    const draftConflict = ref(false)
    const reteHost = ref<HTMLElement | null>(null)
    let validationGeneration = 0
    let draftRefreshScheduled = false
    let validationRequested = false
    let validationTimer: ReturnType<typeof setTimeout> | null = null
    let activeValidationController: AbortController | null = null
    let workspaceDisposed = false

    const isReadOnly = computed(() => Boolean(selectedDetail.value?.is_builtin))
    const selectedNode = computed(() => {
        const nodes = selectedDetail.value?.ir.nodes ?? []
        return (
            nodes.find((node) => node.id === selectedNodeId.value) ??
            nodes[0] ??
            null
        )
    })
    const validation = computed(
        () =>
            selectedDetail.value?.validation ??
            ({ status: 'empty' } as StrategyValidation),
    )
    const canSave = computed(
        () =>
            Boolean(selectedDetail.value) &&
            !isReadOnly.value &&
            validation.value.status === 'valid' &&
            !saving.value,
    )

    function nodeTitle(node: StrategyNode): string {
        const detail = selectedDetail.value
        return detail
            ? strategyNodeTitle(node, detail.ir)
            : node.label || node.type
    }

    const {
        ready: reteReady,
        error: reteError,
        renderGraph: renderReteGraph,
        destroy: destroyRete,
    } = useStrategyRete({
        host: reteHost,
        detail: selectedDetail,
        selectedNodeId,
        titleForNode: nodeTitle,
    })

    function bindReteHost(host: HTMLElement | null): void {
        reteHost.value = host
        if (host && selectedDetail.value) {
            void renderReteGraph()
        }
    }

    onMounted(async () => {
        await loadStrategies()
    })

    onUnmounted(() => {
        workspaceDisposed = true
        if (validationTimer !== null) {
            clearTimeout(validationTimer)
            validationTimer = null
        }
        activeValidationController?.abort()
        activeValidationController = null
        validationGeneration += 1
        destroyRete()
    })

    watch(selectedDetail, async () => {
        if (validationTimer !== null) {
            clearTimeout(validationTimer)
            validationTimer = null
        }
        activeValidationController?.abort()
        activeValidationController = null
        validationGeneration += 1
        const detail = selectedDetail.value
        draftName.value = detail?.ir.name ?? ''
        draftDescription.value = detail?.ir.description ?? ''
        const currentNodeStillExists = detail?.ir.nodes?.some(
            (node) => node.id === selectedNodeId.value,
        )
        if (!currentNodeStillExists) {
            selectedNodeId.value =
                detail?.ir.root ?? detail?.ir.nodes?.[0]?.id ?? null
        }
        await renderReteGraph()
    })

    async function loadStrategies(selectSlug?: string): Promise<void> {
        loading.value = true
        errorMessage.value = null
        try {
            const response = await fetchStrategyLibrary()
            strategies.value = response.strategies
            palette.value = response.palette
            const nextSlug =
                selectSlug ??
                selectedSlug.value ??
                response.strategies.find((strategy) => strategy.is_builtin)
                    ?.slug ??
                response.strategies[0]?.slug ??
                null
            if (nextSlug) {
                await selectStrategy(nextSlug)
            }
        } catch (error) {
            errorMessage.value = extractApiErrorMessage(
                error,
                'Strategy library could not be loaded.',
            )
        } finally {
            loading.value = false
        }
    }

    async function selectStrategy(slug: string): Promise<void> {
        selectedSlug.value = slug
        saveMessage.value = null
        draftConflict.value = false
        try {
            const response = await fetchStrategyDetail(slug)
            selectedDetail.value = response
            if (response.palette?.length) {
                palette.value = response.palette
            }
        } catch (error) {
            errorMessage.value = extractApiErrorMessage(
                error,
                'Strategy could not be opened.',
            )
        }
    }

    async function duplicateSelected(): Promise<void> {
        const detail = selectedDetail.value
        if (!detail || saving.value) {
            return
        }
        saving.value = true
        saveMessage.value = null
        try {
            const response = await duplicateStrategy(
                detail.slug,
                `${detail.name} copy`,
            )
            await loadStrategies(response.slug)
            saveMessage.value =
                'Custom copy created. Edit the inspector, then save a new active version.'
        } catch (error) {
            errorMessage.value = extractApiErrorMessage(
                error,
                'Strategy could not be duplicated.',
            )
        } finally {
            saving.value = false
        }
    }

    async function createBlank(): Promise<void> {
        if (saving.value) {
            return
        }
        saving.value = true
        saveMessage.value = null
        try {
            const response = await createBlankStrategy('Custom strategy')
            await loadStrategies(response.slug)
            saveMessage.value =
                'Empty custom strategy created. Add graph nodes, then choose a decision node.'
        } catch (error) {
            errorMessage.value = extractApiErrorMessage(
                error,
                'Strategy could not be created.',
            )
        } finally {
            saving.value = false
        }
    }

    async function deleteSelected(): Promise<void> {
        const detail = selectedDetail.value
        if (!detail || detail.is_builtin || saving.value) {
            return
        }
        if (!(await options.confirmDelete(detail.name))) {
            return
        }
        saving.value = true
        saveMessage.value = null
        try {
            await deleteStrategy(detail.slug)
            selectedSlug.value = null
            selectedDetail.value = null
            await loadStrategies()
            saveMessage.value = 'Custom strategy deleted.'
        } catch (error) {
            errorMessage.value = extractApiErrorMessage(
                error,
                'Strategy could not be deleted.',
            )
        } finally {
            saving.value = false
        }
    }

    async function validateDraft(): Promise<void> {
        const detail = selectedDetail.value
        if (!detail) {
            return
        }
        if (validationTimer !== null) {
            clearTimeout(validationTimer)
            validationTimer = null
        }
        activeValidationController?.abort()
        const controller = new AbortController()
        activeValidationController = controller
        const generation = ++validationGeneration
        applyDraftText()
        try {
            const nextValidation = await validateStrategy(
                detail.ir,
                controller.signal,
            )
            if (
                generation !== validationGeneration ||
                selectedDetail.value !== detail
            ) {
                return
            }
            detail.validation = nextValidation
        } catch (error) {
            if (
                generation !== validationGeneration ||
                selectedDetail.value !== detail
            ) {
                return
            }
            errorMessage.value = extractApiErrorMessage(
                error,
                'Strategy validation failed.',
            )
        } finally {
            if (activeValidationController === controller) {
                activeValidationController = null
            }
        }
    }

    function scheduleValidation(): void {
        activeValidationController?.abort()
        activeValidationController = null
        validationGeneration += 1
        if (validationTimer !== null) {
            clearTimeout(validationTimer)
        }
        validationTimer = setTimeout(() => {
            validationTimer = null
            if (!workspaceDisposed) {
                void validateDraft()
            }
        }, VALIDATION_DEBOUNCE_MS)
    }

    function scheduleDraftRefresh(validate = true): void {
        validationRequested ||= validate
        if (draftRefreshScheduled) {
            return
        }
        draftRefreshScheduled = true
        queueMicrotask(() => {
            draftRefreshScheduled = false
            if (workspaceDisposed) {
                return
            }
            const shouldValidate = validationRequested
            validationRequested = false
            if (shouldValidate) {
                scheduleValidation()
            }
            void renderReteGraph()
        })
    }

    async function saveActiveVersion(): Promise<void> {
        const detail = selectedDetail.value
        if (!detail || !canSave.value) {
            return
        }
        saving.value = true
        saveMessage.value = null
        draftConflict.value = false
        applyDraftText()
        try {
            const response = await saveStrategyVersion(
                detail.slug,
                detail.ir,
                detail.lock_version,
            )
            selectedDetail.value = response
            await loadStrategies(response.slug)
            saveMessage.value = `Saved active version v${response.active_version}.`
        } catch (error) {
            if (isStrategyConflict(error)) {
                draftConflict.value = true
            }
            errorMessage.value = extractApiErrorMessage(
                error,
                'Strategy could not be saved.',
            )
        } finally {
            saving.value = false
        }
    }

    function applyDraftText(): void {
        const detail = selectedDetail.value
        if (!detail || isReadOnly.value) {
            return
        }
        detail.ir.name = draftName.value.trim() || detail.name
        detail.ir.description = draftDescription.value.trim()
    }

    function updateNodeParam(key: string, value: string): void {
        const detail = selectedDetail.value
        const node = selectedNode.value
        if (!detail || !node || isReadOnly.value) {
            return
        }
        node.params = {
            ...(node.params ?? {}),
            [key]: coerceStrategyParam(value),
        }
        scheduleDraftRefresh()
    }

    function updateNodeParamValue(key: string, value: unknown): void {
        const detail = selectedDetail.value
        const node = selectedNode.value
        if (!detail || !node || isReadOnly.value || value === null) {
            return
        }
        node.params = {
            ...(node.params ?? {}),
            [key]: value,
        }
        scheduleDraftRefresh()
    }

    function updateIndicatorSelection(
        value: string | number | null,
    ): void {
        const detail = selectedDetail.value
        const node = selectedNode.value
        if (!detail || !node || isReadOnly.value || value === null) {
            return
        }
        const indicator = String(value)
        const nextParams: Record<string, unknown> = {
            ...(node.params ?? {}),
            indicator,
        }
        if (
            indicator === 'ema' ||
            indicator === 'rsi' ||
            indicator.startsWith('bollinger_')
        ) {
            delete nextParams.fast_period
            delete nextParams.slow_period
            delete nextParams.signal_period
            nextParams.length = Number(
                nextParams.length || (indicator === 'rsi' ? 14 : 20),
            )
            nextParams.sample = String(nextParams.sample || 'current')
            if (indicator.startsWith('bollinger_')) {
                nextParams.standard_deviations = Number(
                    nextParams.standard_deviations || 2,
                )
            } else {
                delete nextParams.standard_deviations
            }
        } else if (indicator.startsWith('macd_')) {
            delete nextParams.length
            delete nextParams.standard_deviations
            nextParams.sample = String(nextParams.sample || 'current')
            nextParams.fast_period = Number(nextParams.fast_period || 12)
            nextParams.slow_period = Number(nextParams.slow_period || 26)
            nextParams.signal_period = Number(nextParams.signal_period || 9)
        } else {
            delete nextParams.length
            delete nextParams.sample
            delete nextParams.standard_deviations
            delete nextParams.fast_period
            delete nextParams.slow_period
            delete nextParams.signal_period
        }
        node.params = nextParams
        scheduleDraftRefresh()
    }

    function addNodeFromPalette(type: string): void {
        const detail = selectedDetail.value
        const paletteNode = palette.value.find((item) => item.type === type)
        if (!detail || !paletteNode || isReadOnly.value) {
            return
        }
        const nextIndex = detail.ir.nodes.length + 1
        const node: StrategyNode = {
            id: `${type}_${nextIndex}`,
            type,
            label: paletteNode.label,
            params: { ...paletteNode.params },
            position: { x: 220 + nextIndex * 32, y: 90 + nextIndex * 38 },
        }
        detail.ir.nodes.push(node)
        if (!detail.ir.root) {
            detail.ir.root = node.id
        }
        selectedNodeId.value = node.id
        scheduleDraftRefresh()
    }

    function autoAlignGraph(): void {
        const detail = selectedDetail.value
        if (!detail) {
            return
        }
        autoAlignStrategyGraph(detail.ir, nodeTitle)
        scheduleDraftRefresh(false)
    }

    function connectSelectedToDecision(): void {
        const detail = selectedDetail.value
        const node = selectedNode.value
        if (!detail || !node || isReadOnly.value || !detail.ir.root) {
            return
        }
        if (node.id === detail.ir.root) {
            return
        }
        const exists = detail.ir.connections.some(
            (connection) =>
                String(connection.source ?? '') === node.id &&
                String(connection.target ?? '') === detail.ir.root,
        )
        if (!exists) {
            detail.ir.connections.push({
                source: node.id,
                target: detail.ir.root,
            })
        }
        scheduleDraftRefresh()
    }

    function updateSelectedInput(
        port: string,
        sourceId: string | number | null,
    ): void {
        const detail = selectedDetail.value
        const node = selectedNode.value
        if (!detail || !node || isReadOnly.value) {
            return
        }
        const canonicalPort = normalizeComparisonPort(port)
        detail.ir.connections = detail.ir.connections.filter((item) => {
            const target = String(item.target ?? item.targetNode ?? '')
            const targetInput = normalizeComparisonPort(
                String(
                    item.target_input ??
                        item.targetInput ??
                        item.input ??
                        '',
                ),
            )
            return !(target === node.id && targetInput === canonicalPort)
        })
        if (sourceId) {
            detail.ir.connections.push({
                source: String(sourceId),
                target: node.id,
                target_input: canonicalPort,
            })
        }
        scheduleDraftRefresh()
    }

    function setDecisionNode(nodeId: string): void {
        const detail = selectedDetail.value
        if (!detail || isReadOnly.value) {
            return
        }
        detail.ir.root = nodeId
        selectedNodeId.value = nodeId
        saveMessage.value = 'Decision node set.'
        scheduleDraftRefresh()
    }

    return {
        addNodeFromPalette,
        autoAlignGraph,
        bindReteHost,
        canSave,
        connectSelectedToDecision,
        createBlank,
        deleteSelected,
        draftConflict,
        draftDescription,
        draftName,
        duplicateSelected,
        errorMessage,
        isReadOnly,
        loading,
        nodeTitle,
        palette,
        reteError,
        reteReady,
        saveActiveVersion,
        saveMessage,
        saving,
        selectedDetail,
        selectedNode,
        selectedNodeId,
        selectedSlug,
        selectStrategy,
        setDecisionNode,
        strategies,
        updateIndicatorSelection,
        updateNodeParam,
        updateNodeParamValue,
        updateSelectedInput,
        validateDraft,
        validation,
    }
}
