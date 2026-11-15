import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ConfigBackupRestoreControls from '../src/components/config/ConfigBackupRestoreControls.vue'
import { useConfigBackupRestore } from '../src/composables/useConfigBackupRestore'
import type {
    BackupClassification,
    ClassificationFinding,
} from '../src/composables/useConfigBackupRestore'

const post = vi.hoisted(() => vi.fn())
const get = vi.hoisted(() => vi.fn())
vi.mock('axios', () => ({
    default: {
        post,
        get,
        isAxiosError: (error: unknown) => Boolean((error as { isAxiosError?: boolean })?.isAxiosError),
    },
}))

type FindingSeed = {
    code?: string
    severity?: string
    message?: string
    next_action?: string | null
}

function classifyResponse(findings: FindingSeed[]) {
    return {
        status: 200,
        data: {
            classification: {
                schema_version: 3,
                trade_mode_era: 'legacy_unspecified',
                includes_accumulation: false,
            },
            findings,
        },
    }
}

function restoreResponse() {
    return {
        status: 200,
        data: {
            message: 'Restored configuration successfully in paused dry-run mode.',
            result: { config_keys: 5 },
        },
    }
}

function createFlow() {
    const message = { error: vi.fn(), success: vi.fn(), warning: vi.fn() }
    return {
        message,
        flow: useConfigBackupRestore({
            apiUrl: (path: string) => path,
            hasUnsavedChanges: () => false,
            message,
            onBeforeReload: vi.fn(),
            reloadConfig: vi.fn(async () => {}),
        }),
    }
}

async function selectBackup(flow: ReturnType<typeof createFlow>['flow'], payload: unknown) {
    const file = new File([JSON.stringify(payload)], 'backup.json', {
        type: 'application/json',
    })
    const event = new Event('change', { bubbles: true })
    Object.defineProperty(event, 'target', { value: { files: [file] } })
    await flow.handleBackupFileSelected(event)
}

function classifyCalls() {
    return post.mock.calls.filter(
        call => String(call[0]) === '/config/backup/classify',
    )
}

function restoreCalls() {
    return post.mock.calls.filter(
        call => String(call[0]) === '/config/backup/restore',
    )
}

afterEach(() => {
    post.mockReset()
    get.mockReset()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
})

