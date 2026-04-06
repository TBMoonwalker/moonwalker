const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const configViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'Config.vue'),
    'utf8',
)
const utilitiesWorkspaceSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterUtilitiesWorkspace.vue',
    ),
    'utf8',
)
const setupRestoreFlowSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'control-center',
        'ControlCenterSetupRestoreFlow.vue',
    ),
    'utf8',
)
const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
    'utf8',
)
const backupDownloadControlsSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'config',
        'ConfigBackupDownloadControls.vue',
    ),
    'utf8',
)
const backupRestoreControlsSource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'components',
        'config',
        'ConfigBackupRestoreControls.vue',
    ),
    'utf8',
)

const { useConfigBackupRestore } = loadFrontendModule(
    'src/composables/useConfigBackupRestore.ts',
)

function createBackupRestoreHarness(overrides = {}) {
    const flow = useConfigBackupRestore({
        apiUrl(path) {
            return `http://moonwalker.test${path}`
        },
        hasUnsavedChanges() {
            return false
        },
        message: {
            error() {},
            success() {},
            warning() {},
        },
        onBeforeReload() {},
        async reloadConfig() {},
        surfaceMessages: false,
        ...overrides,
    })

    return {
        flow,
    }
}

test.afterEach(() => {
    delete global.HTMLInputElement
})

test('config backup restore binds and reuses the backup input element through the composable seam', () => {
    let clicked = false

    class MockInput {
        constructor() {
            this.value = ''
        }

        click() {
            clicked = true
        }
    }

    global.HTMLInputElement = MockInput

    const harness = createBackupRestoreHarness()
    const input = new MockInput()

    harness.flow.bindBackupFileInput(input)

    assert.equal(harness.flow.backupFileInputRef.value, input)

    harness.flow.openBackupFilePicker()

    assert.equal(clicked, true)
})

test('config backup restore clears the bound input when the ref callback receives a non-input element', () => {
    class MockInput {
        constructor() {
            this.value = ''
        }
    }

    global.HTMLInputElement = MockInput

    const harness = createBackupRestoreHarness()

    harness.flow.bindBackupFileInput(new MockInput())
    harness.flow.bindBackupFileInput({})

    assert.equal(harness.flow.backupFileInputRef.value, null)
})

test('config editors delegate backup input binding to the backup-restore composable', () => {
    const requiredViewSnippets = [
        'bindBackupFileInput,',
        ':bind-backup-file-input="bindBackupFileInput"',
    ]

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected ControlCenterView.vue to include ${snippet}`,
        )
    }

    assert.ok(
        configViewSource.includes(
            ':bind-backup-file-input="bindBackupFileInput"',
        ),
        'expected Config.vue to pass backup input binding into the shared restore controls',
    )
    assert.ok(
        configViewSource.includes('<ConfigBackupRestoreControls'),
        'expected Config.vue to render the shared restore controls',
    )
    assert.equal(
        controlCenterViewSource.includes(
            'function bindBackupFileInput(element: Element | null): void {',
        ),
        false,
    )
})

test('backup and restore presentation is shared across config and control center surfaces', () => {
    const requiredBackupRestoreComponentSnippets = [
        ':ref="bindBackupFileInput"',
        'Restore config only',
        'Restore full backup',
    ]
    const requiredDownloadComponentSnippets = [
        'Include trade data in backup',
        'Download backup',
    ]
    const requiredConfigViewSnippets = [
        "import ConfigBackupDownloadControls from './config/ConfigBackupDownloadControls.vue'",
        "import ConfigBackupRestoreControls from './config/ConfigBackupRestoreControls.vue'",
        '<ConfigBackupDownloadControls',
        '<ConfigBackupRestoreControls',
    ]
    const requiredUtilitiesSnippets = [
        "import ConfigBackupDownloadControls from '../config/ConfigBackupDownloadControls.vue'",
        "import ConfigBackupRestoreControls from '../config/ConfigBackupRestoreControls.vue'",
        '<ConfigBackupDownloadControls',
        '<ConfigBackupRestoreControls',
    ]
    const requiredSetupRestoreSnippets = [
        "import ConfigBackupRestoreControls from '../config/ConfigBackupRestoreControls.vue'",
        '<ConfigBackupRestoreControls',
    ]

    for (const snippet of requiredBackupRestoreComponentSnippets) {
        assert.ok(
            backupRestoreControlsSource.includes(snippet),
            `expected ConfigBackupRestoreControls.vue to include ${snippet}`,
        )
    }
    for (const snippet of requiredDownloadComponentSnippets) {
        assert.ok(
            backupDownloadControlsSource.includes(snippet),
            `expected ConfigBackupDownloadControls.vue to include ${snippet}`,
        )
    }
    for (const snippet of requiredConfigViewSnippets) {
        assert.ok(
            configViewSource.includes(snippet),
            `expected Config.vue to include ${snippet}`,
        )
    }
    for (const snippet of requiredUtilitiesSnippets) {
        assert.ok(
            utilitiesWorkspaceSource.includes(snippet),
            `expected ControlCenterUtilitiesWorkspace.vue to include ${snippet}`,
        )
    }
    for (const snippet of requiredSetupRestoreSnippets) {
        assert.ok(
            setupRestoreFlowSource.includes(snippet),
            `expected ControlCenterSetupRestoreFlow.vue to include ${snippet}`,
        )
    }

    assert.equal(configViewSource.includes('class="backup-file-input"'), false)
    assert.equal(
        utilitiesWorkspaceSource.includes('class="backup-file-input"'),
        false,
    )
    assert.equal(
        setupRestoreFlowSource.includes('class="backup-file-input"'),
        false,
    )
})
