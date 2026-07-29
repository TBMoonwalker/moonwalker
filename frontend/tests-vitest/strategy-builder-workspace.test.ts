import { flushPromises, mount } from '@vue/test-utils'
import { NDialogProvider } from 'naive-ui'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import StrategyBuilderWorkspace from '../src/components/control-center/StrategyBuilderWorkspace.vue'
import { useStrategyBuilderWorkspace } from '../src/composables/useStrategyBuilderWorkspace'
import type {
    StrategyDetail,
    StrategyPaletteNode,
    StrategySummary,
    StrategyValidation,
} from '../src/types/strategyBuilder'

const apiMocks = vi.hoisted(() => ({
    createBlankStrategy: vi.fn(),
    deleteStrategy: vi.fn(),
    duplicateStrategy: vi.fn(),
    fetchStrategyDetail: vi.fn(),
    fetchStrategyLibrary: vi.fn(),
    isStrategyConflict: vi.fn(),
    saveStrategyVersion: vi.fn(),
    validateStrategy: vi.fn(),
}))

vi.mock('../src/api/strategyBuilder', () => apiMocks)

vi.mock('../src/composables/useStrategyRete', async () => {
    const { ref } = await import('vue')
    return {
        useStrategyRete: () => ({
            ready: ref(true),
            error: ref<string | null>(null),
            renderGraph: vi.fn().mockResolvedValue(undefined),
            destroy: vi.fn(),
        }),
    }
})

const palette: StrategyPaletteNode[] = [
    {
        type: 'indicator',
        label: 'Indicator',
        category: 'Values',
        description: 'Technical indicator',
        params: { indicator: 'ema', length: 20, sample: 'current' },
    },
]

function summary(
    slug: string,
    name: string,
    isBuiltin: boolean,
): StrategySummary {
    return {
        slug,
        name,
        description: `${name} description`,
        kind: isBuiltin ? 'builtin' : 'custom',
        is_builtin: isBuiltin,
        duplicated_from: isBuiltin ? null : 'ema_cross',
        active_version: 1,
        draft_version: 1,
        lock_version: 1,
        validation_status: 'valid',
        available: true,
        missing_hooks: [],
    }
}

function detail(strategy: StrategySummary): StrategyDetail {
    return {
        ...strategy,
        ir: {
            schema_version: 1,
            slug: strategy.slug,
            name: strategy.name,
            description: strategy.description,
            kind: strategy.kind,
            root: 'decision',
            nodes: [
                {
                    id: 'ema',
                    type: 'indicator',
                    params: {
                        indicator: 'ema',
                        length: 20,
                        sample: 'current',
                    },
                },
                {
                    id: 'close',
                    type: 'close_price',
                    params: { sample: 'current' },
                },
                {
                    id: 'decision',
                    type: 'comparison',
                    params: { comparison: 'greater_than' },
                },
            ],
            connections: [
                {
                    source: 'ema',
                    target: 'decision',
                    target_input: 'value1',
                },
                {
                    source: 'close',
                    target: 'decision',
                    target_input: 'value2',
                },
            ],
        },
        validation: {
            status: 'valid',
            blocking_errors: [],
            hook_readiness: [
                { name: 'entry', ready: true, message: 'Ready' },
            ],
            required_history: { label: '20 candles', candles: 20 },
        },
        explanation: `${strategy.name} explanation`,
        palette,
    }
}

const builtin = summary('ema_cross', 'EMA cross', true)
const custom = summary('ema_cross_copy', 'EMA cross copy', false)

function mountWorkspace() {
    const Harness = defineComponent({
        setup: () => () =>
            h(NDialogProvider, null, {
                default: () => h(StrategyBuilderWorkspace),
            }),
    })
    return mount(Harness, { attachTo: document.body })
}

function mountWorkspaceState(
    confirmDelete = vi.fn().mockResolvedValue(true),
) {
    let state:
        | ReturnType<typeof useStrategyBuilderWorkspace>
        | undefined
    const Harness = defineComponent({
        setup() {
            state = useStrategyBuilderWorkspace({ confirmDelete })
            return () => h('div')
        },
    })
    const wrapper = mount(Harness)
    return {
        confirmDelete,
        get state() {
            if (!state) {
                throw new Error('workspace state was not initialized')
            }
            return state
        },
        wrapper,
    }
}