describe('backup classification preview', () => {
    it.each([
        ['config only', 'config', true],
        ['full backup', 'full', false],
    ] as const)('retains a failed %s preview until that scope succeeds', async (label, failedMode, configFails) => {
        if (configFails) {
            post.mockRejectedValueOnce(new Error('config preview unavailable'))
            post.mockResolvedValueOnce(classifyResponse([]))
        } else {
            post.mockResolvedValueOnce(classifyResponse([]))
            post.mockRejectedValueOnce(new Error('full preview unavailable'))
        }
        post.mockResolvedValueOnce(classifyResponse([]))
        vi.spyOn(window, 'confirm').mockReturnValue(false)
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [], trade_data: {} })

        expect(flow.restoreReview.value?.message).toContain(label)
        expect(flow.backupClassifications.value[failedMode]).toBeUndefined()

        const result = await flow.handleRestoreBackup(failedMode)
        expect(result.status).toBe('noop')
        expect(flow.backupClassifications.value[failedMode]?.blocking).toBe(false)
        expect(flow.restoreReview.value).toBeNull()
        expect(restoreCalls()).toHaveLength(0)
    })

    it.each([
        ['empty response', {}],
        ['missing findings', { classification: { schema_version: 3, trade_mode_era: 'dynamic_dca', includes_accumulation: false } }],
        ['unknown severity', classifyResponse([{ code: 'risk', severity: 'critical', message: 'Review required.' }]).data],
        ['malformed finding', classifyResponse([{ code: 'risk', severity: 'blocking' }]).data],
    ])('blocks restore on a malformed successful preview: %s', async (_label, data) => {
        post.mockResolvedValue({ status: 200, data })
        const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('config')

        expect(result.status).toBe('blocked')
        expect(flow.restoreReview.value?.code).toBe('preview_unavailable')
        expect(flow.backupClassifications.value.config).toBeUndefined()
        expect(confirm).not.toHaveBeenCalled()
        expect(restoreCalls()).toHaveLength(0)
    })

    it('does not reuse a pending preview after the selected backup changes', async () => {
        let resolveFirst!: (value: ReturnType<typeof classifyResponse>) => void
        post.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
        post.mockResolvedValueOnce(classifyResponse([
            { code: 'invalid_trade_data', severity: 'blocking', message: 'Invalid backup.' },
        ]))
        const { flow } = createFlow()
        const first = selectBackup(flow, { schema_version: 3, config: [], marker: 'first' })
        await vi.waitFor(() => expect(classifyCalls()).toHaveLength(1))
        const second = selectBackup(flow, { schema_version: 3, config: [], marker: 'second' })
        await vi.waitFor(() => expect(flow.selectedBackupPayload.value).toEqual(expect.objectContaining({ marker: 'second' })))
        resolveFirst(classifyResponse([]))
        await Promise.all([first, second])

        expect(classifyCalls()).toHaveLength(2)
        expect(flow.backupClassifications.value.config?.blocking).toBe(true)
    })

    it('does not restore or retain a preview after the selection is cleared', async () => {
        let resolvePreview!: (value: ReturnType<typeof classifyResponse>) => void
        post.mockImplementationOnce(() => new Promise(resolve => { resolvePreview = resolve }))
        const { flow } = createFlow()
        const selection = selectBackup(flow, { schema_version: 3, config: [] })
        await vi.waitFor(() => expect(classifyCalls()).toHaveLength(1))
        const restore = flow.handleRestoreBackup('config')
        flow.clearSelectedBackup()
        resolvePreview(classifyResponse([]))
        await selection
        expect((await restore).status).toBe('noop')
        expect(restoreCalls()).toHaveLength(0)
        expect(flow.backupClassifications.value).toEqual({})
        expect(flow.classificationLoading.value).toBe(false)
    })

    it('does not submit two restores while the preview is pending', async () => {
        let resolvePreview!: (value: ReturnType<typeof classifyResponse>) => void
        post.mockImplementationOnce(() => new Promise(resolve => { resolvePreview = resolve }))
        post.mockResolvedValueOnce(restoreResponse())
        vi.spyOn(window, 'confirm').mockReturnValue(true)
        const { flow } = createFlow()
        const selection = selectBackup(flow, { schema_version: 3, config: [] })
        await vi.waitFor(() => expect(classifyCalls()).toHaveLength(1))
        const first = flow.handleRestoreBackup('config')
        const second = flow.handleRestoreBackup('config')
        resolvePreview(classifyResponse([]))
        await selection
        const outcomes = await Promise.all([first, second])
        expect(outcomes.map(outcome => outcome.status).sort()).toEqual(['noop', 'success'])
        expect(restoreCalls()).toHaveLength(1)
    })

    it('classifies per mode before the confirmation and then restores', async () => {
        post.mockResolvedValueOnce(
            classifyResponse([
                { code: 'forced_dry_run_pause', severity: 'info', message: 'Paused dry-run.', next_action: null },
            ]),
        )
        post.mockResolvedValueOnce(restoreResponse())
        const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => true)
        const { flow } = createFlow()
        const payload = { schema_version: 3, config: [{ key: 'timezone', value: 'UTC', value_type: 'str' }] }

        await selectBackup(flow, payload)
        const result = await flow.handleRestoreBackup('config')

        expect(result.status).toBe('success')
        expect(classifyCalls()).toHaveLength(1)
        expect(classifyCalls()[0][1]).toEqual({
            backup: payload,
            restore_trade_data: false,
        })
        const restoreCall = restoreCalls()[0]
        expect(restoreCall?.[1]).toEqual(
            expect.objectContaining({ confirm: true, restore_trade_data: false }),
        )
        expect(confirm).toHaveBeenCalledTimes(1)
    })

    it('sends restore_trade_data true for full restores', async () => {
        post.mockResolvedValueOnce(classifyResponse([]))
        post.mockResolvedValueOnce(classifyResponse([]))
        post.mockResolvedValueOnce(restoreResponse())
        const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => true)
        const { flow } = createFlow()
        await selectBackup(flow, {
            schema_version: 3,
            config: [],
            trade_data: { trades: [] },
        })

        await flow.handleRestoreBackup('full')

        // Pre-classification previews both restore scopes on file selection.
        expect(classifyCalls()).toHaveLength(2)
        expect(classifyCalls()[0][1]).toEqual(
            expect.objectContaining({ restore_trade_data: false }),
        )
        expect(classifyCalls()[1][1]).toEqual(
            expect.objectContaining({ restore_trade_data: true }),
        )
    })

    it('blocks the restore and the confirmation on a blocking finding', async () => {
        post.mockResolvedValueOnce(
            classifyResponse([
                {
                    code: 'campaign_residue',
                    severity: 'blocking',
                    message: 'Restore aborted: legacy campaign residue.',
                    next_action: 'Clear the campaign_id values first.',
                },
            ]),
        )
        const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => true)
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('config')

        expect(result.status).toBe('blocked')
        expect(confirm).not.toHaveBeenCalled()
        expect(post).toHaveBeenCalledTimes(1)
        expect(flow.backupClassifications.value.config?.blocking).toBe(true)
        const finding = flow.backupClassifications.value.config?.findings[0]
        expect(finding).toMatchObject({
            code: 'campaign_residue',
            severity: 'blocking',
            nextAction: 'Clear the campaign_id values first.',
        })
    })

    it('keeps a blocking classification on repeated clicks without refetching', async () => {
        post.mockResolvedValueOnce(
            classifyResponse([
                { code: 'campaign_residue', severity: 'blocking', message: 'residue' },
            ]),
        )
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const first = await flow.handleRestoreBackup('config')
        const second = await flow.handleRestoreBackup('config')

        expect(first.status).toBe('blocked')
        expect(second.status).toBe('blocked')
        expect(classifyCalls()).toHaveLength(1)
    })

    it('continues when the preview is unavailable because restore re-checks', async () => {
        post.mockRejectedValueOnce({
            isAxiosError: true,
            response: { status: 500, data: { message: 'preview down' } },
        })
        post.mockResolvedValueOnce(classifyResponse([]))
        post.mockResolvedValueOnce(restoreResponse())
        const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => true)
        const { flow, message } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('config')

        expect(result.status).toBe('success')
        expect(message.warning).toHaveBeenCalled()
    })

    it('blocks restore visibly when classification remains unavailable without toasts', async () => {
        post.mockRejectedValue(new Error('preview unavailable'))
        vi.spyOn(window, 'confirm').mockReturnValue(true)
        const message = { error: vi.fn(), success: vi.fn(), warning: vi.fn() }
        const flow = useConfigBackupRestore({
            apiUrl: path => path,
            hasUnsavedChanges: () => false,
            message,
            onBeforeReload: vi.fn(),
            reloadConfig: vi.fn(async () => {}),
            surfaceMessages: false,
        })
        await selectBackup(flow, { schema_version: 3, config: [] })
        const result = await flow.handleRestoreBackup('config')
        expect(result.status).toBe('blocked')
        expect(flow.restoreReview.value?.message).toContain('review is unavailable')
        expect(restoreCalls()).toHaveLength(0)
    })

    it('resets the classification when the selection is cleared', async () => {
        post.mockResolvedValueOnce(
            classifyResponse([
                { code: 'campaign_residue', severity: 'blocking', message: 'residue' },
            ]),
        )
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })
        await flow.handleRestoreBackup('config')

        expect(flow.backupClassifications.value.config?.blocking).toBe(true)
        flow.clearSelectedBackup()

        expect(flow.backupClassifications.value).toEqual({})
    })

    it('resets the classification and re-classifies when a new backup file is selected', async () => {
        post.mockResolvedValueOnce(
            classifyResponse([
                { code: 'campaign_residue', severity: 'blocking', message: 'residue' },
            ]),
        )
        post.mockResolvedValueOnce(classifyResponse([]))
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })
        await flow.handleRestoreBackup('config')

        expect(flow.backupClassifications.value.config?.blocking).toBe(true)

        await selectBackup(flow, { schema_version: 3, config: [] })

        // The new file replaces the review and is pre-classified immediately.
        expect(classifyCalls()).toHaveLength(2)
        expect(flow.backupClassifications.value.config?.blocking).toBe(false)
    })
})

