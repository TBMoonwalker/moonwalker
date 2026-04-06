const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const configEditorAssemblySource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useConfigEditorAssembly.ts',
    ),
    'utf8',
)
const configViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'components', 'Config.vue'),
    'utf8',
)
const controlCenterViewSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'views', 'ControlCenterView.vue'),
    'utf8',
)

test('config editor assembly owns the shared config-editor composable stack', () => {
    const requiredAssemblySnippets = [
        "import { useConfigAdvancedGeneral } from './useConfigAdvancedGeneral'",
        "import { useConfigBackupRestore } from './useConfigBackupRestore'",
        "import { useConfigLoadFlow } from './useConfigLoadFlow'",
        "import { useConfigMonitoringTest } from './useConfigMonitoringTest'",
        "import { useConfigPageState } from './useConfigPageState'",
        "import { useConfigPersistableState } from './useConfigPersistableState'",
        "import { useConfigSaveFlow } from './useConfigSaveFlow'",
        "import { useConfigSignalFlow } from './useConfigSignalFlow'",
        "import { useConfigValidationFlow } from './useConfigValidationFlow'",
        'export function useConfigEditorAssembly(',
    ]
    const requiredViewSnippets = [
        "import { useConfigEditorAssembly } from '../composables/useConfigEditorAssembly'",
        '} = useConfigEditorAssembly({',
    ]
    const removedViewSnippets = [
        "import { useConfigAdvancedGeneral }",
        "import { useConfigBackupRestore }",
        "import { useConfigLoadFlow }",
        "import { useConfigMonitoringTest }",
        "import { useConfigPageState }",
        "import { useConfigPersistableState }",
        "import { useConfigSaveFlow }",
        "import { useConfigSignalFlow }",
        "import { useConfigValidationFlow }",
        "import { buildConfigRules }",
        "import { buildConfigSubmitPayload }",
    ]

    for (const snippet of requiredAssemblySnippets) {
        assert.ok(
            configEditorAssemblySource.includes(snippet),
            `expected config editor assembly to include ${snippet}`,
        )
    }

    for (const snippet of requiredViewSnippets) {
        assert.ok(
            configViewSource.includes(snippet),
            `expected Config.vue to include ${snippet}`,
        )
        assert.ok(
            controlCenterViewSource.includes(snippet),
            `expected ControlCenterView.vue to include ${snippet}`,
        )
    }

    for (const snippet of removedViewSnippets) {
        assert.equal(
            configViewSource.includes(snippet),
            false,
            `expected Config.vue to remove ${snippet}`,
        )
        assert.equal(
            controlCenterViewSource.includes(snippet),
            false,
            `expected ControlCenterView.vue to remove ${snippet}`,
        )
    }
})