describe('StrategyBuilderWorkspace', () => {
    beforeEach(() => {
        for (const mock of Object.values(apiMocks)) {
            mock.mockReset()
        }
        apiMocks.fetchStrategyLibrary.mockResolvedValue({
            strategies: [builtin, custom],
            palette,
        })
        apiMocks.fetchStrategyDetail.mockImplementation((slug: string) =>
            Promise.resolve(detail(slug === custom.slug ? custom : builtin)),
        )
        apiMocks.duplicateStrategy.mockResolvedValue(detail(custom))
        apiMocks.validateStrategy.mockResolvedValue(detail(custom).validation)
        apiMocks.isStrategyConflict.mockReturnValue(false)
    })

    it('renders the split library, canvas, and inspector surfaces', async () => {
        const wrapper = mountWorkspace()
        await flushPromises()

        expect(wrapper.get('#strategy-builder-title').text()).toBe(
            'Strategy Builder',
        )
        expect(wrapper.get('[aria-label="Strategy library"]').text()).toContain(
            'EMA cross',
        )
        expect(wrapper.get('[aria-label="Strategy graph"]').text()).toContain(
            'Read-only built-in preview',
        )
        expect(wrapper.get('[aria-label="Strategy inspector"]').text()).toContain(
            '20 candles',
        )
    })

    it('duplicates a built-in and opens the editable custom result', async () => {
        const wrapper = mountWorkspace()
        await flushPromises()

        const duplicateButton = wrapper
            .findAll('button')
            .find((button) => button.text().includes('Duplicate selected'))
        expect(duplicateButton).toBeDefined()
        await duplicateButton?.trigger('click')
        await flushPromises()

        expect(apiMocks.duplicateStrategy).toHaveBeenCalledWith(
            builtin.slug,
            `${builtin.name} copy`,
        )
        expect(wrapper.text()).toContain('Custom copy created')
        expect(wrapper.text()).toContain('Editable custom graph')
    })

    it('creates, validates, saves, and deletes a custom strategy', async () => {
        const blank = {
            ...custom,
            slug: 'custom_strategy',
            name: 'Custom strategy',
        }
        apiMocks.createBlankStrategy.mockResolvedValue(detail(blank))
        apiMocks.fetchStrategyDetail.mockImplementation((slug: string) => {
            const strategy =
                slug === blank.slug
                    ? blank
                    : slug === custom.slug
                      ? custom
                      : builtin
            return Promise.resolve(detail(strategy))
        })
        apiMocks.saveStrategyVersion.mockResolvedValue({
            ...detail(custom),
            active_version: 2,
            lock_version: 2,
        })
        apiMocks.deleteStrategy.mockResolvedValue(undefined)
        const mounted = mountWorkspaceState()
        await flushPromises()

        await mounted.state.createBlank()
        expect(apiMocks.createBlankStrategy).toHaveBeenCalledWith(
            'Custom strategy',
        )

        await mounted.state.selectStrategy(custom.slug)
        mounted.state.draftName.value = 'EMA custom'
        mounted.state.draftDescription.value = 'Reviewed graph'
        await mounted.state.validateDraft()
        expect(apiMocks.validateStrategy).toHaveBeenCalled()

        await mounted.state.saveActiveVersion()
        expect(apiMocks.saveStrategyVersion).toHaveBeenCalledWith(
            custom.slug,
            expect.objectContaining({
                name: 'EMA custom',
                description: 'Reviewed graph',
            }),
            1,
        )

        await mounted.state.selectStrategy(custom.slug)
        await mounted.state.deleteSelected()
        expect(mounted.confirmDelete).toHaveBeenCalledWith(custom.name)
        expect(apiMocks.deleteStrategy).toHaveBeenCalledWith(custom.slug)
    })

    it('edits graph parameters, connections, layout, and decision state', async () => {
        const mounted = mountWorkspaceState()
        await flushPromises()
        await mounted.state.selectStrategy(custom.slug)

        mounted.state.selectedNodeId.value = 'ema'
        mounted.state.updateNodeParam('length', '21')
        mounted.state.updateNodeParamValue('sample', 'previous')
        mounted.state.updateNodeParamValue('sample', null)
        mounted.state.updateIndicatorSelection('rsi')
        mounted.state.updateIndicatorSelection('bollinger_upper')
        mounted.state.updateIndicatorSelection('macd_line')
        mounted.state.updateIndicatorSelection('custom')
        mounted.state.updateIndicatorSelection(null)

        const current = mounted.state.selectedDetail.value
        expect(current).not.toBeNull()
        if (!current) {
            return
        }
        current.ir.connections = []
        mounted.state.connectSelectedToDecision()
        mounted.state.connectSelectedToDecision()

        mounted.state.selectedNodeId.value = 'decision'
        mounted.state.updateSelectedInput('left', 'ema')
        mounted.state.updateSelectedInput('value1', null)
        mounted.state.autoAlignGraph()
        current.ir.root = ''
        mounted.state.addNodeFromPalette('indicator')
        mounted.state.addNodeFromPalette('missing')
        mounted.state.setDecisionNode('indicator_4')
        mounted.state.connectSelectedToDecision()
        mounted.state.bindReteHost(document.createElement('div'))
        mounted.state.bindReteHost(null)
        await flushPromises()
        await mounted.state.validateDraft()

        expect(
            current.ir.nodes.find((node) => node.id === 'ema')?.position,
        ).toBeDefined()
        expect(current.ir.root).toBe('indicator_4')
        expect(apiMocks.validateStrategy).toHaveBeenCalled()
    })

    it('keeps built-ins read-only and handles cancellation and conflicts', async () => {
        const confirmDelete = vi.fn().mockResolvedValue(false)
        const mounted = mountWorkspaceState(confirmDelete)
        await flushPromises()

        mounted.state.addNodeFromPalette('indicator')
        mounted.state.updateNodeParam('length', '50')
        mounted.state.updateNodeParamValue('length', 50)
        mounted.state.updateIndicatorSelection('ema')
        mounted.state.updateSelectedInput('value1', 'ema')
        mounted.state.setDecisionNode('ema')
        await mounted.state.deleteSelected()
        expect(confirmDelete).not.toHaveBeenCalled()

        await mounted.state.selectStrategy(custom.slug)
        await mounted.state.deleteSelected()
        expect(apiMocks.deleteStrategy).not.toHaveBeenCalled()

        apiMocks.isStrategyConflict.mockReturnValue(true)
        apiMocks.saveStrategyVersion.mockRejectedValueOnce(
            new Error('stale draft'),
        )
        await mounted.state.saveActiveVersion()
        expect(mounted.state.draftConflict.value).toBe(true)
        expect(mounted.state.errorMessage.value).toContain('stale draft')
    })

    it('surfaces library, detail, mutation, and validation failures', async () => {
        apiMocks.fetchStrategyLibrary.mockRejectedValueOnce(
            new Error('library offline'),
        )
        const mounted = mountWorkspaceState()
        await flushPromises()
        expect(mounted.state.errorMessage.value).toContain('library offline')

        apiMocks.fetchStrategyDetail.mockRejectedValueOnce(
            new Error('detail offline'),
        )
        await mounted.state.selectStrategy('missing')
        expect(mounted.state.errorMessage.value).toContain('detail offline')

        mounted.state.selectedDetail.value = detail(custom)
        apiMocks.duplicateStrategy.mockRejectedValueOnce(
            new Error('duplicate failed'),
        )
        await mounted.state.duplicateSelected()
        expect(mounted.state.errorMessage.value).toContain('duplicate failed')

        apiMocks.createBlankStrategy.mockRejectedValueOnce(
            new Error('create failed'),
        )
        await mounted.state.createBlank()
        expect(mounted.state.errorMessage.value).toContain('create failed')

        apiMocks.validateStrategy.mockRejectedValueOnce(
            new Error('validation failed'),
        )
        await mounted.state.validateDraft()
        expect(mounted.state.errorMessage.value).toContain(
            'validation failed',
        )
    })

    it('ignores validation responses from superseded edits', async () => {
        const mounted = mountWorkspaceState()
        await flushPromises()
        await mounted.state.selectStrategy(custom.slug)

        let resolveFirst!: (value: StrategyValidation) => void
        let resolveSecond!: (value: StrategyValidation) => void
        const firstResponse = new Promise<StrategyValidation>((resolve) => {
            resolveFirst = resolve
        })
        const secondResponse = new Promise<StrategyValidation>((resolve) => {
            resolveSecond = resolve
        })
        apiMocks.validateStrategy
            .mockImplementationOnce(() => firstResponse)
            .mockImplementationOnce(() => secondResponse)

        const firstValidation = mounted.state.validateDraft()
        const secondValidation = mounted.state.validateDraft()
        const valid = detail(custom).validation
        const staleInvalid: StrategyValidation = {
            ...valid,
            status: 'invalid',
            blocking_errors: ['stale response'],
        }

        resolveSecond(valid)
        await secondValidation
        resolveFirst(staleInvalid)
        await firstValidation

        expect(mounted.state.validation.value.status).toBe('valid')
        expect(mounted.state.validation.value.blocking_errors).toEqual([])
    })

    it('debounces validation while graph edits are still arriving', async () => {
        const mounted = mountWorkspaceState()
        await flushPromises()
        await mounted.state.selectStrategy(custom.slug)
        mounted.state.selectedNodeId.value = 'ema'
        apiMocks.validateStrategy.mockClear()
        vi.useFakeTimers()

        try {
            mounted.state.updateNodeParam('length', '21')
            await Promise.resolve()
            await vi.advanceTimersByTimeAsync(100)
            mounted.state.updateNodeParam('length', '22')
            await Promise.resolve()
            await vi.advanceTimersByTimeAsync(199)

            expect(apiMocks.validateStrategy).not.toHaveBeenCalled()

            await vi.advanceTimersByTimeAsync(1)
            await flushPromises()

            expect(apiMocks.validateStrategy).toHaveBeenCalledTimes(1)
        } finally {
            vi.useRealTimers()
            mounted.wrapper.unmount()
        }
    })

    it('cancels pending validation work when the workspace unmounts', async () => {
        const timerMounted = mountWorkspaceState()
        await flushPromises()
        await timerMounted.state.selectStrategy(custom.slug)
        timerMounted.state.selectedNodeId.value = 'ema'
        apiMocks.validateStrategy.mockClear()
        vi.useFakeTimers()

        try {
            timerMounted.state.updateNodeParam('length', '23')
            await Promise.resolve()
            timerMounted.wrapper.unmount()
            await vi.advanceTimersByTimeAsync(200)

            expect(apiMocks.validateStrategy).not.toHaveBeenCalled()
        } finally {
            vi.useRealTimers()
        }

        const requestMounted = mountWorkspaceState()
        await flushPromises()
        await requestMounted.state.selectStrategy(custom.slug)
        let validationSignal: AbortSignal | undefined
        apiMocks.validateStrategy.mockImplementationOnce((_ir, signal) => {
            validationSignal = signal
            return new Promise<StrategyValidation>(() => undefined)
        })

        void requestMounted.state.validateDraft()
        await Promise.resolve()
        requestMounted.wrapper.unmount()

        expect(validationSignal?.aborted).toBe(true)
    })

    it('invalidates an active response as soon as a new edit is scheduled', async () => {
        const mounted = mountWorkspaceState()
        await flushPromises()
        await mounted.state.selectStrategy(custom.slug)
        mounted.state.selectedNodeId.value = 'ema'
        let validationSignal: AbortSignal | undefined
        let resolveValidation!: (value: StrategyValidation) => void
        apiMocks.validateStrategy.mockImplementationOnce((_ir, signal) => {
            validationSignal = signal
            return new Promise<StrategyValidation>((resolve) => {
                resolveValidation = resolve
            })
        })
        const activeValidation = mounted.state.validateDraft()
        await Promise.resolve()
        vi.useFakeTimers()

        try {
            mounted.state.updateNodeParam('length', '24')
            await Promise.resolve()

            expect(validationSignal?.aborted).toBe(true)

            const staleInvalid: StrategyValidation = {
                ...detail(custom).validation,
                status: 'invalid',
                blocking_errors: ['stale during debounce'],
            }
            resolveValidation(staleInvalid)
            await activeValidation

            expect(mounted.state.validation.value.status).toBe('valid')
            expect(
                mounted.state.validation.value.blocking_errors,
            ).toEqual([])
        } finally {
            vi.useRealTimers()
            mounted.wrapper.unmount()
        }
    })
})