function stubFileDownload() {
    const createObjectURL = vi.fn(() => 'blob:download')
    const revokeObjectURL = vi.fn()
    const originalUrl = window.URL
    vi.stubGlobal(
        'URL',
        Object.assign(Object.create(originalUrl), {
            createObjectURL,
            revokeObjectURL,
        }),
    )
    return { createObjectURL, revokeObjectURL }
}

describe('backup download and file selection', () => {
    it('downloads a config-only backup by default', async () => {
        const { createObjectURL } = stubFileDownload()
        get.mockResolvedValueOnce({ status: 200, data: { config: [] } })
        const { flow } = createFlow()

        const result = await flow.handleBackupDownload()

        expect(result.status).toBe('success')
        expect(get).toHaveBeenCalledWith(
            '/config/backup/export',
            expect.objectContaining({ params: { include_trade_data: false } }),
        )
        expect(createObjectURL).toHaveBeenCalled()
    })

    it('surfaces a download failure as an error', async () => {
        stubFileDownload()
        get.mockRejectedValueOnce({
            isAxiosError: true,
            response: { status: 500, data: { message: 'export failed' } },
        })
        const { flow, message } = createFlow()

        const result = await flow.handleBackupDownload()

        expect(result.status).toBe('error')
        expect(message.error).toHaveBeenCalled()
    })

    it('rejects a selected file that is not a Moonwalker backup', async () => {
        const { flow, message } = createFlow()

        await selectBackup(flow, { unrelated: true })

        expect(flow.selectedBackupFileName.value).toBeNull()
        expect(message.error).toHaveBeenCalled()
    })

    it('rejects a selected file that is not valid JSON', async () => {
        const { flow, message } = createFlow()
        const file = new File(['{not json'], 'backup.json')
        const event = new Event('change', { bubbles: true })
        Object.defineProperty(event, 'target', { value: { files: [file] } })

        await flow.handleBackupFileSelected(event)

        expect(flow.selectedBackupFileName.value).toBeNull()
        expect(message.error).toHaveBeenCalled()
    })

    it('refuses a full restore when the backup has no trade data', async () => {
        post.mockResolvedValueOnce(classifyResponse([]))
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('full')

        expect(result.status).toBe('error')
        expect(restoreCalls()).toHaveLength(0)
    })
})

