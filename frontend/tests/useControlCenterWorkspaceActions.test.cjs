const assert = require('node:assert/strict')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useControlCenterWorkspaceActions } = loadFrontendModule(
    'src/composables/useControlCenterWorkspaceActions.ts',
)

function createWorkspaceActionsHarness(overrides = {}) {
    const announcements = []
    const navigations = []
    const transitions = []

    const actions = useControlCenterWorkspaceActions({
        announce(message) {
            announcements.push(message)
        },
        async handleBackupDownload() {
            return {
                status: 'success',
                message: 'Backup downloaded successfully.',
            }
        },
        async handleRestoreBackup() {
            return {
                status: 'success',
                message: 'Backup restored successfully.',
            }
        },
        async navigateToControlCenter(mode, target = null) {
            navigations.push([mode, target])
        },
        normalizeBlockers(rawBlockers) {
            return Array.isArray(rawBlockers) ? rawBlockers : []
        },
        now() {
            return 123
        },
        setTransitionIntent(intent) {
            transitions.push(intent)
        },
        async submitForm() {
            return {
                status: 'success',
                message: 'Configuration saved successfully.',
            }
        },
        async testMonitoringTelegram() {
            return {
                status: 'success',
                message: 'Telegram test sent.',
            }
        },
        ...overrides,
    })

    return {
        actions,
        announcements,
        navigations,
        transitions,
    }
}

test('workspace actions route successful saves into overview through the shared flow', async () => {
    const harness = createWorkspaceActionsHarness()

    await harness.actions.handleSubmitWorkspace()

    assert.deepEqual(harness.navigations, [['overview', null]])
    assert.deepEqual(harness.transitions, [
        {
            kind: 'save',
            status: 'success',
            message: 'Configuration saved.',
            at: 123,
            mode: 'overview',
        },
    ])
    assert.deepEqual(harness.announcements, ['Configuration saved.'])
})

test('workspace actions translate restore success into a restore transition', async () => {
    const harness = createWorkspaceActionsHarness()

    await harness.actions.handleRestoreBackupAction('config')

    assert.deepEqual(harness.navigations, [['overview', null]])
    assert.deepEqual(harness.transitions, [
        {
            kind: 'restore',
            status: 'success',
            message: 'Backup restored successfully.',
            at: 123,
            mode: 'overview',
        },
    ])
    assert.deepEqual(harness.announcements, ['Backup restored successfully.'])
})

test('workspace actions surface backup download failures as error transitions', async () => {
    const harness = createWorkspaceActionsHarness({
        async handleBackupDownload() {
            return {
                status: 'error',
                message: 'Backup download failed.',
            }
        },
    })

    await harness.actions.handleBackupDownloadAction()

    assert.deepEqual(harness.transitions, [
        {
            kind: 'save',
            status: 'error',
            message: 'Backup download failed.',
            at: 123,
        },
    ])
    assert.deepEqual(harness.announcements, ['Backup download failed.'])
})

test('workspace actions surface monitoring test failures as error transitions', async () => {
    const harness = createWorkspaceActionsHarness({
        async testMonitoringTelegram() {
            return {
                status: 'error',
                message: 'Telegram test failed.',
            }
        },
    })

    await harness.actions.handleMonitoringTestAction()

    assert.deepEqual(harness.transitions, [
        {
            kind: 'save',
            status: 'error',
            message: 'Telegram test failed.',
            at: 123,
        },
    ])
    assert.deepEqual(harness.announcements, ['Telegram test failed.'])
})
