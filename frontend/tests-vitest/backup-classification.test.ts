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

afterEach(() => {
    post.mockReset()
    get.mockReset()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
})

describe('backup classification preview', () => {
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
        const restoreCall = post.mock.calls.find(
            call => String(call[0]) === '/config/backup/restore',
        )
        expect(restoreCall?.[1]).toEqual(
            expect.objectContaining({ confirm: true, restore_trade_data: false }),
        )
        expect(confirm).toHaveBeenCalledTimes(1)
    })

    it('sends restore_trade_data true for full restores', async () => {
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

        expect(classifyCalls()[0][1]).toEqual(
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
        expect(flow.backupClassification.value?.blocking).toBe(true)
        const finding = flow.backupClassification.value?.findings[0]
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
        post.mockResolvedValueOnce(restoreResponse())
        const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => true)
        const { flow, message } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('config')

        expect(result.status).toBe('success')
        expect(message.warning).toHaveBeenCalled()
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

        expect(flow.backupClassification.value).not.toBeNull()
        flow.clearSelectedBackup()

        expect(flow.backupClassification.value).toBeNull()
        expect(flow.backupClassifications.value).toEqual({})
    })

    it('resets the classification when a new backup file is selected', async () => {
        post.mockResolvedValueOnce(
            classifyResponse([
                { code: 'campaign_residue', severity: 'blocking', message: 'residue' },
            ]),
        )
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })
        await flow.handleRestoreBackup('config')

        await selectBackup(flow, { schema_version: 3, config: [] })

        expect(flow.backupClassification.value).toBeNull()
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
        const { flow } = createFlow()
        await selectBackup(flow, { schema_version: 3, config: [] })

        const result = await flow.handleRestoreBackup('full')

        expect(result.status).toBe('error')
        expect(post).not.toHaveBeenCalled()
    })
})

describe('restore outcome handling', () => {
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
        const restoreCalls = post.mock.calls.filter(
            call => String(call[0]) === '/config/backup/restore',
        )
        expect(restoreCalls).toHaveLength(0)
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
                backupClassification: classification,
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
        expect(fullButton?.attributes('disabled')).toBeUndefined()
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