describe('restore outcome handling', () => {
    it('preserves a failed preview alongside a different restore review', async () => {
        post.mockRejectedValueOnce(new Error('config preview unavailable'))
        post.mockResolvedValueOnce(classifyResponse([]))
        post.mockRejectedValueOnce({
            isAxiosError: true,
            response: { status: 409, data: { migration_error: {
                code: 'campaign_residue', message: 'Clear campaign residue first.',
                next_action: 'See docs/operations.md.',
            } } },
        })
        vi.spyOn(window, 'confirm').mockReturnValue(true)
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [], trade_data: {} })
        expect((await flow.handleRestoreBackup('full')).status).toBe('blocked')
        expect(flow.restoreReview.value?.message).toContain('Clear campaign residue')
        expect(flow.restoreReview.value?.previewMessage).toContain('config only')
        post.mockResolvedValueOnce(restoreResponse())
        expect((await flow.handleRestoreBackup('full')).status).toBe('success')
        expect(flow.restoreReview.value?.message).toContain('config only')
    })

    it('surfaces a migration error as a blocked review state', async () => {
        post.mockResolvedValueOnce(classifyResponse([]))
        post.mockRejectedValueOnce({
            isAxiosError: true,
            response: {
                status: 409,
                data: {
                    message: 'Restore review required.',
                    migration_error: {
                        code: 'campaign_residue',
                        message: 'Clear campaign residue first.',
                        next_action: 'See docs/operations.md.',
                    },
                },
            },
        })
        const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => true)
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('config')

        expect(result.status).toBe('blocked')
        expect(confirm).toHaveBeenCalledTimes(1)
        expect(flow.restoreReview.value).toEqual({
            code: 'campaign_residue',
            message: 'Clear campaign residue first.',
            nextAction: 'See docs/operations.md.',
        })
    })

    it('reports a restore failure without a review as an error', async () => {
        post.mockResolvedValueOnce(classifyResponse([]))
        post.mockRejectedValueOnce({
            isAxiosError: true,
            response: { status: 500, data: { message: 'restore blew up' } },
        })
        const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => true)
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('config')

        expect(result.status).toBe('error')
        expect(flow.restoreReview.value).toBeNull()
    })

    it('cancels when the operator declines the confirmation', async () => {
        post.mockResolvedValueOnce(classifyResponse([]))
        const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => false)
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('config')

        expect(result.status).toBe('noop')
        expect(restoreCalls()).toHaveLength(0)
    })

    it('warns when history refresh fails for restored symbols', async () => {
        post.mockResolvedValueOnce(classifyResponse([]))
        post.mockResolvedValueOnce({
            status: 200,
            data: {
                message: 'Restored.',
                result: { history_failed_symbols: ['AAA/USDC'] },
            },
        })
        const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => true)
        const { flow, message } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('config')

        expect(result.status).toBe('success')
        expect(result.message).toContain('History refresh failed')
        expect(message.warning).toHaveBeenCalled()
    })
})

