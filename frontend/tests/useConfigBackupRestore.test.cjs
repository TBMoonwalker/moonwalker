const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const configViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'Config.vue'),
    'utf8',
)
const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
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
        configViewSource.includes(':ref="bindBackupFileInput"'),
        'expected Config.vue to bind the backup input through the composable seam',
    )
    assert.equal(
        controlCenterViewSource.includes(
            'function bindBackupFileInput(element: Element | null): void {',
        ),
        false,
    )
})