describe('backup classification panel', () => {
    function blockingClassification(
        findings: ClassificationFinding[],
    ): BackupClassification {
        return {
            mode: 'config',
            schemaVersion: 1,
            tradeModeEra: 'legacy_unspecified',
            includesAccumulation: false,
            findings,
            blocking: findings.some(finding => finding.severity === 'blocking'),
        }
    }

    function baseProps() {
        return {
            bindBackupFileInput: () => {},
            hasSelectedBackupPayload: true,
            restoreLoading: false,
            selectedBackupConfigCount: 5,
            selectedBackupFileName: 'backup.json',
            selectedBackupHasTradeData: true,
        }
    }

    it('renders both a restore review and an unavailable preview', () => {
        const wrapper = mount(ConfigBackupRestoreControls, {
            props: {
                ...baseProps(),
                restoreReview: {
                    code: 'campaign_residue', message: 'Clear campaign residue first.',
                    nextAction: null, previewMessage: 'Backup review is unavailable for config only.',
                },
            },
        })
        expect(wrapper.text()).toContain('Clear campaign residue first.')
        expect(wrapper.text()).toContain('Backup review is unavailable for config only.')
    })

    it('renders the findings and disables only the blocked restore mode', () => {
        const classification = blockingClassification([
            {
                code: 'campaign_residue',
                severity: 'blocking',
                message: '2 open trade row(s) with legacy campaign residue.',
                nextAction: 'See docs/operations.md.',
            },
            {
                code: 'forced_dry_run_pause',
                severity: 'info',
                message: 'A restore always finishes paused in dry-run mode.',
                nextAction: null,
            },
        ])
        const wrapper = mount(ConfigBackupRestoreControls, {
            props: {
                ...baseProps(),
                backupClassifications: { config: classification },
            },
        })

        expect(wrapper.text()).toContain('Backup review (config only restore)')
        expect(wrapper.text()).toContain('[Blocking]')
        expect(wrapper.text()).toContain('2 open trade row(s)')
        expect(wrapper.text()).toContain('See docs/operations.md.')
        expect(wrapper.find('[role="status"]').exists()).toBe(true)

        const buttons = wrapper.findAll('button')
        const configButton = buttons.find(button =>
            button.text().includes('Restore config only'),
        )
        const fullButton = buttons.find(button =>
            button.text().includes('Restore full backup'),
        )
        expect(configButton?.attributes('disabled')).toBeDefined()
        expect(configButton?.attributes('title')).toBe(
            '2 open trade row(s) with legacy campaign residue.',
        )
        expect(fullButton?.attributes('disabled')).toBeUndefined()
    })

    it('renders one alert per classified restore mode', () => {
        const configClassification = blockingClassification([
            {
                code: 'forced_dry_run_pause',
                severity: 'info',
                message: 'A restore always finishes paused in dry-run mode.',
                nextAction: null,
            },
        ])
        const fullClassification: BackupClassification = {
            ...blockingClassification([
                {
                    code: 'campaign_residue',
                    severity: 'blocking',
                    message: 'Legacy campaign residue blocks the full restore.',
                    nextAction: null,
                },
            ]),
            mode: 'full',
        }
        const wrapper = mount(ConfigBackupRestoreControls, {
            props: {
                ...baseProps(),
                backupClassifications: {
                    config: configClassification,
                    full: fullClassification,
                },
            },
        })

        expect(wrapper.text()).toContain('Backup review (config only restore)')
        expect(wrapper.text()).toContain('Backup review (full backup restore)')
        const fullButton = wrapper.findAll('button').find(button =>
            button.text().includes('Restore full backup'),
        )
        expect(fullButton?.attributes('disabled')).toBeDefined()
        expect(fullButton?.attributes('title')).toBe(
            'Legacy campaign residue blocks the full restore.',
        )
    })

    it('shows a loading hint while the preview is in flight', () => {
        const wrapper = mount(ConfigBackupRestoreControls, {
            props: {
                ...baseProps(),
                classificationLoading: true,
            },
        })

        expect(wrapper.text()).toContain('Reviewing backup…')
        expect(wrapper.find('[role="status"]').exists()).toBe(true)
    })
})
